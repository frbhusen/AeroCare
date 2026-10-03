# Task Status

Module-level detail lives in `docs/modules/<m>.md`; this file is the integrated summary (lead updates).

## Completed
- Core: config, app factory, tenancy + RLS, server sessions (single session), CSRF, rate limit, error format, validation, pagination, optimistic locking helper, idempotent X-Op-Id, deletion/undo service, storage + upload validation, files service (quota, access, sharing clause), notifications, audit service, accounts (generated email, plan limits), centers (trial, modules, sequences), CLI, test harness (`tests/test_core_auth.py` 7 passing).

## In Progress (parallel workstreams)
| # | Workstream | Owns | Test DB |
|---|---|---|---|
| 1 | Admin + Center management (superadmin portal API, departments, clinics, staff, permissions, audit view, branding, backups, demo seed) | modules/admin, modules/center, services/backup.py, services/demo.py | test_1 |
| 2 | Patients, visits, generic records, prescriptions API, files API, patient summary | modules/patients, modules/generic, modules/files, modules/prescriptions | test_2 |
| 3 | Appointments (recurring, walk-ins, conflicts, WhatsApp) | modules/appointments | test_3 |
| 4 | Billing + documents/PDF + services/pricing | modules/billing, services/pdf.py, services/documents.py | test_4 |
| 5 | Inventory + Pharmacy | modules/inventory, modules/pharmacy | test_5 |
| 6 | Dentistry (AeroDent port) | modules/dentistry | test_6 |
| 7 | Dermatology + Laser, Ophthalmology | modules/dermatology, modules/ophthalmology | test_7 |
| 8 | Laboratory + Radiology | modules/laboratory, modules/radiology | test_8 |
| 9 | Frontend core (shell, design system, auth, router, i18n, components, offline queue) | web/ core paths | test_9 |

## Blocked
- none

## Needs Verification
- Production deployment on Linux (Nginx/Gunicorn) — config written later, not yet exercised on a Linux host.

## Known Issues
- none recorded
