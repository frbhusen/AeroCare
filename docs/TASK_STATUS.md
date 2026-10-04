# Task Status

Module-level detail lives in `docs/modules/<m>.md`; this file is the integrated summary (lead updates).

## Completed
- **Core Platform**: config, app factory, tenancy + PostgreSQL RLS (`hc_app`), server sessions (single-session per user enforcement), CSRF, rate limiting, error format, validation, pagination, optimistic locking helper (`version`), idempotent `X-Op-Id`, 30s deletion/undo service, secure storage + upload validation, quota tracking, sharing clauses, notifications, immutable audit log, center lifecycle (trial, modules, sequence numbering), CLI commands.
- **Admin & Center Management**: Superadmin portal API and frontend UI (centers, modules catalog, subscription tiers/plans, platform users, storage quotas, audit logs, system branding, backups). Center administration (departments, clinics, working hours, staff, role permissions overrides).
- **Patients & Clinical Core**: Central patient registry with search, duplicate prevention & linking, visit management, generic clinical records (vitals, SOAP notes), shared prescriptions API & PDF printing, files & documents storage with interactive canvas annotations (pen, arrow, text) and quotas, comprehensive patient summary across departments.
- **Appointments**: Calendar scheduling, slots, recurring appointments, walk-ins, conflict detection, WhatsApp notification links.
- **Billing & Accounting**: Invoices, cash payments, partial payments, discounts, PDF invoice & receipt printing, service & pricing catalog, integration with clinical source records (dental treatments, pharmacy sales), financial summary provider.
- **Inventory & Pharmacy**: Stock lots, movements, transfers, expiry tracking, department-scoped low stock reports, prescription dispensing queue, pharmacy point of sale (OTC & patient sales) creating linked billing invoices.
- **Dentistry (AeroDent Port)**: Adult & pediatric odontograms, tooth conditions, clinical treatments, treatment plans with convert-to-treatment workflow, dental X-rays with SHA-256 verification and staged deletion, appointments integrated in dental timeline.
- **Dermatology & Laser Hair Removal**: Interactive 2D SVG body map with 3D toggle, lesion severity & clinical photography, laser hair removal sessions with region tracking and numbering.
- **Ophthalmology**: Structured eye examinations (OD / OS visual acuity, refraction, IOP, pupils, slit lamp, fundus, motility), glasses prescriptions with bilingual PDF generation.
- **Laboratory & Radiology**: Laboratory test catalog, order workflow, specimen collection, result entry with abnormal flags, PDF report generation. Radiology studies, scheduling, imaging viewer, findings & impressions, report generation, explicit clinic/user sharing.
- **Frontend Architecture & Modules**: Native ES modules (no bundler), responsive design system (no theme switch, per spec), RTL/LTR Arabic/English internationalization, offline queue with IndexedDB and background replay. All 15 modules (`patients`, `appointments`, `billing`, `inventory`, `files`, `reports`, `admin`, `center-admin`, `dentistry`, `dermatology`, `ophthalmology`, `radiology`, `laboratory`, `pharmacy`, `generic`) fully wired with `index.js`, routes, menus, and widgets.

## Verified in browser (2026-10-04, demo center)
- Doctor: General Medicine visit create/edit/complete; ophthalmology exam create (inline range errors), view, glasses PDF; patient register; files upload/share.
- Pharmacy: queue → partial dispense from stock; POS sale via simulated USB scan; catalog; expiry.
- Center manager: department cards, all center pages, settings save, backup export, audit log.
- Superadmin: all 7 portal pages load.
- Arabic RTL at phone width (patients, dental chart).

## Needs Verification
- Production deployment on Linux (Nginx/Gunicorn) — deployment configs present in `deploy/`, verification on Linux host pending.

## Known Issues / Notes
- Arabic PDF layout not yet checked visually.

- Arabic PDF rendering in production requires `fonts-dejavu-core` or suitable fonts installed on Linux.
- Service worker registration in embedded verification webview requires standard Chrome/Edge browser context.
