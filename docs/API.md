# API (v1)

Base: `/api/v1`. JSON only. Same-origin (no CORS). Cookie session.

## Conventions
- Mutations (POST/PUT/PATCH/DELETE) require header `X-CSRF-Token` (from `/auth/me` or login response) and same-origin `Origin`.
- Optional `X-Op-Id: <uuid>` on mutations ⇒ idempotent (offline queue). Duplicate ⇒ stored response replayed with `X-Op-Replayed: 1`; concurrent duplicate ⇒ 409 `op_in_progress`.
- Lists: `?page=1&per_page=25` (max 100) ⇒ `{"items": [...], "page", "per_page", "total"}`.
- Updates of versioned records must include `"version"`; mismatch ⇒ 409 `version_conflict` with `details.current_version`.
- Delete ⇒ `202 {"undo_token", "undo_expires_at", "undo_seconds": 30}`; `POST /undo {"undo_token"}` restores within the window.
- Datetimes: ISO-8601 UTC out; naive datetimes in are Asia/Damascus local. Dates `YYYY-MM-DD`. Money as strings with 2 decimals.
- IDs in URLs are never trusted for authorization: services re-check tenant + scope; out-of-scope ⇒ 404.

## Errors
```json
{"error": {"code": "validation_error", "message": "Invalid input", "details": {"field": "is required"}}}
```
| Status | Codes |
|---|---|
| 401 | unauthorized, invalid_credentials, session_replaced, center_inactive, account_inactive |
| 403 | forbidden, csrf_token, csrf_origin, center_inactive (login) |
| 404 | not_found (also out-of-scope) |
| 409 | conflict, version_conflict, appointment_conflict, integrity_error, op_in_progress, email_taken, username_taken |
| 422 | validation_error, plan_limit_reached, quota_exceeded, file_* , undo_expired |
| 429 | rate_limited |

## Endpoint groups
| Group | Prefix | Owner module |
|---|---|---|
| Auth/session | `/auth` (login, logout, me, change-password, support/enter, support/exit) | core `api/auth.py` |
| Common | `/health`, `/notifications`, `/notifications/read`, `/undo`, `/branding/logo` | core `api/common.py` |

Module endpoints are documented in `docs/modules/<module>.md` (one file per module, owned by that module).
| Module | Prefix(es) | Doc |
|---|---|---|
| admin (superadmin portal) | `/admin/*`, `/platform/branding` | modules/admin.md |
| center (settings, departments, clinics, staff, permissions, audit, backup) | `/center/*` | modules/center.md |
| patients (patients, visits, summary, generic records, prescriptions, files) | `/patients`, `/visits`, `/prescriptions`, `/files`, `/generic` | modules/patients.md |
| appointments | `/appointments` | modules/appointments.md |
| billing (services, invoices, payments, documents/PDF) | `/billing/*`, `/documents/*` | modules/billing.md |
| inventory + pharmacy | `/inventory/*`, `/pharmacy/*` | modules/inventory.md |
| dentistry | `/dentistry/*` | modules/dentistry.md |
| dermatology + laser, ophthalmology | `/dermatology/*`, `/ophthalmology/*` | modules/dermatology.md, modules/ophthalmology.md |
| laboratory, radiology | `/lab/*`, `/radiology/*` | modules/laboratory.md, modules/radiology.md |
| reports/exports | `/reports/*` | modules/reports.md |
