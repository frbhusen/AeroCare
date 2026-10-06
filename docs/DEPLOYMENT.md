# Deployment (dedicated Linux server)

Internet → Nginx (TLS, static `web/`) → Gunicorn (`backend.wsgi:app`) → Flask → PostgreSQL + secure file storage.
Files: `deploy/nginx/aerocare.conf`, `deploy/gunicorn.conf.py`, `deploy/systemd/aerocare.service`, `deploy/aerocare.env.example`. Backups/restore: `docs/OPERATIONS.md`. Local setup: `docs/LOCAL_DEPLOYMENT.md`.

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
CREATE DATABASE aerocare OWNER hc_schema;
\c aerocare
CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS btree_gist;
```
The app connects as `hc_app` (never superuser, never table owner) so Row Level Security always applies.

## 3. Application
```
useradd --system --home /opt/aerocare aerocare
mkdir -p /opt/aerocare /var/lib/aerocare/{storage,backups} /var/log/aerocare /etc/aerocare
# copy the repository to /opt/aerocare/app
python3 -m venv /opt/aerocare/venv
/opt/aerocare/venv/bin/pip install -r /opt/aerocare/app/requirements.lock.txt
cp deploy/aerocare.env.example /etc/aerocare/aerocare.env   # fill secrets; chmod 600
chown -R aerocare: /var/lib/aerocare /var/log/aerocare
chmod 700 /var/lib/aerocare/storage
```
Schema + first Superadmin (as the app user, with the env file loaded):
```
set -a; . /etc/aerocare/aerocare.env; set +a
cd /opt/aerocare/app
venv/bin/flask --app backend.wsgi db init-schema
venv/bin/flask --app backend.wsgi admin create-superadmin --username owner --name "Platform Owner"
```
`init-schema` is idempotent and never drops data; re-run it after upgrades.

## 4. Services
```
cp deploy/systemd/aerocare.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now aerocare
cp deploy/nginx/aerocare.conf /etc/nginx/sites-available/aerocare   # set server_name + cert paths
ln -s /etc/nginx/sites-available/aerocare /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
certbot --nginx -d your.domain
```

## 5. Checks
- `curl https://your.domain/api/v1/health` → `{"status":"ok"}`
- Login works; cookies are `Secure; HttpOnly; SameSite=Lax`.
- `journalctl -u aerocare` and `/var/log/aerocare/app.log` contain no request bodies / medical content.
- Firewall: only 80/443 (and SSH) open; PostgreSQL listens on localhost only.

## Notes
- Staged deletions are purged by a thread in each Gunicorn worker (safe concurrently). `flask ops purge-deletions` exists for manual runs.
- Timezone is fixed to Asia/Damascus in application logic; the server may run UTC.
- Static files are served by Nginx (`SERVE_FRONTEND=0`); uploaded files are never under the web root.
