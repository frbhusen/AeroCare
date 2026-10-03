# Patients / Visits / Generic / Prescriptions / Files

Packages: `backend/app/modules/{patients,generic,prescriptions,files}/`. Tests: `tests/test_patients_*.py`, `tests/test_generic_api.py`, `tests/test_prescriptions_api.py`, `tests/test_files_api.py` (helpers in `tests/test_patients_common.py`).

## Purpose
One patient identity per center (spec §18–28), visits/encounters, the generic medical environment (§43), shared prescriptions (§42), patient files (§69–72, §87, §103), the access-scoped Complete Patient Summary (§22) with an extensible provider registry.

## Data models
- Core (models/clinical.py, models/files.py — unchanged): `Patient`, `PatientClinicLink`, `PatientDepartmentLink`, `Visit`, `Prescription`, `PrescriptionItem`, `StoredFile`, `FileShare`.
- `generic_visit_records` (modules/generic/models.py): one-to-one with `visits` (unique `visit_id`, composite FK CASCADE), `patient_id`, `clinic_id`, text fields (chief_complaint, symptoms, examination, diagnosis, assessment, treatment_plan, medications, notes), `vitals` JSON `{bp_systolic, bp_diastolic, heart_rate, temperature, resp_rate, spo2, weight, height}`, `extra` JSON (department-specific extension fields), author snapshot, `last_edited_by/name`, version.
- Extra index (register_sql): `ix_patients_center_search_prefix (health_center_id, search_name text_pattern_ops)` for 1–2 char prefix searches (trigram GIN indexes already in core).

## Endpoints (all `/api/v1`, `@login_required`; out of scope ⇒ 404, missing permission ⇒ 403)
### Patients (blueprint `patients`, no prefix)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | /patients/meta | patients.view | genders, blood types, visit types/statuses, accessible clinics, permission flags |
| GET | /patients?q=&clinic_id=&department_id=&page=&per_page= | patients.view | scoped (`patient_clause`). `q`: name terms (normalized, ANDed, trigram) and/or phone tokens (≥3 digits). Relevance order. **No COUNT**: returns `has_more`, `total: null` |
| GET | /patients/lookup?q=&date_of_birth= | patients.create | center-wide duplicate check, max 10: `id, code, display_code, full_name, date_of_birth, gender, phone_masked, accessible` |
| POST | /patients | patients.create + `clinic_id` in scope | code via `patient_seq`; creates clinic+department link. Returns detail (201) |
| GET | /patients/{id} | patients.view | profile + `departments` indicator + permission flags |
| PATCH | /patients/{id} | patients.edit | partial, `version` required |
| POST | /patients/{id}/link `{clinic_id}` | patients.create + clinic in scope | link an existing center patient (found via lookup) |
| DELETE | /patients/{id} | patients.delete; patients.delete_with_history if any table with `patient_id` has rows (visits, records, files, prescriptions, appointments, invoices…) | 403 `patient_outside_scope` if the patient is linked to clinics outside the caller's scope (center manager only). 202 + undo |
| GET | /patients/{id}/departments | patients.view | `[{department_id,name,type_code,environment,color,accessible, clinics[], visit_count}]` — restricted departments carry no clinics/counts |
| GET | /patients/{id}/visits | medical_records.view | visits in accessible clinics |
| GET | /patients/{id}/summary | patients.view | `{patient_id, sections:[{name,data}]}` |
### Visits
| GET | /visits?patient_id=&clinic_id=&department_id=&status=&visit_type=&date_from=&date_to= | medical_records.view | clinic-scoped; items include `patient` when not filtered by patient |
| POST | /visits | medical_records.create, clinic in scope, patient visible | via `services.clinical.create_visit` |
| GET | /visits/{id} | medical_records.view | |
| PATCH | /visits/{id} | medical_records.edit | version; visit_type, visit_at, title, notes, appointment_id |
| POST | /visits/{id}/complete, /visits/{id}/reopen `{version}` | medical_records.edit | |
| DELETE | /visits/{id} | medical_records.delete | 202 + undo. On purge: attached files are deleted too; prescriptions keep existing with `visit_id=NULL` |
### Generic environment (`/generic`, only clinics whose department environment is `generic`, else 422 `wrong_environment`)
| GET | /generic/meta | medical_records.view | vitals spec (key,min,max,unit,decimals), text fields, generic clinics |
| POST | /generic/visits `{patient_id, clinic_id, visit_type, visit_at, title, notes, record:{...}}` | medical_records.create | visit + record atomically |
| GET | /generic/visits/{visit_id} | medical_records.view | visit + `record` (null if none) + `bmi` |
| PUT | /generic/visits/{visit_id}/record | create: medical_records.create; update: medical_records.edit + `version` | partial fields |
| GET | /generic/patients/{id}/visits | medical_records.view | generic visits with record |
### Prescriptions (`/prescriptions`)
| GET | /prescriptions/meta | medical_records.view | statuses, clinics for creation |
| GET | /prescriptions?patient_id=&clinic_id=&visit_id=&department_id=&status=&date_from=&date_to= | medical_records.view | clinic-scoped |
| POST | /prescriptions `{patient_id, clinic_id, visit_id?, notes, items:[{medication_name, inventory_item_id?, dose, frequency, duration, instructions, quantity}]}` | medical_records.create, clinic in scope, patient visible | visit must be same patient+clinic; `inventory_item_id` validated against `inventory_items` of the center if that table exists |
| GET | /prescriptions/{id} | medical_records.view | with items |
| PUT | /prescriptions/{id} | medical_records.edit | only while `pending` (422 `prescription_not_pending`); `items` replaces all; version always bumps |
| POST | /prescriptions/{id}/cancel `{version}` | medical_records.edit | pending/partially_dispensed → cancelled |
| DELETE | /prescriptions/{id} | medical_records.delete | not if (partially) dispensed (422 `prescription_dispensed`); 202 + undo |
### Files (`/files`)
| GET | /files/meta | files.view | categories, upload categories, allowed extensions, max size, annotation types, clinics |
| GET | /files/storage | files.view | used/quota/remaining bytes |
| GET | /files/share-targets | files.share | active departments, clinics, doctors/managers |
| GET | /files?patient_id=&visit_id=&clinic_id=&department_id=&owner_type=&owner_id=&category=&q=&images_only= | files.view | `services.files.visible_clause` + patient visibility (unless center-wide / shared) |
| POST | /files (multipart: `files` (multiple) or `file`, `patient_id`, `clinic_id`, `visit_id?`, `category?`, `description?`) | files.upload + clinic in scope + patient visible | `services.files.store_upload` (allow-list + sniffing, 15 MB, quota lock). Returns `{items, storage}` |
| GET | /files/{id} | files.view | metadata (+ `shares` for managers) |
| GET | /files/{id}/content[?download=1] | files.view via `get_visible` | images/PDF inline, others attachment; safe RFC 5987 filename; `nosniff`; `CSP default-src 'none'`; `X-Frame-Options SAMEORIGIN`; `private, no-store`; ETag=sha256 |
| PATCH | /files/{id} `{version, display_name?, description?, category?}` | files.edit + can_manage | name sanitized, extension preserved |
| PUT | /files/{id}/annotations `{version, annotations:[{type, points[], text?, color?, width?}]}` | files.edit + can_manage | images only; ≤500 items |
| DELETE | /files/{id} | files.delete + can_manage | 202 + undo; purger removes bytes |
| GET/POST | /files/{id}/shares `{target_type: department|clinic|user, target_id}` | files.share + can_manage | targets must be active in same center; idempotent |
| DELETE | /files/{id}/shares/{share_id} | files.share + can_manage | revoke |
Visible-but-not-managed (shared) files ⇒ 403 `file_not_managed` on mutations.

## Deletion types registered
`patient` (files: `StoredFile.patient_id == id`; before_purge nulls `visit_id` on its files/prescriptions), `visit` (before_purge: attached files detached + staged as expired `file` deletions, prescriptions' `visit_id` nulled), `prescription`, `file` (files: `StoredFile.id == id`).

## Complete Patient Summary — provider contract
`backend/app/modules/patients/summary.py`:
```python
from backend.app.modules.patients.summary import register_summary_provider
register_summary_provider("dentistry", fn, order=200)   # lower order renders first; same name replaces
```
- `fn(p, patient)` is called only after the patient is visible to principal `p` and `p` has `patients.view`. `patient` is a live `Patient` of `p.center_id`.
- Return JSON-serializable dict/list, or `None` to omit the section (no permission / no data).
- **The provider is fully responsible for scoping**: check its own permission (`p.has("medical_records.view")` etc.), filter with `p.tenant(Model)`, `p.clinic_clause(Model.clinic_id)` and `Model.live()`. Never include details of departments/clinics outside scope.
- Read-only, bounded (e.g. latest 50 items). Runs in a SAVEPOINT; an exception omits the section in production (logged) and re-raises in TESTING.
- Register at import time of your module's `api.py` (or something it imports); importing `patients.summary` is cheap and safe from any module.
- Core sections: `profile` (0), `departments` (10), `visits` (20, grouped per accessible clinic, latest 200), `prescriptions` (40), `files` (50), `generic` (100).
- Response: `{"patient_id", "sections": [{"name", "data"}]}` (ordered list).

## Financial history hook
Not included here. Billing already exposes `GET /billing/patients/{id}/history`; the billing module should also register a `financial` summary provider (gated by `billing.view`, scoped) — the summary will then include it automatically.

## Status
Backend complete; all tests pass on healthcenter_test_2 (see final report). UI: later round.

## Known issues / notes
- Patient list/search returns `has_more` instead of `total` (avoids COUNT on 100k+ rows).
- Files belonging to a patient must carry `patient_id` (store_upload callers): patient purge cascades/collects bytes by `patient_id`.
- `get_visible` (core) lets any explicit share on a file bypass the patient-visibility rule for any principal that the share clause matched — intended (shares grant access).

## Needs from others
- **Core (lead)**: the composite FKs `tenant_fk(visit_id, "visits", ondelete="SET NULL")` on `files` and `prescriptions` make PostgreSQL null **both** columns `(health_center_id, visit_id)` → NOT NULL violation when a visit is hard-deleted. Worked around in my before_purge hooks; the proper fix is `ON DELETE SET NULL (visit_id)` (PG ≥15 column list) or RESTRICT. Any other module using `tenant_fk(..., ondelete="SET NULL")` has the same bug.
- Specialty modules: tables with `patient_id` automatically count as "history" for patient deletion; use CASCADE composite FKs to `patients`/`visits` so purges succeed.
- Billing: register a `financial` summary provider.
- Pharmacy: dispensing updates `Prescription.status` / `PrescriptionItem.dispensed_quantity` (edit locked once not pending).

## Core changes made
None.
