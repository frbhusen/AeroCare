# Database

PostgreSQL 18, SQLAlchemy 2. Schema created by `flask --app backend.wsgi db init-schema` (idempotent, run as schema owner). No Alembic yet (spec §107): changes to existing tables = additive idempotent SQL registered with `schema.register_sql()`.

Roles: `hc_schema` (owner, DDL), `hc_app` (runtime: DML only, NOBYPASSRLS). Extensions: `pg_trgm`, `btree_gist`.

## Conventions (all tenant tables)
- `health_center_id NOT NULL` FK → `health_centers` (TenantMixin) ⇒ RLS policy auto-generated.
- `UNIQUE(health_center_id, id)` + composite FKs via `tenant_fk()` ⇒ no cross-tenant references.
- `version` (VersionMixin) on editable records ⇒ optimistic locking.
- `pending_delete_until` (UndoDeleteMixin) on deletable records ⇒ hidden while staged; ALWAYS filter `Model.live()`.
- Medical records carry `author_user_id` + immutable `author_name`/`author_role` snapshots (AuthorSnapshotMixin).
- Timestamps `timestamptz` UTC; business dates Asia/Damascus.

## Core tables
| Table | Purpose / key columns |
|---|---|
| `plans` | plan templates; NULL limit = unlimited |
| `department_types` | platform specialty catalog (`code`, `environment` ∈ dentistry/dermatology/ophthalmology/radiology/laboratory/pharmacy/generic, `is_custom`) |
| `health_centers` | tenant root: status (trial/active/expired/suspended), trial/subscription end, effective limits (copied from plan, overridable), storage quota, branding, `patient_seq`/`invoice_seq` |
| `health_center_modules` | activated department types per center |
| `health_center_departments` | department in center; `head_user_id` (unique, nullable); settings JSON |
| `clinics` | `department_id`, name, `location` text, contact, working_hours JSON, settings JSON |
| `users` | global unique `lower(email)`; `(center, lower(username))` unique; role; status active/archived; `clinic_id` (doctor), `department_id` (dept manager) |
| `user_scopes` | receptionist assignments (center / department / clinic) |
| `user_sessions`, `login_attempts` | auth (no RLS; accessed in `auth` mode) |
| `role_permissions`, `user_permissions` | permission overrides |
| `patients` | one per person per center; `code` (PAT-000001 via `patient_seq`); `search_name` (normalized) + `phone_digits` with trigram GIN indexes |
| `patient_department_links`, `patient_clinic_links` | patient ↔ department/clinic membership (visibility) |
| `visits` | encounters: patient, department, clinic, author snapshot, `visit_at`, type, status |
| `prescriptions`, `prescription_items` | shared prescriptions (status pending → partially_dispensed/dispensed/cancelled) |
| `files`, `file_shares` | uploaded files (owner clinic/department, patient, visit, `owner_type/owner_id`), explicit shares |
| `audit_logs` | append-only (trigger + REVOKE UPDATE/DELETE); categories login/department/clinic/user |
| `notifications` | per-user in-app notifications |
| `offline_sync_operations` | `(user_id, op_id)` unique idempotency records |
| `deletion_buffer` | staged deletions (token, entity, expires_at) |

Module tables are listed in MODULES.md per module (owned by the module's `models.py`).

## Ownership
Medical data → health center + department + clinic + patient (+ visit). Doctor is historical metadata only. Billing rows → center + department + clinic (+ doctor). Inventory → center + location (clinic / department pool / center pool).

## Deletion
Staged delete → 30 s undo → hard delete with FK cascades (patient → links, visits, records, files rows; file bytes removed by purger). Patients with medical history require `patients.delete_with_history`. Users are archived, not deleted, once referenced. Audit logs are never deleted.

## Indexes (non-obvious)
- `patients`: GIN trigram on `search_name`, `phone_digits`; `(center, created_at)`.
- `visits`: `(center, clinic, patient, visit_at)`, `(center, department, visit_at)`.
- `appointments`: exclusion constraints on doctor/clinic time ranges (see appointments module).
- `audit_logs (center, created_at)`; `notifications (user, is_read, created_at)`.
