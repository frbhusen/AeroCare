# Radiology module (`backend/app/modules/radiology/`, prefix `/api/v1/radiology`)

Spec: §39, §71, §76, §82–83, §103. Decision: final reports go to the requesting clinic + explicit shares.

## Purpose
Radiology request + study in one entity: request from any clinic, worklist, scheduling, performing, image
upload, report (findings/impression), finalization with sharing to the requesting clinic, explicit shares.

## Files
`models.py` · `service.py` (scope, serialization, lists, create/edit/delete) · `workflow.py` (transitions,
images, shares) · `report.py` (JSON/PDF) · `summary.py` (patient summary provider `radiology`, order 610) · `api.py`.
Uses `laboratory/routing.py` and `laboratory/notify.py`.

## Data models
- `radiology_studies`: patient, requesting dept/clinic, author snapshot (requester), radiology dept/clinic,
  visit_id, exam_type x_ray|ct|mri|ultrasound|other, body_region, clinical_question, priority, status
  requested → scheduled → in_progress → reported → finalized | cancelled (requested → in_progress allowed),
  requested/scheduled/performed_at, findings, impression, radiologist snapshot, reported_at, finalized_at/by,
  cancelled_*, report_file_id, version, undo-delete.
- `radiology_study_shares`: explicit share of a finalized study to exactly one clinic / department / user.

Images: `services.files.store_upload` (category `radiology_image`, owner_type `radiology_study`, clinic = radiology clinic, patient set).

## Access
`radiology` side = `radiology.process` + target radiology dept/clinic in scope (full workflow). `requester` =
requesting clinic in scope (incl. its managers and center-wide principals); report/images only once finalized.
`shared` = finalized + `medical_records.view` + study share to one of the user's clinics/departments or the user.
Everything else 404. Radiology staff see the patient's basic identity only.
On finalize: `file_shares` to the requesting clinic for every image (+ the generated PDF report file). Adding a
study share also creates file shares for all study files to the same target; revoking removes them (the
automatic requesting-clinic share is never revoked).

## Endpoints
| Method | Path | Permission / notes |
|---|---|---|
| GET | `/radiology/meta` | exam types, priorities, statuses, radiology departments (+clinics), requesting clinics, `can` |
| POST | `/radiology/studies` | `radiology.request`; `patient_id, exam_type, body_region?, clinical_question?, priority?, requesting_clinic_id?, radiology_department_id?, radiology_clinic_id?, visit_id?` |
| GET | `/radiology/studies` | requesting side list (`status` incl. `active`, `priority`, `exam_type`, `patient_id`, `clinic_id`, dates) |
| GET | `/radiology/worklist` | `radiology.process`; default active; urgent first, then scheduled time |
| GET | `/radiology/patients/<pid>/studies` | requester ∪ radiology ∪ shared; patient must be visible |
| GET | `/radiology/studies/<id>` | any access level; `access`, `can`, `images` |
| PATCH | `/radiology/studies/<id>` | requester, status requested, `version` |
| DELETE | `/radiology/studies/<id>` | requester, status requested → 202 undo |
| POST | `/radiology/studies/<id>/schedule` | radiology side, `version`, `scheduled_at`, `radiology_clinic_id?` |
| POST | `/radiology/studies/<id>/start` | radiology side, `version` (clinic must be determinable) |
| POST | `/radiology/studies/<id>/images` | radiology side + `files.upload`, multipart `files`, status in_progress/reported |
| PUT | `/radiology/studies/<id>/report` | radiology side, `version`, `findings`, `impression` → reported |
| POST | `/radiology/studies/<id>/finalize` | radiology side, status reported |
| POST | `/radiology/studies/<id>/cancel` | radiology (≤ in_progress) or requester (requested/scheduled); `reason` |
| GET | `/radiology/studies/<id>/report` | finalized (or reported for radiology side); `?format=json|pdf&lang=` |
| GET/POST | `/radiology/studies/<id>/shares` | finalized; radiology side or requester with `files.share`; body one of `target_clinic_id/target_department_id/target_user_id` |
| DELETE | `/radiology/studies/<id>/shares/<share_id>` | same |

Image rename/annotate/delete goes through the files module (owning clinic = radiology clinic).

## Notifications
`radiology_request` → radiology clinic/department staff; `radiology_result_available` → requesting clinic + requester.

## Status
Backend complete. Tests: `tests/test_radiology.py`.

## Known issues
- Images uploaded are not removable via this module (use files module); no DICOM handling (spec §103).
- Stored PDF is English; on-demand endpoint supports `lang=ar`.

## Needs from others
- Frontend: routes `#/radiology/studies/<id>`; image viewer from files module.

## Core changes made
None.
