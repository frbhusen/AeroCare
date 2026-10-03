# Dentistry module (port of AeroDent)

Owner: dentistry agent. Code: `backend/app/modules/dentistry/` (`models.py`, `constants.py`, `service.py` = scope helpers, odontogram, doctors, summary and meta; `records.py` = treatments and plans; `xrays.py`; `timeline.py`; `api.py`). Tests: `tests/test_dentistry.py`, `tests/test_dentistry_xrays.py`.
Spec: §23, 24, 25, 33, 72, 73, 82, 83, 101.

## Purpose
This module brings AeroDent's dental workflows into the platform: the permanent and primary odontogram, treatments, treatment plans, X-rays and the patient timeline. Everything is re-keyed to the platform's ownership model: health center, department, clinic, patient and an optional visit. Only clinics whose department environment is `dentistry` are accepted.

## Scope and permission rules
- **Accessible dental clinics** are `p.clinic_department` entries whose department environment is `dentistry`:
  - a doctor gets their own clinic
  - a department manager or department receptionist gets the dentistry department's clinics
  - center-wide principals get all of them
- **Lists** are always limited to these clinics. Single objects are loaded with a scoped query. Out of scope returns 404.
- **`clinic_id`** may be omitted when the principal has exactly one dental clinic. Otherwise the API returns 422 `{"clinic_id": "is required"}`.
  - An accessible clinic that is not dental returns 422 `wrong_environment`.
  - An inaccessible clinic returns 404.
- **Permissions:**

  | Action | Permission |
  |---|---|
  | Read | `medical_records.view` |
  | Create treatment, plan, convert, X-ray | `medical_records.create` (an X-ray upload also needs `files.upload`) |
  | Odontogram changes, treatment/plan/X-ray edits | `medical_records.edit` |
  | Deletes | `medical_records.delete` |

  - Receptionists can therefore read in scope, and write only after a `user_permissions` grant (tested).
  - Superadmin support mode is read-only.
- **Patient visibility:**
  - Reads need the patient to be visible (`clinical.get_patient`).
  - Writes need a live patient of the center. The write then links the patient to the clinic (`clinical.link_patient_to_clinic`), which is the same rule `clinical.create_visit` uses.
- **Visits:**
  - `visit_id` must be a visit of the same patient in the same clinic. Otherwise the API returns 422, or 404 if the visit is not visible.
  - `create_visit: true` on a treatment create, update or plan convert calls `clinical.create_visit(visit_type="treatment", environments="dentistry")`.

## Data models
| Table | Notes |
|---|---|
| `dental_odontogram_teeth` | Current state per (center, clinic, patient, `tooth_mode`, `tooth_number`), stored once as a unique row. Fields: `condition` (NULL means cleared), `procedure`, `notes`, `surfaces` (JSON list of M/O/D/B/L). Also has `VersionMixin`, an author snapshot (who first charted the tooth) and `updated_by_*` (last change). |
| `dental_odontogram_entries` | Append-only history, one row per change (`action` set/clear, full state after the change, `tooth_version`, `visit_id`, author snapshot). Past states are never lost. |
| `dental_treatments` | Fields: `tooth_mode` and `tooth_number`, `procedure`, `description`, `status` (planned/accepted/scheduled/in-progress/completed/cancelled), `fee`, `date`, a doctor snapshot (`doctor_user_id` + `doctor_name`), `visit_id`, `plan_id`. Has Version, UndoDelete and AuthorSnapshot. |
| `dental_treatment_plans` | Plan items with AeroDent's fields: tooth, `diagnosis`, `procedure`, `fee`, `priority` (low/medium/high), `status`, `notes`, doctor snapshot. Also `converted_treatment_id` and `converted_at`. Has Version and UndoDelete. |
| `dental_xrays` | Fields: `file_id` (unique FK to `files`, ON DELETE CASCADE), `filename`, `type` (periapical/bitewing/panoramic/cephalometric/occlusal/cbct/other), `tooth_tag`, `date`, `time`, `notes`, `visit_id`. Has Version, UndoDelete and AuthorSnapshot. |

All references use composite tenant FKs. Visit FKs use `ON DELETE SET NULL (visit_id)` (a PG15+ column list), so purging a visit never tries to null `health_center_id`.

Module SQL `dentistry_xray_file_cleanup` adds an AFTER DELETE trigger on `dental_xrays` that deletes the X-ray's `files` row. When the purger hard-deletes an X-ray, the file row goes with it, and the registered `files` clause makes the purger delete the bytes.

Deletion types:
- `dental_treatment`
- `dental_treatment_plan` (purging a plan nulls `dental_treatments.plan_id`)
- `dental_xray` (files: `StoredFile.id == file_id`)

## Endpoints (prefix `/api/v1/dentistry`, all `@login_required`)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/meta` | (any staff) | Numbering (Universal: upper/lower order, labels, FDI map), conditions, chart_actions, surfaces, procedures, statuses, priorities, xray_types, accessible dental clinics, and the caller's medical permission flags |
| GET | `/doctors?clinic_id=` | view | Doctors of the clinic plus the department head (for the treatment doctor picker) |
| GET | `/patients/<pid>/odontogram?clinic_id=&mode=` | view | `{patient_id, clinic_id, teeth[], can_edit}` |
| PUT | `/patients/<pid>/odontogram/<mode>/<tooth>` | edit | Body: `clinic_id?`, `visit_id?`, `condition` / `procedure` / `notes` / `surfaces` (partial), `version` (required once the row exists). Returns 201 when the row is created, 200 otherwise. `condition:"clear"` resets the tooth and records a history entry. |
| POST | `/patients/<pid>/odontogram/bulk` | edit | `{clinic_id?, visit_id?, teeth:[{tooth_mode, tooth_number, ..., version}]}`. Atomic (all or nothing), at most 52 teeth, no duplicate teeth |
| GET | `/patients/<pid>/odontogram/history?clinic_id=&mode=&tooth_number=` | view | Newest first, up to 200 rows |
| GET | `/patients/<pid>/timeline?clinic_id=` | view | Visits, treatments, plan items, X-rays (with `image_url`) and shared prescriptions in dental clinics, newest first |
| GET | `/patients/<pid>/summary` | view | Same data as the patient-summary section |
| GET/POST | `/treatments` | view / create | List filters: `clinic_id`, `patient_id`, `status`, `doctor_user_id`, `date_from`, `date_to`; paginated. Create: `patient_id`, `clinic_id?`, tooth, `procedure` or `description`, `status`, `fee`, `date`, `doctor_user_id`, `visit_id` or `create_visit` |
| GET/PATCH/DELETE | `/treatments/<id>` | view / edit / delete | PATCH needs `version`. DELETE returns 202 with an undo token |
| GET/POST | `/treatment-plans` | view / create | Filters as for treatments, plus `priority` |
| GET/PATCH/DELETE | `/treatment-plans/<id>` | view / edit / delete | |
| POST | `/treatment-plans/<id>/convert` | create | `{version, date?, status?, description?, visit_id? or create_visit?}` returns `{treatment, plan}`. A planned item becomes `accepted`. Converting twice returns 409 `already_converted`; a cancelled item returns 422. |
| GET/POST | `/patients/<pid>/xrays` | view / create + files.upload | Upload: multipart with `file` plus `clinic_id`, `type`, `tooth_tag`, `date`, `time` (HH:MM), `notes`, `filename`, `visit_id`. List filters: `clinic_id`, `type`, `tooth_tag`, `date` |
| GET/PATCH/DELETE | `/xrays/<id>` | view / edit / delete | PATCH edits metadata with `version`; renaming also renames the file's display name |
| GET | `/xrays/<id>/verify` | view | SHA-256 integrity check of the stored bytes |

X-ray bytes are downloaded from the shared `/api/v1/files/<file_id>/content`. Each X-ray's payload includes `file.url`.

Upload rules:
- `services.files.store_upload` is called with category `xray`, owner_type `dental_xray`, and the X-ray's `owner_id`, clinic, department and patient. The resulting file is visible only through clinic or department scope (tested).
- Accepted types are JPEG, PNG, WebP, GIF, BMP, TIFF and DICOM. Anything else returns 422 `xray_type_not_allowed`.
- Core validation also applies: 15 MB limit, extension allow-list and magic-byte sniffing.

## AeroDent behaviour preserved
- **Tooth numbering:** AeroDent's Universal scheme is kept.
  - Permanent teeth are 1–32 (upper 1→16, lower 32→17).
  - Primary teeth are 1–20, shown as A–T.
  - The meta endpoint exposes the arch order and labels, so the AeroDent odontogram UI can be reused. FDI numbers are added for display.
- **Odontogram:**
  - One state per (patient, mode, tooth) with `condition`, `procedure`, `notes`.
  - A PUT upsert only changes the fields sent (partial).
  - AeroDent's condition keys (healthy, decay, filling, amalgam, crown, rct, extract, implant) and quick-action list (including `clear`) are unchanged, so its CSS classes and i18n keys still apply.
- **Treatments:**
  - Same fields, the same six statuses (including `in-progress` with a hyphen), fee ≥ 0 with 2 decimal places (max 99,999,999.99), date defaults to today, status defaults to planned.
  - The doctor defaults to the creating doctor and must be a doctor of the clinic.
  - The list is ordered by date descending, then id descending.
- **Treatment plans:** same fields, priority defaults to medium, same statuses.
- **X-rays:**
  - Same metadata: filename, type, `tooth_tag`, date, time (HH:MM), notes. Date defaults to today.
  - List filters on `tooth_tag`, `type` and `date` are kept.
  - Original bytes are stored unmodified with a SHA-256 hash (this is AeroDent's "original" lossless encoding).
  - The integrity verify endpoint is kept.
  - Metadata edits are allowed; replacing the file is not.
- **Timeline:** the same event shape (`type`, `id`, `date`, `time`, `title`, `description`, `status`, `image_url`) and the same event types (`treatment-plan` keeps its hyphen).

## AeroDent behaviour intentionally changed or dropped
- **Odontogram DELETE was replaced by `condition:"clear"`.** The row is kept and a history entry is recorded, so a past state is never silently lost (spec §101).
- **Treatment-plan tooth range of 1–85 was dropped.** That range was inconsistent with AeroDent's own UI, which uses 1–32. Plans and treatments now use `tooth_mode` plus the Universal number, the same as the odontogram.
- **Condition is now validated against an enum** instead of accepting any string. The enum is AeroDent's keys plus missing, bridge, veneer, fracture and sealant. Surfaces are a new optional field; AeroDent only had i18n keys for them.
- **X-ray image re-encoding was dropped:** no PNG-lossless recompression, pixel hashes or TIFF preview rendition. Bytes go through the platform file store unmodified. Browsers cannot render TIFF or DICOM inline; a preview is future work.
- **The 25 MB X-ray limit is now the platform's 15 MB limit.**
- **The X-ray upload rate limit (200/h) was dropped.** Rate limiting belongs to the platform.
- **The legacy filesystem `storage_key` was dropped.**
- **Per-action AeroDent activity logging was dropped.** Spec: no audit for medical activity.
- **Timeline appointments are not included yet.** They depend on the appointments module; see Needs.
- **The "block treatment delete if invoiced" rule is not implemented yet.** It depends on billing; see Needs.
- **AeroDent patient fields** (work_study, medical_flags, location) belong to the core patients module and are not handled here.

## Patient summary
`service.dental_summary(p, patient)` is registered with `patients.summary.register_summary_provider("dentistry", order=200)`. It is built only from the principal's dental clinics and returns None when there is no access or no data. Fields: treatments by status, open plan items, X-ray count, charted (non-healthy) teeth, last treatment date.

## Status
Backend complete. 16 module tests pass on `healthcenter_test_6`, together with `test_core_auth.py` and `test_security_routes.py`. The UI comes in a later round (reuse `meta`).

## Known issues
- During the 30-second undo window of an X-ray delete, its `files` row is still live. The files module could show it in a generic file list for those 30 seconds.
- `health_centers.storage_used_bytes` is not decremented on purge; this is core behaviour.

## Needs from others
- **Core:** `prescriptions.fk_rx_visit` and `files.fk_file_visit` use a plain composite `ON DELETE SET NULL`. Deleting a visit therefore tries to null `health_center_id` (NOT NULL) and fails. Suggested fix: `ondelete="SET NULL (visit_id)"`. Until then, dental X-ray files do not set `files.visit_id`; the visit link lives on `dental_xrays.visit_id`.
- **Billing:** to keep AeroDent's rule, refuse deleting a treatment that an invoice references. Billing can either expose a check hook or reference `dental_treatments.id` with an FK.
- **Appointments:** the dental timeline could include appointments if the appointments module exposes a scoped query helper.

## Core changes made
None.
