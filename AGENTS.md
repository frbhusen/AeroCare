# AGENTS.md — Health Center Platform Developer Guide

## 1. Project Overview & Multi-Tenant Architecture
This project evolves AeroDent-Online into a full multi-tenant Health Center Management Platform.
- **Hierarchy**:
  ```text
  Platform (Superadmin Portal)
  └── Health Center (Tenant)
      ├── Departments / Specialties (Dentistry, Dermatology, Laser, Ophthalmology, Radiology, Lab, Pharmacy, Generic...)
      │   ├── Clinics (Operational units with physical rooms/locations)
      │   │   └── Doctors (Assigned to one clinic)
      │   └── Department / Center Staff (Receptionists, Managers, Technicians)
  ```
- **Strict Isolation**: App filters + Composite FKs `(health_center_id, ...)` + PostgreSQL RLS (FORCE) using runtime role `hc_app`. Context set via transaction-local `app.mode` / `app.center_id`.
- **Global Patient Identity**: One patient record per health center, linked to clinics via `patient_clinic_links`. Medical records are isolated by department/clinic scopes.
- **Server Sessions**: Stored in `sessions` table with hashed token; single active session enforced per user (revoking existing sessions on login).

## 2. Technology Stack & Directory Structure
- **Backend**: Python 3.12+, Flask application factory, SQLAlchemy 2.0, PostgreSQL 18.
  - Entry point: `backend/wsgi.py`
  - Core: `backend/app/core/`, `auth/`, `authz/`, `models/`, `services/`, `schema/`
  - Modules: `backend/app/modules/<module>/` with `api.py` (Blueprint auto-registered at `/api/v1/<module>`), `models.py`, `service.py`
- **Frontend**: Vanilla ES modules (HTML5 + CSS + JavaScript, no bundler/framework), Arabic/English with full RTL/LTR support, responsive, offline queue with IndexedDB and `X-Op-Id`.
  - Core shell: `web/index.html`, `web/css/`, `web/js/core/`, `web/js/components/`, `web/js/offline/`
  - Modules: `web/js/<module>/` exporting `register(registry)` in `index.js`.
- **Database & Schemas**: No Alembic. Schema managed via `flask db init-schema` (idempotent `create_all` + custom idempotent SQL in `backend/app/schema/`).

## 3. Development & Testing Commands
- **Detailed Local Setup Guide**: [`docs/LOCAL_DEPLOYMENT.md`](file:///c:/Users/Husen/Documents/Programming/Health%20Center/docs/LOCAL_DEPLOYMENT.md)
- **Python venv**: `.venv\Scripts\python.exe`
- **Postgres**: Running locally on port `55432` (`hc_owner` superuser, `hc_schema` owner, `hc_app` app role).
- **Run tests**:
  ```bash
  .venv\Scripts\python -m pytest tests/test_<module>.py
  ```
  For parallel agents, specify an isolated test database (`healthcenter_test_1` through `healthcenter_test_12`):
  ```bash
  TEST_DATABASE_URL=postgresql+psycopg://hc_app@127.0.0.1:55432/healthcenter_test_N TEST_SCHEMA_DATABASE_URL=postgresql+psycopg://hc_schema@127.0.0.1:55432/healthcenter_test_N .venv/Scripts/python -m pytest tests/test_<file>.py
  ```
- **Syntax check JS**:
  ```bash
  node --check web/js/<module>/<file>.js
  ```

## 4. Security & Business Logic Rules
- **Layered Authorization**: Every backend route must enforce:
  `Authentication` → `Health Center` → `Department Scope` → `Clinic Scope` → `Permission`.
- **Single Object Access**: Always use scoped queries with `p.tenant(Model)` and scope clauses, never bare `db.session.get`. Return 404 for out-of-scope objects.
- **Auditing**: Log administrative changes (users, clinics, roles, centers) via `services.audit.log_change`. Never log medical or financial records.
- **Deletions**: Use the 30-second staged undo deletion service (`services.deletion.stage(p, obj, type, label)`).
- **Medical Records**: Include `AuthorSnapshotMixin` and set author once.

## 5. UI Integration Contract
- Each module in `web/js/modules.js` defines an `index.js` exporting `register(registry)`.
- Use `registry.route`, `registry.menu`, `registry.widget`, and `registry.i18n` with en/ar translations.
- All styles must use CSS variables and logical properties (`margin-inline-start`, etc.) to support RTL cleanly.
