# Module: center (Health Center management)

**Purpose.** Center settings & branding, storage and plan usage, departments, clinics, staff accounts, permission customization, audit view, and the tenant-scoped export.
**Code.** `backend/app/modules/center/`: `api.py` (thin routes), `settings_service.py`, `org_service.py` (departments, clinics), `staff_service.py`, `perms_service.py` (permissions + audit view), `export.py`, `common.py` (`is_center_level`, `user_department_id`, `lock_center`, `revoke_sessions`).

## Management levels
- **Center level** = `center_manager` or Superadmin support view (`common.is_center_level`). It manages every department and clinic (including inactive ones) and every non-manager account.
- **Department manager** = `managed_department_ids` (own department). It manages that department's settings and clinics, doctors of its clinics, and receptionists whose *every* scope lies inside the department. It never manages managers, center-wide receptionists, role overrides or password resets.
- Out of scope ⇒ 404; in scope without permission or management right ⇒ 403. Plan-limit checks lock the center row (`SELECT ... FOR UPDATE`).

## Data models
The module has no tables of its own. It uses `health_centers`, `health_center_departments`, `clinics`, `users`, `user_scopes`, `role_permissions`, `user_permissions`, `files` (logo), `audit_logs`, `notifications`. Deletion types registered: `department`, `clinic`.

## Endpoints (`/api/v1/center`, all `@login_required`)
| Method | Path | Permission / rule | Notes |
|---|---|---|---|
| GET | `/settings` | settings.view | name, colors, currency, address, phone, footer, login_message, `logo_url`, `can_edit` |
| PATCH | `/settings` | center level + settings.edit | + `version` |
| POST/DELETE | `/settings/logo` | center level + settings.edit | multipart `file` png/jpg/webp ≤ 2 MB → `files` (category `branding`, center_wide). Previous logo row+bytes removed. Served by core `/branding/logo` |
| GET | `/storage` | settings.view | used/quota/remaining/% + per category |
| GET | `/limits` | settings.view | plan, status, each limit `{key,label,max,used,remaining}` (`max` null = unlimited), storage |
| GET | `/departments` | settings.view | center level: all; others: visible/managed. Includes type, environment, head, clinic_count, module_active, `can_manage` |
| GET | `/departments/meta` | settings.view | activated module types (`available` if no department yet), limits/usage, day keys |
| POST | `/departments` | center level + settings.edit | `{department_type_id, name?, color?, settings?}`. Only activated types; one per type (409 `department_exists`/`department_pending_delete`); `max_departments` |
| GET/PATCH | `/departments/<id>` | settings.view / settings.edit + manage | name, color, settings JSON, `is_active` (center level only) + `version` |
| PUT | `/departments/<id>/head` | center level + staff.edit | `{user_id \| null}`. Head must be an active department_manager of that department; `max_head_doctors` |
| DELETE | `/departments/<id>` | center level + settings.edit | 202 undo. 409 `department_in_use` if any row references it (clinics, staff, records) |
| GET | `/clinics?department_id=&include_inactive=&q=` | settings.view | center level: all; dept manager: own dept (incl. inactive); doctor: own clinic |
| POST | `/clinics` | settings.edit + manage dept | `{department_id, name, location, phone, email, working_hours, settings, notes, is_active}`; `max_clinics`; name unique per dept (409 `clinic_name_taken`) |
| GET/PATCH | `/clinics/<id>` | settings.view / settings.edit + manage | + `version` |
| DELETE | `/clinics/<id>` | settings.edit + manage | 202 undo. 409 `clinic_in_use` if staff/patients/records reference it (deactivate instead) |
| GET | `/staff?role=&status=&department_id=&clinic_id=&q=&page=` | staff.view | scoped (see below); each row has `can_manage`, `is_head`, `scopes` |
| GET | `/staff/meta` | staff.view | roles/scope types/departments/clinics the caller may assign, `can_reset_passwords` |
| POST | `/staff` | staff.create | `{role: doctor\|department_manager\|receptionist, username, name, password, email?, phone?, specialty_title?, clinic_id (doctor; optional working clinic for dept manager), department_id (dept manager), scopes:[{type: center\|department\|clinic, id}] (receptionist)}`. Dept manager: center level only, one per department, auto-becomes head (`max_head_doctors`). Limits `max_doctors`/`max_receptionists` |
| GET/PATCH | `/staff/<id>` | staff.view / staff.edit + manage | name, username, email, `reset_email`, phone, specialty_title + `version`. Generated email regenerates on rename (`accounts.apply_identity_change`) |
| POST | `/staff/<id>/reassign` | staff.edit + manage | `{clinic_id}` (doctors). Access switches immediately; sessions revoked (`scope_changed`); history stays with the old clinic |
| PUT | `/staff/<id>/scopes` | staff.edit + manage | `{scopes:[...]}` (receptionists), replaces all; sessions revoked |
| POST | `/staff/<id>/archive` / `reactivate` | staff.delete / staff.edit + manage | archive revokes sessions + clears head; reactivate re-checks plan limits / one manager per dept / clinic exists |
| POST | `/staff/<id>/password` | **center level only** (spec §7) + staff.edit | `{password}`; not for center managers or yourself; sessions revoked |
| DELETE | `/staff/<id>` | staff.delete + manage | hard delete if never referenced, else archived. Response `{deleted, archived, referenced_by?}` |
| GET | `/permissions` | permissions.manage | catalog + per role defaults/forbidden/overrides/effective/editable |
| PUT | `/permissions/roles/<role>` | center level + permissions.manage | role ∈ department_manager/doctor/receptionist. `{changes:{perm: true\|false\|null}}`. Notifies users of the role |
| GET/PUT | `/staff/<id>/permissions` | permissions.manage + manage target | per-user overrides `{changes:{perm: bool\|null}, note?}`. ROLE_FORBIDDEN ⇒ 422 `permission_forbidden`. A department manager cannot grant what it lacks. Notifies the user (`permission_changed`), audited as user edit |
| GET | `/audit?category=&action=&department_id=&date_from=&date_to=&q=&page=` | audit.view | center level: whole center; dept manager: entries with own `department_id` |
| GET | `/backup/export` | backup.create | ZIP download (see `docs/OPERATIONS.md` §3) |

Staff visibility (`staff_service.scope_clause`): center-wide principals see everyone. Others see themselves; doctors of their clinics and of their managed departments' clinics; department managers of visible departments; and receptionists with any scope touching those departments or clinics.

User "referenced" check (delete vs archive): any integer column in any table (except account-maintenance tables) that has an FK to `users.id` or is named `user_id`, `*_user_id`, `*_by`, `*_by_id` or `doctor_id`, holding the user id. As a fallback, an FK violation also leads to archiving.

## Audit
Department, clinic and user create/edit/delete are logged (`services.audit.log_change`) with `department_id`. For users this is the doctor's clinic department, the manager's department, or the receptionist's single department (NULL if center-wide or mixed). Changed field names are in `details.fields`.

## Status
Implemented and tested: `tests/test_center_org.py` (6), `tests/test_center_staff.py` (13).

## Known issues / notes
- Users have no undo-delete (only never-referenced accounts are hard-deleted; the rest are archived).
- Department/clinic delete refuses any referencing row, including rows of other modules (generic scan of `department_id`/`clinic_id` columns). This is intentionally conservative.
- Logging in updates `users.last_login_at`, which bumps the user `version`. A staff edit form open during the user's login gets a 409 and must reload. This could be fixed in core by excluding that column from versioning.
- Role changes of existing accounts (doctor ↔ department manager) are not supported; create a new account or archive the old one.

## Needs from others
- Appointments/other modules: read clinic `settings` / department `settings` (free JSON, e.g. `slot_minutes`, `default_duration_minutes`). Working hours format: `{"sat": [["09:00","13:00"],["16:00","20:00"]], ...}`, keys `sat..fri`, sorted, non-overlapping.
- Frontend core: handle 401 `session_ended` after reassignment/scope change/password reset (re-login).

## Core changes made
- None in this module (see admin.md for the audit trigger change).
