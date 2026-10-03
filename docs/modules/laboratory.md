# Laboratory module (`backend/app/modules/laboratory/`, prefix `/api/v1/lab`)

Spec: §40, §71, §76, §82–83, §104. Decision: finalized lab results are readable center-wide (DECISIONS 2026-10-03).

## Purpose
Test catalog (categories, tests, units, reference ranges incl. per-gender, price), lab requests from any
clinic to a laboratory department, result entry with abnormal flags, finalization, lab report (JSON + PDF).

## Files
`models.py` · `catalog.py` (catalog service) · `service.py` (request workflow + visibility) · `flags.py`
(pure flag computation) · `report.py` (report JSON/PDF, stored PDF) · `notify.py` (lab + radiology
notifications) · `routing.py` (target dept resolution, shared with radiology) · `summary.py` (patient summary
provider `laboratory`, order 600) · `api.py`.

## Data models
- `lab_test_categories`: name (unique among live), sort_order, is_active, version, undo-delete.
- `lab_tests`: code (unique among live), name, category_id, unit, result_type numeric|text|choice, choices,
  normal_choices, ref_low/high, ref_low/high_male, ref_low/high_female, ref_text, price, is_active, version, undo-delete.
- `lab_requests`: patient, requesting dept/clinic, author snapshot (requester), lab_department_id, lab_clinic_id
  (nullable until a lab clinic takes it), visit_id, priority routine|urgent, status
  requested → in_progress → completed | cancelled, clinical_notes, result_notes, patient_gender snapshot,
  started/performed_by, finalized_at/by(+role) snapshot, cancelled_*, report_file_id, version, undo-delete.
- `lab_request_items`: snapshot of the test (code, name, category, unit, type, choices, the patient's
  effective range, ref_text, price) + result_value, numeric_value, abnormal_flag L/H/N/A, comment.

Flags: numeric → L/H/N against the snapshotted range (None without range); choice → A if not in
`normal_choices` (or explicit `abnormal`); text → only explicit `abnormal` true/false → A/N.

## Access
- Catalog management: `lab.manage_tests` AND (center-wide OR manages a laboratory-env department). Superadmin
  never (support mode lacks the permission; also rejected explicitly). Read: any of lab.request/process/manage_tests.
- Per request (`service.access_level`): `lab` = `lab.process` + target lab dept/clinic in scope (full workflow);
  `requester` = requesting clinic in scope (results only after completion); `result` = completed +
  `medical_records.view` + patient visible (read-only, no workflow). Otherwise 404. Visible-but-not-lab
  workflow attempts → 403.
- Creating a request requires `lab.request`, requesting clinic in scope and patient visible; it links the patient
  to the lab clinic(s) so lab staff see the basic profile. Lab staff never gain other clinics' records.

## Endpoints
| Method | Path | Permission / notes |
|---|---|---|
| GET | `/lab/meta` | any lab perm; result types, priorities, laboratories (+clinics), requesting clinics, `can` flags, categories |
| GET/POST | `/lab/categories` | read / manage |
| PATCH/DELETE | `/lab/categories/<id>` | manage; PATCH needs `version`; DELETE → 202 undo |
| GET/POST | `/lab/tests` (`?category_id&active&q`) | read / manage |
| GET/PATCH/DELETE | `/lab/tests/<id>` | read / manage (version) / manage (202 undo) |
| POST | `/lab/requests` | `lab.request`; body `patient_id, test_ids[], requesting_clinic_id?, lab_department_id?, lab_clinic_id?, visit_id?, priority, clinical_notes` |
| GET | `/lab/requests` | requesting side list (`status` incl. `active`, `priority`, `patient_id`, `clinic_id`, `date_from/to`, paging) |
| GET | `/lab/queue` | lab worklist (`lab.process`; default active, urgent first) |
| GET | `/lab/patients/<pid>/requests` | union of requester/lab/finalized-result scopes; patient must be visible |
| GET | `/lab/requests/<id>` | any access level; payload has `access` and `can` flags |
| PATCH | `/lab/requests/<id>` | requester, status requested, `version` (priority, clinical_notes) |
| POST | `/lab/requests/<id>/start` | lab side, `version`, optional `lab_clinic_id` |
| PUT | `/lab/requests/<id>/results` | lab side, `version`, `items:[{id,result_value,comment,abnormal}]`, `result_notes`; auto-starts |
| POST | `/lab/requests/<id>/finalize` | lab side, all results required (422 `missing_results`) |
| POST | `/lab/requests/<id>/cancel` | lab (requested/in_progress) or requester (requested); `reason` |
| DELETE | `/lab/requests/<id>` | requester side, status requested only → 202 undo |
| GET | `/lab/requests/<id>/report` | completed only; `?format=json|pdf&lang=en|ar` |

## Notifications
`lab_request` → staff of the target lab clinic(s)/department; `lab_result_available` → requesting clinic staff + requester.

## Report / PDF
`services.documents.render(..., kind="lab_report")`. On finalize (separate transaction, best-effort) a PDF is
stored as a center-wide `lab_report` file (owner_type `lab_request`, clinic = lab clinic) → `report_file_id`.

## Status
Backend complete. Tests: `tests/test_laboratory_catalog.py`, `tests/test_laboratory_workflow.py`
(helpers in `tests/test_laboratory_helpers.py`, shared with radiology tests).

## Known issues
- Catalog is center-level (shared by all laboratory departments of a center).
- Stored PDF is English; the on-demand endpoint supports `lang=ar`.
- Item prices are snapshotted but not billed automatically.

## Needs from others
- Billing: optionally create invoice lines from `lab_request_items.price` (read via request id).
- Frontend: routes `#/laboratory/requests/<id>` used in notification links.

## Core changes made
None.
