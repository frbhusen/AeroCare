# Architecture

Multi-tenant Health Center Management Platform. One URL, one app; portal chosen after login by role.

```
Platform (Superadmin)
└── Health Center (tenant)            health_centers
    ├── Department (specialty)        health_center_departments  (type from department_types)
    │   ├── Clinic (operational unit) clinics  (free-text location, not a branch)
    │   │   └── Doctors               users.clinic_id (exactly one)
    │   └── Department staff          head doctor = department.head_user_id; receptionists via user_scopes
    └── Center staff                  center_manager; center-wide receptionists
```

## Stack
Vanilla JS (ES modules, no framework/bundler) → Flask JSON API `/api/v1` → SQLAlchemy 2 → PostgreSQL 18.
Prod: Nginx (TLS, static `web/`) → Gunicorn → Flask → PostgreSQL + local secure file storage. See `deploy/`.

## Backend layout (`backend/app/`)
| Path | Role |
|---|---|
| `__init__.py` | `create_app()`: config, blueprints (`/api/v1`), before_request auth → CSRF → idempotency |
| `config.py` | env-driven config (Dev/Testing/Production) |
| `core/` | `tenancy` (DB tenant context → RLS), `errors`, `api` (pagination, version check), `validation`, `security` (CSRF, headers, X-Op-Id idempotency), `storage` (file backend + upload sniffing), `timeutil` |
| `authz/` | `permissions.py` (catalog + role defaults), `principal.py` (scope resolution, SQL scope clauses), `decorators.py` |
| `auth/service.py` | password hashing, server sessions, rate limit, principal loading |
| `models/` | core models: platform, users, org, clinical (patients/visits/prescriptions), files, ops |
| `services/` | shared business logic: accounts, centers, audit, deletion (undo), files, notifications |
| `api/` | core endpoints: auth, notifications, undo, health, branding |
| `modules/<name>/` | feature modules (`models.py`, `api.py` with `bp`, `service.py`); auto-discovered by `modules.load_all()` |
| `schema/` | idempotent schema init: create_all + RLS + module SQL + grants |
| `cli.py` | `db init-schema`, `admin create-superadmin`, `ops ...`, `backup create`, `dev seed-demo` |

Request flow: `API route → principal.require(...) / scope clause → service → ORM → PostgreSQL (RLS backstop)`.
Business logic lives in `service.py`, not route handlers.

## Authentication
- Login = email + password → server-side `user_sessions` row; cookie `hc_session` (HttpOnly, Secure in prod, SameSite=Lax) holds a random token; DB stores SHA-256 only.
- Single active session: login revokes all other sessions of the user (`revoked_reason=new_login` → client sees `session_replaced`).
- No inactivity logout. Archived users / expired centers are rejected on every request.
- CSRF: same-origin Origin/Referer check + session-bound `X-CSRF-Token` header on every mutation.
- Login rate limit: failures per email/IP window (`login_attempts`).
- First Superadmin: `flask --app backend.wsgi admin create-superadmin` (password prompted / env). No credentials in code.

## Multi-tenancy (defense in depth)
1. Principal resolved only from the session (never client-supplied center ids).
2. Every query filters `Model.health_center_id == p.center_id` (`p.tenant(Model)`) plus scope clauses.
3. Composite FKs `(health_center_id, x_id) → parent(health_center_id, id)` make cross-tenant links impossible.
4. PostgreSQL RLS (ENABLE + FORCE) on every table with `health_center_id`; runtime role `hc_app` is NOSUPERUSER NOBYPASSRLS and not the table owner. Policies read `app.mode` / `app.center_id` set per transaction by `core/tenancy.py`.
5. Fail closed: no context ⇒ no tenant rows. Modes: `tenant` (staff / superadmin support view), `platform` (superadmin portal, CLI, purger), `auth` (login/session lookups only).
6. Out-of-scope objects return 404 (existence is not revealed).

## Scope model (see PERMISSIONS.md)
`Principal` has `clinic_ids`, `managed_department_ids`, `visible_department_ids`, `center_wide`, `perms`. Departments whose module is inactive for the center are excluded for everyone.

## Files
`core/storage.LocalStorage` (keys `<center>/<yyyy>/<mm>/<random32hex>` under `STORAGE_ROOT`, outside web root). Uploads: extension allow-list + magic-byte sniffing (client MIME ignored), 15 MB/file, quota = SUM(files.size_bytes) checked under a center row lock (default 2 GB). Downloads only via authenticated `/api/v1/files/<id>/content` after `services.files.get_visible()`.

## Deletion / undo
`services/deletion.stage()` flags `pending_delete_until` (rows hidden via `Model.live()`), records `deletion_buffer` with a token; `/api/v1/undo` within 30 s restores; a purger thread (and `flask ops purge-deletions`) hard-deletes after expiry and removes cascaded file bytes. Server-authoritative.

## Concurrency
`VersionMixin` (`version` + SQLAlchemy `version_id_col`): clients send `version`; mismatch → 409 `version_conflict` (never silent overwrite). Sequences (patient code, invoice number) via `UPDATE health_centers ... RETURNING` row lock. Appointment double-booking prevented by PostgreSQL exclusion constraints (btree_gist).

## Offline
Online-first. Frontend `web/js/offline/` queues failed mutations in IndexedDB with a client UUID `X-Op-Id`; server claims op ids in `offline_sync_operations` before executing and replays stored responses for duplicates (idempotent). Conflicts surface as 409 → "Sync issue — requires attention". localStorage only for UI prefs (language).

## Frontend (`web/`)
Single `index.html`, ES modules under `web/js/`: `core/` (api, router, i18n, ui components, state), `auth/`, `offline/`, `portal/` (superadmin), `center/` (manager overview), per-domain folders (`patients/`, `appointments/`, `billing/`, `inventory/`, `files/`, `reports/`) and per-environment folders (`dentistry/`, `dermatology/`, `ophthalmology/`, `radiology/`, `laboratory/`, `pharmacy/`, `generic/`). Arabic/English with RTL/LTR (logical CSS properties). No light/dark switch.

## Production
See `deploy/` and `docs/OPERATIONS.md`: Nginx TLS + static files + proxy `/api` to Gunicorn (`backend.wsgi:app`), env file for secrets, DB pool, logs in `LOG_DIR` (no medical/financial content), manual backups (`flask backup create`, center export).
