# Dermatology (+ Laser Hair Removal)

Spec §23-25, §34-37, §73, §82-83. Dedicated environment `dermatology`. Every endpoint checks that the clinic belongs to a department with the `dermatology` environment (`services.clinical.require_environment`, wrong env → 422 `wrong_environment`). Scope: medical data is owned by center + department + clinic + patient + visit. Out-of-scope clinic, patient or record → 404. Missing permission → 403.

Code: `backend/app/modules/dermatology/`
- `regions.py`: shared body-region catalog, kept as data in code
- `models.py`
- `visitkit.py`: helpers for visit-owned detail records, shared with ophthalmology
- `service.py` and `api.py`: dermatology visits
- `laser_service.py` and `laser_api.py`: laser sessions (same blueprint)

## Data models
| Table | Notes |
|---|---|
| `derm_visit_records` | One-to-one with `visits` (`UNIQUE visit_id`). Fields: `affected_areas` (JSONB list of region codes), `condition`, `symptoms`, `severity` (mild/moderate/severe, CHECK), `diagnosis`, `examination_findings`, `treatment`, `notes`, `extra` (JSONB for extensible fields), `owns_visit`. Mixins: Version, UndoDelete, AuthorSnapshot. Composite tenant FKs to patient, department, clinic and visit use CASCADE. |
| `laser_sessions` | `patient`, `department`, `clinic`, optional `visit_id` (tenant FK CASCADE, unique), `owns_visit`, `session_number` (1-9999), `session_date` (local date), `notes`, `next_session_at`, `next_appointment_id` (integration point, not an FK), `extra`. Partial unique index `(center, patient, department, session_number) WHERE pending_delete_until IS NULL`. |
| `laser_session_areas` | `(session_id, region, side)` unique. `side` is front or back and must be one of the region's `views`. |

**Body regions** (`GET /dermatology/body-regions`): returns `{groups, regions:[{code,en,ar,views,group,mirror_of,order}], views}`. The codes are stable; they are intended to be used as 3D mesh ids and 2D SVG element ids. Left and right mean the patient's left and right.

**Session numbering**: the automatic number is the highest live number for that patient in that department, plus 1. It is computed under `pg_advisory_xact_lock(hashtextextended('laser_session_number:<center>:<patient>:<dept>'))`, so concurrent creates are serialized. The number can be edited. A duplicate number returns 409 `session_number_taken`, and the partial unique index acts as a database backstop.

## Endpoints (`/api/v1/dermatology`; all `@login_required`)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/meta` | login | Severities, visit types and statuses, photo categories, body regions |
| GET | `/body-regions` | login | Region catalog |
| GET | `/patients/<pid>/visits?clinic_id=&page=&per_page=` | medical_records.view | Patient must be visible; only records in the caller's clinics; includes `photo_count` and `clinic_name` |
| POST | `/visits` | medical_records.create | Pass either `{patient_id, clinic_id, visit_at?, visit_type?, title?, status?}`, which creates the visit as well (`owns_visit=true`), or `{visit_id}`, which attaches to an existing visit in a dermatology clinic. Both forms accept the derm fields. A second record on the same visit → 409 `already_exists` |
| GET | `/visits/<id>` | medical_records.view | |
| PATCH | `/visits/<id>` | medical_records.edit | Requires `version` (409 `version_conflict`). Visit fields (`visit_at`, `title`, `visit_type`, `status`) can only be changed when the record owns the visit; otherwise 422 `visit_not_owned` |
| DELETE | `/visits/<id>` | medical_records.delete | Returns 202 with an undo token. If the record owns the visit, the whole visit is staged (type `derm_visit`); otherwise only the record is staged (`derm_record`). The purge removes the attached file rows and their stored bytes |
| GET/POST | `/visits/<id>/photos` | files.view / files.upload | Multipart `files` (or `file`) with optional `category` (photo or medical_image) and `description`. Stored via `services.files.store_upload` with `owner_type='derm_visit'` and owned by the clinic |
| GET | `/laser/meta`, `/laser/body-regions` | login | |
| GET | `/laser/patients/<pid>/sessions?clinic_id=` | medical_records.view | Paginated, newest number first |
| GET | `/laser/patients/<pid>/history?clinic_id=` | medical_records.view | `{sessions (oldest first, with areas and labels), area_counts:[{region,count,sides,session_numbers,first_date,last_date}], last_session_date, next_session_at}` |
| GET | `/laser/patients/<pid>/next-number?clinic_id=` | medical_records.view | Suggested next number |
| POST | `/laser/sessions` | medical_records.create | `{patient_id, clinic_id \| visit_id, areas:[{region,side}] (at least 1), session_number?, session_date?, notes?, next_session_at?, create_visit? (default true → creates a visit of type 'session'), extra?}` |
| GET/PATCH/DELETE | `/laser/sessions/<id>` | view / edit (needs `version`) / delete | PATCH replaces the area set. Delete is staged (`laser_session`). The purge removes photos and the owned visit |
| GET/POST | `/laser/sessions/<id>/photos` | files.view / files.upload | `owner_type='laser_session'` |

There are no technical laser parameters in v1.

## Summary providers
These are registered with `patients.summary.register_summary_provider` as `dermatology` (order 210) and `laser_hair_removal` (order 215). Both are scoped to the caller's clinics. They can also be called directly: `service.patient_summary(p, patient_id)` and `laser_service.patient_summary(p, patient_id)`.

## Status
The backend is implemented. Tests are in `tests/test_dermatology.py` (11) and `tests/test_dermatology_laser.py` (8), plus shared helpers in `tests/test_dermatology_support.py`. The UI comes in a later round.

## Known issues / notes
- Undo after the session number was reused while the original session was staged hits the unique index. It returns 409 and the user has to renumber.
- While a non-owning derm record is staged, its photos stay visible through the generic files API until the purge.
- Deleting a visit elsewhere (for example from the patients module) cascades to that visit's derm record or laser session.

## Needs from others
- **Core (lead): composite `ON DELETE SET NULL` bug.** `tenant_fk(..., ondelete="SET NULL")` on `files.visit_id` and `prescriptions.visit_id` sets *both* FK columns to NULL, including `health_center_id`. Deleting a visit that still has files or prescriptions therefore fails with a NOT NULL violation. I hit this while purging. My module works around it by deleting its own file rows before deleting the visit. The fix is PG15+ column-list syntax, `ON DELETE SET NULL (visit_id)`. It would need raw SQL via `register_sql`, because SQLAlchemy rejects that phrase.
- **Appointments:** the "next appointment" is only stored, in `next_session_at` and the reserved `next_appointment_id`. When the appointments service has a stable create API, the laser create could optionally book it.
- **Files module:** downloads go through `/api/v1/files/<id>/content`. Visibility follows `services.files.visible_clause`, which means the owning clinic.

## Core changes made
None.
