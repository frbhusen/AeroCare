# Ophthalmology

Spec §23-25, §38, §73, §82-83. Dedicated environment `ophthalmology`: one structured eye examination per visit. Clinics must be in the ophthalmology environment; otherwise the API returns 422 `wrong_environment`. Out of scope → 404; missing permission → 403.

Code: `backend/app/modules/ophthalmology/`
- `models.py`
- `schemas.py`: nested validation
- `service.py`
- `api.py`

It reuses `modules/dermatology/visitkit.py` for the visit-owned record lifecycle.

## Data model
`ophthalmology_exams` is one-to-one with `visits` (`UNIQUE visit_id`) and has composite tenant FKs to patient, department, clinic and visit (all CASCADE). Mixins: Version, UndoDelete, AuthorSnapshot.

Columns:
- `chief_complaint`, `history`, `diagnosis`, `treatment`, `follow_up`, `notes`
- `right_eye` (OD) and `left_eye` (OS), JSONB
- `glasses`, JSONB
- `extra`, JSONB
- `owns_visit`

The per-eye blocks are validated strictly on the server. Unknown keys are dropped, and errors use dotted paths such as `right_eye.iop.value`.

| Block | Fields (ranges) |
|---|---|
| visual_acuity | `uncorrected`, `best_corrected`, `pinhole`: Snellen (`6/9`, `20/40`, `6/12+2`), decimal 0-2.0, or CF/HM/LP/NLP with an optional qualifier. `near`: text |
| refraction | `sphere` ±30 (0.01), `cylinder` ±15, `axis` 0-180 (required when cylinder ≠ 0), `add` 0-5 |
| iop | `value` 0-80 mmHg (0.1); `method` goldmann/non_contact/tonopen/icare/perkins/palpation/other |
| pupils | `size_mm` 0-12, `shape`, `reaction` brisk/sluggish/non_reactive, `rapd` absent/present |
| motility | `status` full/restricted, `notes` |
| slit_lamp | `lids`, `conjunctiva`, `cornea`, `anterior_chamber`, `iris`, `lens` |
| fundus | `dilated`, `optic_disc`, `cup_disc_ratio` 0-1, `macula`, `vessels`, `periphery` |
| (eye) | `notes` |
| glasses | `right` and `left` (refraction schema), `pd_mm` 40-80, `lens_type` single_vision/bifocal/progressive/reading/contact_lens/other, `notes` |

## Endpoints (`/api/v1/ophthalmology`; all `@login_required`)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/meta` | login | Field catalog with types, min/max/step and choices, so the UI can build forms; also lists the eyes (OD/OS) |
| GET | `/patients/<pid>/exams?clinic_id=&page=` | medical_records.view | Only exams in the caller's clinics |
| POST | `/exams` | medical_records.create | Pass either `{patient_id, clinic_id, visit_at?, visit_type? (default examination), title?}` or `{visit_id}` to attach to an existing ophthalmology visit, plus the exam fields |
| GET | `/exams/<id>` | medical_records.view | |
| PATCH | `/exams/<id>` | medical_records.edit | Requires `version` (409 on conflict). An eye or glasses block, when provided, replaces the whole block |
| DELETE | `/exams/<id>` | medical_records.delete | Returns 202 with an undo token. Stages the owned visit (`oph_exam_visit`) or only the exam (`oph_exam`). The purge cascades |

## Summary provider
Registered as `ophthalmology` (order 230). It returns the exam count and recent exams with VA and IOP per eye, scoped to the caller's clinics. It can also be called as `service.patient_summary(p, patient_id)`.

## Status
The backend is implemented. Tests are in `tests/test_ophthalmology.py` (18, including 12 parametrized validation cases). The UI comes in a later round.

## Needs from others
See the dermatology doc for the composite `ON DELETE SET NULL` issue on `files.visit_id` and `prescriptions.visit_id`. It affects visit deletion center-wide. Prescriptions for glasses or medication are not created here: the exam stores the spectacle Rx itself, and medication prescriptions should use the shared prescriptions module with `visit_id`.

## Core changes made
None.
