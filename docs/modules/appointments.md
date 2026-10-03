# Appointments module

Package: `backend/app/modules/appointments/` (`models.py`, `service.py`, `series.py`, `recurrence.py`,
`reminders.py`, `api.py`). Tests: `tests/test_appointments.py`, `tests/test_appointments_series.py`.
Spec: §44-50, §68, §73, §76, §77, §89.

## Purpose
Center-wide appointment scheduling, scoped by clinic: create/edit/cancel/delete, explicit start/end
per appointment, doctor auto-assignment, race-safe double-booking prevention, recurring series,
walk-ins, day/week schedule data and WhatsApp reminder links.

## Data models
- **Appointment** (`appointments`): tenant, `department_id`, `clinic_id`, `doctor_id` (nullable, users),
  `patient_id`, `starts_at` < `ends_at` (timestamptz, CHECK), `location` (defaults to clinic.location),
  `appointment_type` (free text ≤ 40; suggested codes in meta), `reason`, `notes`,
  `status` ∈ `scheduled, arrived, in_progress, cancelled, no_show, completed`, `status_changed_at`,
  `is_walk_in`, `series_id` + `series_index`, author snapshot (`AuthorSnapshotMixin` = created by),
  `version`, `pending_delete_until` (undo).
- **AppointmentSeries** (`appointment_series`): tenant, clinic/department/doctor/patient, rule
  (`freq` daily|weekly|monthly, `repeat_interval` 1-52, `weekdays` ISO 1=Mon..7=Sun for weekly,
  `count` and/or `until` local date), `starts_on`, template (`start_time` local wall clock,
  `duration_minutes`, location, type, reason, notes).
- **Exclusion constraints** (registered via `register_sql`, idempotent, `DEFERRABLE INITIALLY IMMEDIATE`):
  `ex_appointments_doctor` / `ex_appointments_clinic` — `EXCLUDE USING gist (<col> WITH =,
  tstzrange(starts_at, ends_at) WITH &&) WHERE (status NOT IN ('cancelled','no_show') AND
  pending_delete_until IS NULL AND <col> IS NOT NULL)`. Ranges are `[)`, so back-to-back slots are OK.
  The core error handler maps these to 409 `appointment_conflict`. The service pre-checks for a
  friendly message (`details.conflicts`, never patient data); the DB is the authority under races.

## Endpoints (`/api/v1/appointments`)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `` | appointments.view | `from`,`to` (local dates, default today, max 92 days), `clinic_id`, `department_id`, `doctor_id`, `patient_id`, `series_id`, `status` (comma list), `page`,`per_page` (≤100). With `patient_id` and no `from`: whole history. Scoped by clinic. |
| GET | `/meta` | appointments.view | statuses, transitions, suggested types, clinics in scope (+ dept name, default duration), `is_doctor`, `own_clinic_id`, `can{view,create,edit,delete}`, `max_occurrences`, `week_starts_on`. |
| GET | `/doctors?clinic_id=` | appointments.view | Active doctors + department managers whose `clinic_id` is that clinic. 404 if clinic out of scope. |
| GET | `/schedule?date=&view=day\|week` | appointments.view | `{view,start_date,end_date,days:[{date,items}]}`; week = Saturday..Friday; filters clinic/department/doctor/status. |
| GET | `/<id>` | appointments.view | 404 out of scope. |
| POST | `` | appointments.create | `{patient_id, starts_at, ends_at \| duration_minutes, clinic_id, doctor_id?, location?, appointment_type?, reason?, notes?}`. Doctor creator: clinic + doctor forced to self. Others: clinic required, doctor optional but must work in that clinic. Patient must exist in center; gets linked to the clinic (`link_patient_to_clinic`). Missing end → clinic default duration. 201. |
| POST | `/walk-in` | appointments.create | `{patient_id, clinic_id, doctor_id?, duration_minutes?, reason?, notes?}` → starts now, status `arrived`, `is_walk_in`; duration = clinic/department setting `appointment_duration_minutes` or 15. |
| POST | `/recurring` | appointments.create | Same body + `rule {freq, interval?, weekdays?, count?, until?}`. Max 200 occurrences (422 `too_many_occurrences`). Any conflict → 409 `appointment_conflict` with `details.conflicting_dates` and nothing created. Returns `{series, items}`. |
| GET | `/series/<id>` | appointments.view | Series template + its live in-scope occurrences. |
| PUT | `/<id>` | appointments.edit | Partial; `version` required (409 `version_conflict`). Fields as create (+ `patient_id`, `clinic_id` (not for doctors), `doctor_id`). `mode`: `this` (default) or `this_and_future` (series only: applies to this + later live **scheduled** in-scope occurrences, shifts by the same number of days with the new local time/duration, updates the series template; all-or-nothing on conflicts). Changing clinic moves location if it was the old clinic default. |
| POST | `/<id>/status` | appointments.edit | `{status, version}`; transitions in `service.TRANSITIONS` (422 `invalid_transition`). Re-activating a cancelled/no-show one re-checks conflicts. Notifies `appointment_cancelled` / `patient_arrived`. |
| DELETE | `/<id>` | appointments.delete | 202 + undo token (type `appointment`); undo via `POST /api/v1/undo` (409 if the slot was re-booked meanwhile). |
| GET | `/<id>/whatsapp?lang=ar\|en` | appointments.view | `{url: "https://wa.me/<digits>?text=<urlencoded>", message, phone, lang}`; center name, local `MM/DD/YYYY` + `HH:MM` (Asia/Damascus), clinic name/location. Syrian `09xxxxxxxx` → `9639xxxxxxxx`. 422 `no_phone`. |

Notifications (`services.notifications.notify`, actor excluded, doctor included): `appointment_created`
(single + one per recurring series), `appointment_cancelled`, `patient_arrived` (status arrived / walk-in).
Link format: `/appointments/<id>`.

## Status
Backend complete; tests: 29 appointment tests (incl. 9-role scope matrix) pass, plus core auth and
route-security tests, on `healthcenter_test_3`.

## Known issues / decisions
- Walk-ins obey double-booking rules: if the doctor/clinic is booked right now the walk-in gets 409
  (choose another doctor/time; the clinic constraint applies even without a doctor).
- Status changes only via `/status`; `PUT` never changes status.
- No series-wide delete/cancel yet (delete/cancel occurrences individually).
- `appointment_type` is free text; meta lists suggested codes.
- Doctor/author FKs use `NO ACTION`: users are archived, never hard-deleted.

## Needs from others
- Settings module: clinic/department setting key `appointment_duration_minutes` (int) is read for
  default duration (clinic overrides department).
- Patients module: patient purge cascades appointments + series (FK `ON DELETE CASCADE`).
- Frontend: notification link `/appointments/<id>`.

## Core changes made
None.
