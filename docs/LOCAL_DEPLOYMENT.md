# Local Deployment & Development Guide

This guide covers running the Health Center Management Platform locally for development, testing, and offline evaluation.

---

## 1. Architecture Overview

In a local development environment:
- **Backend**: Flask application running on Python 3.12+ (serves both API `/api/v1/` and static frontend files `/` when `SERVE_FRONTEND=true`).
- **Frontend**: Vanilla ES modules (HTML5 + CSS + JavaScript, no bundler or build tools required).
- **Database**: PostgreSQL 15+ (running locally on port `55432` with `pg_trgm` and `btree_gist` extensions).
- **Row-Level Security (RLS)**: Enforced via PostgreSQL runtime role `hc_app` (`NOBYPASSRLS`). The application never connects as superuser or table owner during runtime.
- **File Storage**: Local directory (`./storage`), completely isolated from the web root.

---

## 2. Prerequisites

1. **Python 3.12+**
   - Verify: `python --version` (or `python3 --version`)
2. **PostgreSQL 15+** (with command line tools `pg_ctl`, `initdb`, `psql`)
   - Verify: `psql --version`
3. **Node.js** (Optional, used for `node --check` syntax validation)
   - Verify: `node --version`

---

## 3. Step-by-Step Local Setup

### Step 3.1: Clone & Virtual Environment

```bash
# Clone the repository and enter the project root
cd "Health Center"

# Create Python virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install locked dependencies
pip install -r requirements.lock.txt
```

---

### Step 3.2: Local PostgreSQL Cluster & Roles

The project uses a dedicated local cluster (defaulting to directory `.devdb/data` on port `55432`) or an existing local PostgreSQL 15+ instance.

#### Option A: Dedicated Local Cluster in `.devdb` (Recommended for Development)

1. Initialize cluster:
   ```bash
   initdb -D .devdb/data -E UTF8 --locale=C
   ```
2. Start PostgreSQL cluster on port `55432`:
   - **Windows**:
     ```powershell
     pg_ctl -D .devdb/data -o "-p 55432 -c listen_addresses=127.0.0.1" -l .devdb/pg.log start
     ```
   - **Linux / macOS**:
     ```bash
     pg_ctl -D .devdb/data -o "-p 55432 -c listen_addresses=127.0.0.1" -l .devdb/pg.log start
     ```

3. Connect to the cluster:
   - For a cluster initialized by Windows `initdb`, the initial superuser is your Windows username (`%USERNAME%`) or `hc_owner` (not `postgres`):
   ```bash
   psql -h 127.0.0.1 -p 55432 -U hc_owner -d postgres
   ```
   Execute the following SQL if setting up a fresh cluster for the first time:
   ```sql
   -- Superuser role for setup/tests
   CREATE ROLE hc_owner WITH SUPERUSER LOGIN PASSWORD 'hc_dev_pass';

   -- Schema owner role (owns tables and runs migrations/init-schema)
   CREATE ROLE hc_schema WITH LOGIN PASSWORD 'hc_dev_pass' NOSUPERUSER NOBYPASSRLS;

   -- Runtime app role (used by Flask app; strict RLS enforced)
   CREATE ROLE hc_app WITH LOGIN PASSWORD 'hc_dev_pass' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

   -- Development database
   CREATE DATABASE health_center OWNER hc_schema;

   -- Connect to health_center and install required extensions
   \c health_center
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   CREATE EXTENSION IF NOT EXISTS btree_gist;

   -- Grant connect permission
   GRANT CONNECT ON DATABASE health_center TO hc_app;
   ```

4. Create isolated test databases (for running test suites):
   ```sql
   CREATE DATABASE healthcenter_test OWNER hc_schema;
   \c healthcenter_test
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   CREATE EXTENSION IF NOT EXISTS btree_gist;
   GRANT CONNECT ON DATABASE healthcenter_test TO hc_app;

   -- For parallel test execution (databases healthcenter_test_1 through 12):
   CREATE DATABASE healthcenter_test_1 OWNER hc_schema;
   \c healthcenter_test_1
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   CREATE EXTENSION IF NOT EXISTS btree_gist;
   GRANT CONNECT ON DATABASE healthcenter_test_1 TO hc_app;
   ```

---

### Step 3.3: Environment Configuration (`.env`)

Copy `.env.example` to `.env`:

```bash
# Windows:
copy .env.example .env
# Linux / macOS:
cp .env.example .env
```

Verify your `.env` contents:
```ini
FLASK_ENV=development
SECRET_KEY=dev-secret-key-change-in-production-32-chars-min
DATABASE_URL=postgresql+psycopg://hc_app:hc_dev_pass@127.0.0.1:55432/health_center
SCHEMA_DATABASE_URL=postgresql+psycopg://hc_schema:hc_dev_pass@127.0.0.1:55432/health_center
TEST_DATABASE_URL=postgresql+psycopg://hc_app:hc_dev_pass@127.0.0.1:55432/healthcenter_test
TEST_SCHEMA_DATABASE_URL=postgresql+psycopg://hc_schema:hc_dev_pass@127.0.0.1:55432/healthcenter_test
STORAGE_ROOT=./storage
BACKUP_ROOT=./backups
LOG_DIR=./logs
SERVE_FRONTEND=1
SESSION_COOKIE_SECURE=0
```

---

### Step 3.4: Initialize Schema & Superadmin

1. **Initialize database schema** (creates tables, RLS policies, indexes, and seeds standard department types & subscription plans):
   ```bash
   flask --app backend.wsgi db init-schema
   ```
   > [!NOTE]
   > `init-schema` is idempotent and safe to run multiple times without data loss.

2. **Create Platform Superadmin Account**:
   ```bash
   flask --app backend.wsgi admin create-superadmin --username devadmin --name "System Administrator"
   ```
   You will be prompted to enter a secure password (or you can set `HC_SUPERADMIN_PASSWORD` in your environment).

3. **(Optional) Seed Demo Center**:
   To populate a complete demo health center with departments, clinics, doctors, receptionists, and sample patients:
   ```bash
   flask --app backend.wsgi dev seed-demo
   ```

---

## 4. Running the Local Application

Start the Flask development server:

```bash
flask --app backend.wsgi run --host 127.0.0.1 --port 5000 --debug
```

- **Application URL**: [http://127.0.0.1:5000](http://127.0.0.1:5000)
  - Use `127.0.0.1`, not `localhost`: on Windows `localhost` tries IPv6 first and every one of the ~130 module files waits ~1 s (first load ≈ 6 s instead of < 0.5 s).
- **API Health Endpoint**: [http://127.0.0.1:5000/api/v1/health](http://127.0.0.1:5000/api/v1/health)

Sign in with your superadmin account (`devadmin@aerodent.com` or custom username/email) to access the Superadmin Portal at `#/admin`.

---

## 5. Running Tests & Code Health Checks

### Backend Unit & Integration Tests

Run the complete test suite:
```bash
pytest
```

Run tests against a specific isolated test database:
```bash
TEST_DATABASE_URL=postgresql+psycopg://hc_app:hc_dev_pass@127.0.0.1:55432/healthcenter_test_1 \
TEST_SCHEMA_DATABASE_URL=postgresql+psycopg://hc_schema:hc_dev_pass@127.0.0.1:55432/healthcenter_test_1 \
pytest tests/test_core_auth.py
```

### Frontend Syntax & Import Validation

Validate JavaScript syntax for all native ES modules:
```bash
python -c "import glob, subprocess; [subprocess.run(['node', '--check', f], check=True) for f in glob.glob('web/**/*.js', recursive=True)]; print('All JS files syntax verified.')"
```

---

## 6. Local Management & Operations Commands

- **Stop PostgreSQL cluster**:
  ```bash
  pg_ctl -D .devdb/data stop
  ```
- **Purge expired staged deletions (30-second undo buffer)**:
  ```bash
  flask --app backend.wsgi ops purge-deletions
  ```
- **Garbage collect unreferenced storage files**:
  ```bash
  flask --app backend.wsgi ops storage-gc
  ```
- **Create manual database & storage backup snapshot**:
  ```bash
  flask --app backend.wsgi backup create
  ```

---

## 7. Troubleshooting Local Issues

| Issue | Cause | Resolution |
|---|---|---|
| `Connection refused: 127.0.0.1:55432` | PostgreSQL cluster is not running | Run `pg_ctl -D .devdb/data -o "-p 55432 -c listen_addresses=127.0.0.1" -l .devdb/pg.log start` and inspect `.devdb/pg.log`. |
| `permission denied for table ...` | Connected with improper role | Ensure `DATABASE_URL` uses `hc_app` and `SCHEMA_DATABASE_URL` uses `hc_schema`. Verify table ownership with `\dt`. |
| `RLS policy violation` | Query missing tenant context | Always query using `p.tenant(Model)` and ensure `app.mode` / `app.center_id` are set via `tenancy.scoped()`. |
| `Module not found` in browser console | Incorrect relative import | Verify relative import paths end with `.js` and pass `node --check`. |
| Session cookie not persisting | `SESSION_COOKIE_SECURE=1` over HTTP | In `.env`, ensure `SESSION_COOKIE_SECURE=0` when running locally over plain HTTP. |
