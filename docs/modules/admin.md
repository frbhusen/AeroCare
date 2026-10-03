# Module: admin (Superadmin portal)

**Purpose.** This module is the platform owner's portal. It manages health centers (trial, status, plan, limits, modules, quota, permanent delete), plans, department types, users across the platform, storage, audit logs, platform settings and login branding, and full backups.
**Code.** `backend/app/modules/admin/` (`api.py` routes, `service.py` centers, `platform_service.py` plans/types/users/audit/settings, `serializers.py`), `backend/app/services/backup.py`, `backend/app/services/demo.py`.
**DB mode.** Superadmin requests run in `platform` mode (RLS sees all centers). No center context: `/center/*` is reachable only through support view (`/auth/support/enter`).

## Data models
The module has no tables of its own. It uses core `plans`, `department_types`, `health_centers`, `health_center_modules`, `users`, `audit_logs` and `platform_settings`. Settings rows:
- `branding`: `{platform_name, primary_color, secondary_color, login_message, support_contact}`.
- `branding_logo`: `{mime, sha256, data(base64)}`. It holds PNG/JPEG/WebP only, ≤ 1 MB and content-sniffed. It is kept in the DB on purpose, so `ops storage-gc` cannot delete it and `pg_dump` backs it up.

## Endpoints (`/api/v1`)
All are `@superadmin_required` except the two public branding endpoints.

| Method | Path | Notes |
|---|---|---|
| GET | `/platform/branding` | **public**. Login page: name, colors, message, `logo_url` |
| GET | `/platform/branding/logo` | **public**. Logo bytes with a strict stored mime (png/jpeg/webp), `nosniff` |
| GET | `/admin/dashboard` | center counts by effective status, active users by role, storage totals, trials/subscriptions expiring in ≤ 7 days |
| GET | `/admin/meta` | form choices: plans, department types, roles, statuses, status actions, audit categories, environments |
| GET | `/admin/storage` | per-center used/quota/remaining/file count/% |
| GET | `/admin/centers?q=&status=&page=` | `status` ∈ trial/active/expired/suspended (effective: lapsed trials count as expired) |
| POST | `/admin/centers` | `{name, slug?, plan_code=basic, currency, modules:[codes], address?, phone?, notes?, manager?:{username,name,password,email?}}` → 14-day trial. Response includes `manager.email` |
| GET | `/admin/centers/<id>` | detail: limits, usage (`accounts.usage`), modules, user counts, storage used |
| PATCH | `/admin/centers/<id>` | name, slug, currency, address, phone, notes, colors, login_message, document_footer + `version` |
| POST | `/admin/centers/<id>/status` | `{action: activate, subscription_ends_at}` / `{action: extend_trial, days or trial_ends_at}` / `{action: expire}` / `{action: suspend}`. Dates `YYYY-MM-DD` = end of that Damascus day |
| PUT | `/admin/centers/<id>/plan` | `{plan_id}`: copies the plan limits (quota only increases) |
| PUT | `/admin/centers/<id>/limits` | partial `{max_departments, max_head_doctors, max_doctors, max_receptionists, max_clinics, storage_quota_bytes}`. `null` = unlimited. The quota cannot drop below current usage |
| PUT | `/admin/centers/<id>/modules` | `{modules:[codes]}`: exactly this set active (`services.centers.set_modules`) |
| POST | `/admin/centers/<id>/managers` | create an additional center manager |
| DELETE | `/admin/centers/<id>` | body `{confirm: <slug>}`. **Permanent**: deletes every tenant row (reverse FK order) and the stored files. Audit entries are kept, detached (`health_center_id` NULL) |
| GET/POST | `/admin/plans` | list (with `center_count`) / create `{code, name, max_*, storage_quota_bytes, is_active}` |
| PATCH/DELETE | `/admin/plans/<id>` | delete → 409 `plan_in_use` if assigned; deactivate instead |
| GET/POST | `/admin/department-types` | create = custom type `{name_en, name_ar, icon?, color?, sort_order?}`. Environment is always `generic`, code `custom_<slug>` |
| PATCH | `/admin/department-types/<id>` | names, icon, color, sort_order, `is_active` (deactivate) |
| GET | `/admin/users?center_id=&role=&status=&q=&page=` | all platform users, with `center_name` |
| GET/PATCH | `/admin/users/<id>` | name, username, email, `reset_email`, phone, specialty_title + `version`. Generated email regenerates on rename |
| POST | `/admin/users/<id>/password` | `{password}`: reset any account; revokes its sessions |
| POST | `/admin/users/<id>/archive` / `reactivate` | archive revokes sessions and clears department head. Reactivate enforces plan limits and one manager per department. Not allowed on yourself |
| POST | `/admin/superadmins` | create another superadmin |
| GET | `/admin/audit?category=&action=&center_id=&platform_only=1&date_from=&date_to=&q=&page=` | platform-wide audit (50/page) |
| GET/PUT | `/admin/settings` | platform branding |
| POST/DELETE | `/admin/settings/logo` | multipart `file` |
| GET/POST | `/admin/backups` | list / create full backup (`services.backup.create_full_backup`). 500 `backup_failed` with pg_dump stderr |
| GET | `/admin/backups/<name>/<file>` | `file` ∈ database.dump, files.zip, manifest.json (name regex-validated) |

Support view: the UI calls core `POST /auth/support/enter {center_id}` and then uses `/center/*`.

## Audit
User create/edit (password, status, identity fields) is logged with category `user`, the target's center and its department. Center/plan/module changes are not audit categories (spec §17), so they are not logged.

## Backups / demo
- `services/backup.py`: `create_full_backup(app)` writes `BACKUP_ROOT/hc-backup-<ts>/{database.dump, files.zip, manifest.json}`. `pg_dump` runs with `--enable-row-security` and `PGOPTIONS=-c app.mode=platform`, because FORCE RLS would otherwise abort the owner's dump. See `docs/OPERATIONS.md`.
- `services/demo.py`: `seed_demo_center(password, name=...)` for `flask dev seed-demo`. It creates an active enterprise center with all 11 modules, 13 clinics, a center manager, 2 department heads, one doctor per clinic and 3 receptionists (center/department/clinic scope), and returns the printable login lines. No medical data.

## Status
Implemented and tested (`tests/test_admin_portal.py`, 11 tests).

## Known issues
- A full backup through the API runs synchronously; Gunicorn `timeout=60` may cut very large backups. Use the CLI.
- Permanent delete of a center does not remove `login_attempts` rows (they are not tenant-scoped and only hold emails/IPs).
- Effective status: a lapsed trial is reported as `expired` (`status`) while `stored_status` may still say `trial` until the next login check persists it.

## Needs from others
- Frontend: superadmin portal UI (round 2, owned by this workstream).

## Core changes made
- `backend/app/schema/__init__.py` (`CORE_SQL`, `hc_audit_immutable`): allows exactly one UPDATE, the FK action `ON DELETE SET NULL` of `audit_logs.health_center_id` when a center is permanently deleted (only that column changes, to NULL, and the center no longer exists). The runtime role still has no UPDATE/DELETE privilege, and every other UPDATE/DELETE still raises. Accepted by the lead.
