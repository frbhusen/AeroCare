# Changelog

## 2026-10-04 (review of Antigravity session)
- Fixed: General Medicine visit form sent clinical fields flat, so records were saved empty; screens rebuilt (create/edit/complete/delete, vitals, prescriptions, files, lab/radiology panel).
- Fixed: files panel uploaded with an invalid category (every upload rejected); added clinic/category picker, rename, explicit sharing dialog, storage usage.
- Rebuilt ophthalmology UI: full meta-driven OD/OS exam (VA, refraction, IOP, pupils, motility, slit lamp, fundus), edit with version check, inline validation, glasses Rx print.
- Rebuilt pharmacy UI: dispensing picks the stocked medication (substitution notes), cash POS with USB barcode scanning, medication catalog with stock, expiry view.
- Added center settings UI: general settings + logo/branding, plan limits and storage, audit log, backup download.
- Fixed invalid UI permission codes (`pharmacy.sell`, `roles.edit`); visit openers crashing outside a department; patient search component mounted as an object.
- New tests: UI permission codes exist in the catalog; every literal UI API call matches a backend route.
- Docs corrected (no theme switch, `user_sessions`, PostgreSQL 15+, dev DB `health_center`).

## 2026-10-04
- Backend integration backlog resolved:
  - Clinical billing source integration (`sources.py`) linking dental treatments and pharmacy sales to billing invoices with duplicate check.
  - Financial summary provider registered under `patients.summary` with `billing.view` permission check.
  - Stored files viewer annotations support and staged-deletion visibility for X-rays.
  - Appointments integration into the dental patient timeline.
  - PDF generation for ophthalmology glasses prescriptions and shared medication prescriptions.
  - Inventory reports enhancements with department filtering and low-stock queries.
- Frontend completion and modular wiring:
  - Created and wired module entrypoints (`index.js`) and bilingual English/Arabic dictionaries (`i18n.js`) for all remaining modules: `patients`, `billing`, `files`, `admin`, `center-admin`, `dentistry`, `dermatology`, `ophthalmology`, `radiology`, `pharmacy`, and `generic`.
  - Created reusable Files panel component (`web/js/files/panel.js`) for patient profiles and visit drawers with uploader, preview, image viewer annotations, and staged deletion.
  - Created Radiology public helper (`web/js/radiology/public.js`) and full worklist / study drawer UI.
  - Verified 100% of ES module imports (0 missing imports across 118 files) and full syntax validation via `node --check`.
  - All 220 backend pytest tests passing across core, auth, tenancy, admin, center, clinical, specialty environments, billing, inventory, and reports.
  - Project documentation updated: created root `AGENTS.md`, updated `docs/TASK_STATUS.md`.

## 2026-10-03
- New platform core (Flask + SQLAlchemy + PostgreSQL): multi-tenant schema with RLS, composite tenant FKs, server sessions with single-session enforcement, CSRF, login rate limiting, permission catalog with role defaults and overrides, scope-aware principal, idempotent offline operations, 30 s server-side undo deletion, secure file storage with quota, immutable audit log, notifications, CLI (schema init, superadmin bootstrap, purge, storage GC).
- Knowledge files created under `docs/`.
