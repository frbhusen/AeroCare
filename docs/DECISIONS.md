# Decisions

2026-10-03 — Hierarchy Health Center → Department → Clinic → Doctor. Clinics are operational units (free-text location), no branch entity.

2026-10-03 — Rebuild platform core fresh; port AeroDent dentistry domain. Reason: AeroDent's tenant = clinic; new tenant = health center with department/clinic scopes, new auth/permissions/files. Reference clone (read-only, never pushed): `../AeroDent-Online-ref`. Impact: dental models re-keyed to (center, clinic, patient); AeroDent offline PIN mode not carried over (replaced by online-first offline queue).

2026-10-03 — Tenant isolation = app filters + composite FKs + PostgreSQL RLS (FORCE) with runtime role `hc_app` (NOBYPASSRLS, not owner). Context via transaction-local `app.mode`/`app.center_id`. Fail closed.

2026-10-03 — Server-side session table with hashed tokens; single active session by revoking others at login. No JWT/localStorage tokens.

2026-10-03 — No Alembic (spec §107). `db init-schema` is idempotent create_all + SQL; changes must be additive idempotent SQL until a migration tool is adopted.

2026-10-03 — Delete+undo via `pending_delete_until` flag + `deletion_buffer` + purger (server-authoritative), not client timers or JSON snapshots.

2026-10-03 — Storage quota computed as SUM(files.size_bytes) under a center row lock (always consistent with cascaded deletes); `storage_used_bytes` is only a cache.

2026-10-03 — Superadmin support access = session `acting_center_id` (tenant DB mode) with read-only medical permissions (`SUPPORT_READ`).

2026-10-03 — Patient visibility via `patient_clinic_links`; a patient is created with an initial clinic link (registration requires a clinic/department within scope), so receptionists/doctors can find patients they register.

2026-10-03 — Finalized lab results are readable center-wide by staff with `medical_records.view` who can see the patient; radiology final reports go to the requesting clinic + explicit shares.

2026-10-03 — Frontend: native ES modules, no bundler. Language preference in localStorage (UI preference only).

2026-10-03 — Login page shows platform branding (one URL for all centers); center branding applies after login and on documents.

2026-10-03 — Parallel development by module agents with strict directory ownership (AGENT_GUIDE.md); each agent uses its own test database.

2026-10-03 — Duplicate prevention: `GET /patients/lookup?q=` (requires `patients.create`) searches the whole center but returns only minimal identity (code, name, DOB, gender, masked phone); staff then link the existing patient to their clinic instead of creating a second profile. Clinical details stay scope-restricted.
