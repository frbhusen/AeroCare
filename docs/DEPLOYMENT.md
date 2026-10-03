# Deployment (dedicated Linux server)

Internet → Nginx (TLS, static `web/`) → Gunicorn (`backend.wsgi:app`) → Flask → PostgreSQL + secure file storage.
Files: `deploy/nginx/healthcenter.conf`, `deploy/gunicorn.conf.py`, `deploy/systemd/healthcenter.service`, `deploy/healthcenter.env.example`. Backups/restore: `docs/OPERATIONS.md`.

## 1. Packages (Debian/Ubuntu)
```
apt install nginx postgresql python3-venv python3-dev build-essential fonts-dejavu-core certbot python3-certbot-nginx
```
PostgreSQL 15+ required (RLS FORCE, `pg_trgm`, `btree_gist`).

## 2. Database roles
```sql
-- as postgres
CREATE ROLE hc_schema LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE hc_app    LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE healthcenter OWNER hc_schema;
\c healthcenter
CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS btree_gist;
```
The app connects as `hc_app` (never superuser, never table owner) so Row Level Security always applies.

## 3. Application
```
useradd --system --home /opt/healthcenter healthcenter
mkdir -p /opt/healthcenter /var/lib/healthcenter/{storage,backups} /var/log/healthcenter /etc/healthcenter
# copy the repository to /opt/healthcenter/app
python3 -m venv /opt/healthcenter/venv
/opt/healthcenter/venv/bin/pip install -r /opt/healthcenter/app/requirements.lock.txt
cp deploy/healthcenter.env.example /etc/healthcenter/healthcenter.env   # fill secrets; chmod 600
chown -R healthcenter: /var/lib/healthcenter /var/log/healthcenter
chmod 700 /var/lib/healthcenter/storage
```
Schema + first Superadmin (as the app user, with the env file loaded):
```
set -a; . /etc/healthcenter/healthcenter.env; set +a
cd /opt/healthcenter/app
venv/bin/flask --app backend.wsgi db init-schema
venv/bin/flask --app backend.wsgi admin create-superadmin --username owner --name "Platform Owner"
```
`init-schema` is idempotent and never drops data; re-run it after upgrades.

## 4. Services
```
cp deploy/systemd/healthcenter.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now healthcenter
cp deploy/nginx/healthcenter.conf /etc/nginx/sites-available/healthcenter   # set server_name + cert paths
ln -s /etc/nginx/sites-available/healthcenter /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
certbot --nginx -d your.domain
```

## 5. Checks
- `curl https://your.domain/api/v1/health` → `{"status":"ok"}`
- Login works; cookies are `Secure; HttpOnly; SameSite=Lax`.
- `journalctl -u healthcenter` and `/var/log/healthcenter/app.log` contain no request bodies / medical content.
- Firewall: only 80/443 (and SSH) open; PostgreSQL listens on localhost only.

## Notes
- Staged deletions are purged by a thread in each Gunicorn worker (safe concurrently). `flask ops purge-deletions` exists for manual runs.
- Timezone is fixed to Asia/Damascus in application logic; the server may run UTC.
- Static files are served by Nginx (`SERVE_FRONTEND=0`); uploaded files are never under the web root.
