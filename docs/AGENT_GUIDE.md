# Agent Guide — read first

Read only what your task needs: this file, then ARCHITECTURE.md / PERMISSIONS.md / DATABASE.md sections relevant to you, then your module doc in `docs/modules/`. The full product spec is `docs/SPEC.md` (search it; don't load it whole unless needed).

## Environment (Windows dev box)
- Python venv: `.venv/Scripts/python`, `.venv/Scripts/flask`. Node available for `node --check`.
- Dev Postgres: `127.0.0.1:55432` (project-local cluster in `.devdb/`, roles `hc_owner` superuser, `hc_schema` owner, `hc_app` runtime). Start if down:
  `"/c/Program Files/PostgreSQL/18/bin/pg_ctl" -D .devdb/data -o "-p 55432 -c listen_addresses=127.0.0.1" -l .devdb/pg.log start` (run in background; it holds stdout).
- Dev DB: `health_center` (set in `.env`; the older `healthcenter_dev` is no longer used). Rebuild schema: `.venv/Scripts/flask --app backend.wsgi db init-schema`.
- **Tests**: `.venv/Scripts/python -m pytest tests/<file>.py`. Each parallel agent MUST use its own test DB to avoid clobbering others (the suite drops/recreates the schema):
  `TEST_DATABASE_URL=postgresql+psycopg://hc_app@127.0.0.1:55432/healthcenter_test_N TEST_SCHEMA_DATABASE_URL=postgresql+psycopg://hc_schema@127.0.0.1:55432/healthcenter_test_N .venv/Scripts/python -m pytest ...`
  (N = your assigned number; DBs `healthcenter_test_1..12` exist).

## Directory ownership
| Path | Owner | Others may |
|---|---|---|
| `backend/app/{__init__,config,extensions,cli}.py`, `core/`, `authz/`, `auth/`, `schema/`, `models/`, `services/{accounts,centers,audit,deletion,files,notifications}.py`, `api/`, `tests/conftest.py`, `tests/factories.py` | **core (lead)** | read; minimal targeted edits only if blocking (see below) |
| `backend/app/modules/<m>/`, `tests/test_<m>*.py`, `docs/modules/<m>.md` | that module's agent | read |
| `backend/app/services/pdf.py`, `services/documents.py` | billing agent | call |
| `web/index.html`, `web/css/`, `web/js/core/`, `web/js/auth/`, `web/js/offline/`, `web/js/components/` | frontend-core agent | read/use |
| `web/js/<domain or environment>/` | that module's agent | read |
| `docs/{ARCHITECTURE,DATABASE,PERMISSIONS,API,MODULES,DECISIONS,TASK_STATUS,CHANGELOG}.md` | lead (integrates) | append to your module doc instead |

## Editing shared/core files
Avoid it. If you truly need a core change (new permission code, a model column on a core table, a helper):
1. Prefer doing it inside your module (own table, own helper).
2. Otherwise make the smallest targeted Edit (never rewrite the file), re-read the file right before editing, keep backwards compatible, run `tests/test_core_auth.py` afterwards.
3. Record it under "Core changes requested/made" in your `docs/modules/<m>.md`.
Never change: tenancy/RLS logic, session/auth flow, principal scope rules, error format — without the lead.

## Backend conventions
- Module package `backend/app/modules/<m>/`: `models.py`, `service.py`, `api.py` exporting `bp = Blueprint("<m>", __name__, url_prefix="/<prefix>")`. Auto-registered under `/api/v1`. No registry edits needed.
- Every route: `@login_required` (center context) or `@superadmin_required` / `@public` (rare). Then in the service: `p = current_principal()`; `p.require("perm", clinic_id=obj.clinic_id)`; list queries add `p.tenant(Model)` + `p.clinic_clause(Model.clinic_id)` (or `patient_clause`, `department_clause`) + `Model.live()`.
- Load single objects with a scoped query, not bare `db.session.get` (RLS is only a backstop). Out-of-scope ⇒ `NotFound`.
- Validate input with `core.validation.validate(request_json(), {...})`; never mass-assign dict keys to models.
- Versioned updates: `check_version(obj, data.get("version"))`.
- Deletes: register type once with `services.deletion.register(...)`, then `return jsonify(deletion.stage(p, obj, "<type>", label)), 202`.
- Medical records: `AuthorSnapshotMixin` + `obj.set_author(p.user)`; never update author fields later.
- New tenant tables: `TenantMixin`, `tenant_unique("<table>")`, `tenant_fk(...)` for every reference to a tenant table. RLS is applied automatically by init-schema.
- DB-level rules (exclusion constraints, partial indexes, triggers): `from backend.app.schema import register_sql` at module import; SQL must be idempotent (`IF NOT EXISTS`, `DROP ... IF EXISTS` then create).
- Serialization: explicit `to_json` functions; datetimes via `core.timeutil.iso`; money as `str(Decimal)`.
- Business logic in `service.py`; routes stay thin. No giant files (> ~600 lines ⇒ split).
- Logging: never log request bodies, medical or financial content.
- No email/SMS/payment gateways. No mock data as source of truth. No CSV export.
- Audit (`services.audit.log_change`) ONLY for department/clinic/user create/edit/delete (+ login, core). Never for medical/financial activity.
- Notifications: `services.notifications.notify(center_id, type, title, ..., clinic_id=...)` — operational text only.

## Tests (required before you report done)
- pytest files `tests/test_<module>_*.py` using fixtures `world`, `client_for`, `app` from conftest (see `tests/factories.py` for the standard center layout and user keys).
- Must cover: happy path, permission denial (403), out-of-scope (404) incl. **cross-tenant (center B user → center A object)**, clinic/department isolation where relevant, validation errors, version conflict on update, delete + undo where supported.
- Run your module tests + `tests/test_core_auth.py` with your own test DB. Leave nothing failing.

## Frontend conventions (see web/js/core/README.md once frontend-core lands)
Vanilla ES modules, no framework/bundler. Use core `api`, `router`, `i18n` (`t()` with en+ar keys in your module's i18n file), and shared components. Logical CSS properties only (RTL). No secrets, no authoritative data in localStorage; IndexedDB only for offline queue/cache. Every visible feature must be wired to a real endpoint or clearly marked unavailable. `node --check` every JS file you change.

## Communication
You cannot message other agents directly. Record cross-module needs in your module doc under "Needs from others". The lead integrates and relays. Keep your module doc current: purpose, data models, endpoints (method, path, permission), status, known issues.
