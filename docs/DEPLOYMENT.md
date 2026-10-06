# Deploying AeroCare on Ubuntu (24.04 LTS)

Internet → **Nginx** (HTTPS, serves `web/`) → **Gunicorn** (`backend.wsgi:app`, 127.0.0.1:8000) → Flask → **PostgreSQL** (localhost) + uploaded files in `/var/lib/aerocare/storage`.

Repo files used: `deploy/nginx/aerocare.conf`, `deploy/nginx/aerocare-headers.conf`, `deploy/gunicorn.conf.py`,
`deploy/systemd/aerocare.service`, `deploy/aerocare.env.example`, `requirements.lock.txt`, `backend/wsgi.py`.
There is **no frontend build step**: `web/` is plain HTML/CSS/ES modules served as-is.
Backups and restore: `docs/OPERATIONS.md`.

Replace `aerocare.example.com` with your domain everywhere below. Run commands as a sudo-capable admin unless noted.

---

## 1. System packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx postgresql postgresql-contrib python3-venv python3-dev build-essential \
     git fonts-dejavu-core certbot ufw
psql --version          # PostgreSQL 15+ required (16 on Ubuntu 24.04 is fine)
python3 --version       # 3.12 on Ubuntu 24.04 (3.11+ works)
```
`fonts-dejavu-core` is required: it provides the Arabic glyphs used in PDFs (invoices, prescriptions, reports).

## 2. Database (PostgreSQL)
Two login roles, on purpose:
| Role | Used by | Rights |
|---|---|---|
| `hc_schema` | `flask db init-schema`, full backups (`pg_dump`) | owns the database and tables |
| `hc_app` | the running app (Gunicorn) | data only; **not** superuser, **no** BYPASSRLS, not owner, so Row Level Security always applies |

```bash
sudo -u postgres psql
```
```sql
CREATE ROLE hc_schema LOGIN PASSWORD 'CHANGE-ME-1' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE hc_app    LOGIN PASSWORD 'CHANGE-ME-2' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE aerocare OWNER hc_schema ENCODING 'UTF8' TEMPLATE template0;
\c aerocare
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
\q
```
- Keep PostgreSQL local-only: `listen_addresses = 'localhost'` in `/etc/postgresql/16/main/postgresql.conf` (the default). The default `pg_hba.conf` line `host all all 127.0.0.1/32 scram-sha-256` is what the app uses.
- Connections: Gunicorn opens up to `GUNICORN_WORKERS × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` connections (3 × 20 = 60 with the example env). Keep this below `max_connections` (default 100).

## 3. System user and directories
```bash
sudo useradd --system --create-home --home-dir /opt/aerocare --shell /usr/sbin/nologin aerocare
sudo mkdir -p /var/lib/aerocare/storage /var/lib/aerocare/backups /var/log/aerocare /etc/aerocare /var/www/letsencrypt
sudo chown -R aerocare:aerocare /var/lib/aerocare /var/log/aerocare
sudo chmod 700 /var/lib/aerocare/storage /var/lib/aerocare/backups
```

## 4. Code and Python environment
```bash
sudo git clone https://github.com/frbhusen/AeroCare.git /opt/aerocare/app     # private repo: use a deploy key or token
sudo python3 -m venv /opt/aerocare/venv
sudo /opt/aerocare/venv/bin/pip install --upgrade pip
sudo /opt/aerocare/venv/bin/pip install -r /opt/aerocare/app/requirements.lock.txt
# Nginx (user www-data) must be able to read the static frontend:
sudo chmod 755 /opt/aerocare /opt/aerocare/app
sudo chmod -R a+rX /opt/aerocare/app/web
```
The code is owned by root and read-only to the app (only `/var/lib/aerocare` and `/var/log/aerocare` are writable — see the systemd unit).

## 5. Environment file
```bash
sudo cp /opt/aerocare/app/deploy/aerocare.env.example /etc/aerocare/aerocare.env
sudo chown root:aerocare /etc/aerocare/aerocare.env
sudo chmod 640 /etc/aerocare/aerocare.env
python3 -c "import secrets;print(secrets.token_urlsafe(64))"     # paste as SECRET_KEY
sudo nano /etc/aerocare/aerocare.env
```
Every variable the app reads:
| Variable | Value / meaning |
|---|---|
| `FLASK_ENV` | `production` (selects the production config; Secure cookies forced on) |
| `SECRET_KEY` | 64+ random characters (required — app refuses to start without it) |
| `DATABASE_URL` | `postgresql+psycopg://hc_app:<pw>@127.0.0.1:5432/aerocare` (required) |
| `SCHEMA_DATABASE_URL` | `postgresql+psycopg://hc_schema:<pw>@127.0.0.1:5432/aerocare` (init-schema + backups) |
| `STORAGE_ROOT` / `BACKUP_ROOT` / `LOG_DIR` | `/var/lib/aerocare/storage`, `/var/lib/aerocare/backups`, `/var/log/aerocare` |
| `SESSION_COOKIE_SECURE` | `1` — cookies only over HTTPS |
| `SESSION_IDLE_DAYS` | `30` — sessions unused this long end (0 = never) |
| `SESSION_MAX_AGE_DAYS` | `365` — cookie lifetime |
| `SERVE_FRONTEND` | `0` — Nginx serves `web/`; Flask only `/api` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | `3` / `2` (rule of thumb: 2 × CPU cores + 1 workers, mind DB connections) |
| `PDF_FONT_PATH` / `PDF_FONT_BOLD_PATH` | `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` / `…/DejaVuSans-Bold.ttf` |
| optional | `PG_DUMP` (pg_dump binary), `LOGIN_RATE_LIMIT` (default 10), `UNDO_WINDOW_SECONDS` (default 30), `BACKUP_DATABASE_URL` (other role for pg_dump) |

URL-encode special characters in passwords inside the URLs (e.g. `@` → `%40`).

## 6. Schema and first Superadmin
Run as the `aerocare` user with the env file loaded:
```bash
sudo -u aerocare bash -c 'set -a; . /etc/aerocare/aerocare.env; set +a; cd /opt/aerocare/app && \
  /opt/aerocare/venv/bin/flask --app backend.wsgi db init-schema'
sudo -u aerocare bash -c 'set -a; . /etc/aerocare/aerocare.env; set +a; cd /opt/aerocare/app && \
  /opt/aerocare/venv/bin/flask --app backend.wsgi admin create-superadmin --username owner --name "Platform Owner"'
```
- `init-schema` creates all tables, RLS policies, constraints, indexes, seeds plans + department types and grants `hc_app` its rights. It is idempotent and never drops data; run it after every upgrade (there are no migration files).
- `create-superadmin` prompts for the password (10+ chars, letters and digits, not containing the username) and prints the login email (`owner_<id>@aerodent.com`). Write that email down.
- Check isolation: `psql "postgresql://hc_app:<pw>@127.0.0.1/aerocare" -c "select count(*) from patients;"` must print `0` even once patients exist.

## 7. HTTPS certificate (before enabling the Nginx site)
`deploy/nginx/aerocare.conf` points at the certificate files, so get them first with a temporary HTTP site:
```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo tee /etc/nginx/sites-available/aerocare-acme >/dev/null <<'EOF'
server { listen 80; server_name aerocare.example.com;
         location /.well-known/acme-challenge/ { root /var/www/letsencrypt; } }
EOF
sudo ln -s /etc/nginx/sites-available/aerocare-acme /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d aerocare.example.com --agree-tos -m you@example.com
sudo rm /etc/nginx/sites-enabled/aerocare-acme
```
Renewal is automatic (`systemctl list-timers | grep certbot`); the final site keeps serving `/.well-known/acme-challenge/` on port 80 for it. Add a reload hook once:
```bash
echo -e '#!/bin/sh\nsystemctl reload nginx' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

## 8. Gunicorn service (systemd)
```bash
sudo cp /opt/aerocare/app/deploy/systemd/aerocare.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aerocare
sudo systemctl status aerocare --no-pager
curl -s http://127.0.0.1:8000/api/v1/health      # {"status":"ok"}
```
Logs: `journalctl -u aerocare -f` and `/var/log/aerocare/app.log` (no request bodies or medical content are logged).

## 9. Nginx site
```bash
sudo cp /opt/aerocare/app/deploy/nginx/aerocare-headers.conf /etc/nginx/snippets/aerocare-headers.conf
sudo cp /opt/aerocare/app/deploy/nginx/aerocare.conf /etc/nginx/sites-available/aerocare
sudo sed -i 's/example.com/aerocare.example.com/g' /etc/nginx/sites-available/aerocare
sudo ln -s /etc/nginx/sites-available/aerocare /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
`client_max_body_size 64m` allows multi-file uploads; the app itself rejects any file over 15 MB.

## 10. Firewall
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'          # 80 + 443
sudo ufw enable
sudo ufw status
```
PostgreSQL (5432) and Gunicorn (8000) stay closed: they only listen on localhost.

## 11. Backups (manual) and a restore test
- Full backup (database dump + all uploaded files), as the app user:
```bash
sudo -u aerocare bash -c 'set -a; . /etc/aerocare/aerocare.env; set +a; cd /opt/aerocare/app && \
  /opt/aerocare/venv/bin/flask --app backend.wsgi backup create'
```
  It writes `/var/lib/aerocare/backups/hc-backup-<timestamp>/` (`database.dump`, `files.zip`, `manifest.json`). `pg_dump` must be at least the server's major version (`postgresql-client` from the same apt repo is).
- Copy every backup **off the server**, encrypted (e.g. `gpg -c`), and delete old ones by hand. Nothing is automatic (spec §78); a cron entry calling the command above is fine if you want a schedule.
- Before going live, **do one restore test** on a spare VM following `docs/OPERATIONS.md` §2, then log in and open a patient file.

## 12. Upgrades
```bash
cd /opt/aerocare/app
sudo git fetch && sudo git log --oneline HEAD..origin/main      # see what's coming
# take a full backup first (step 11)
sudo git pull --ff-only
sudo /opt/aerocare/venv/bin/pip install -r requirements.lock.txt
sudo chmod -R a+rX /opt/aerocare/app/web
sudo -u aerocare bash -c 'set -a; . /etc/aerocare/aerocare.env; set +a; cd /opt/aerocare/app && \
  /opt/aerocare/venv/bin/flask --app backend.wsgi db init-schema'
sudo systemctl restart aerocare
# if deploy/nginx/* changed: re-copy them (step 9) and reload nginx
```
Browsers pick up the new frontend on the next load (static files are served with `Cache-Control: no-cache`).

## 13. Smoke test (after install and after every upgrade)
- [ ] `curl -s https://aerocare.example.com/api/v1/health` → `{"status":"ok"}`
- [ ] `curl -sI https://aerocare.example.com/` shows `strict-transport-security`, `content-security-policy`, `x-frame-options: DENY`
- [ ] `http://` redirects to `https://`
- [ ] Log in as the Superadmin (forced password change appears only for admin-set passwords) → create a health center with a manager → log in as that manager
- [ ] Create a department, clinic, doctor and receptionist; log in as the doctor; register a patient; book an appointment; write a visit
- [ ] Upload an image to the patient and open it; print an invoice PDF and check Arabic text renders
- [ ] Logging in on a second browser signs the first one out
- [ ] Browser dev tools → Application → Cookies: `hc_session` is `Secure`, `HttpOnly`, `SameSite=Lax`
- [ ] `journalctl -u aerocare --since -10min` shows no errors
- [ ] Run a backup (step 11) and confirm the three files exist

## Notes
- Timezone is fixed to Asia/Damascus in application logic; the server can stay on UTC.
- Staged deletions are purged by a thread in each Gunicorn worker (safe with several workers); `flask --app backend.wsgi ops purge-deletions` runs it by hand.
- Uploaded files never live under `web/`; they are only reachable through authenticated `/api/v1/files/<id>/content`.
- The app trusts one proxy hop for client IPs (`ProxyFix x_for=1`), which matches this Nginx setup. Don't put another proxy (e.g. Cloudflare) in front without adjusting it.
