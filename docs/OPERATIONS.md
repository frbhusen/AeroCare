# Operations: backups and restore

Backups are **manual** (spec §78). Two kinds exist:

| Kind | Who | Contents | How |
|---|---|---|---|
| Full platform backup | Superadmin / server operator | PostgreSQL dump of the whole database + ZIP of `STORAGE_ROOT` | `flask --app backend.wsgi backup create` or Superadmin portal → Backups (`POST /api/v1/admin/backups`) |
| Center export | Health Center Manager (`backup.create`) | ZIP: JSON per table with that center's rows + its stored files | Center settings → Backup (`GET /api/v1/center/backup/export`) |

The full backup is the disaster-recovery mechanism. The center export is a portable copy of one tenant (data handover / archive); restoring it is a manual, assisted procedure (see the end).

## 1. Creating a full backup

```
set -a; . /etc/healthcenter/healthcenter.env; set +a
cd /opt/healthcenter/app
/opt/healthcenter/venv/bin/flask --app backend.wsgi backup create
# -> backup written: /var/lib/healthcenter/backups/hc-backup-20261004-031500
```

Each backup is a directory `BACKUP_ROOT/hc-backup-<UTC yyyymmdd-HHMMSS>/`:

| File | Content |
|---|---|
| `database.dump` | `pg_dump --format=custom` of the whole database (schema, data, RLS policies, triggers) |
| `files.zip` | every uploaded file under `STORAGE_ROOT` (paths = storage keys) |
| `manifest.json` | timestamps, database name, number of stored files |

Details:
- `pg_dump` is found via `$PG_DUMP`, then `PATH`, then `C:/Program Files/PostgreSQL/18/bin` (dev). The client major version must be >= the server's.
- Credentials: `SCHEMA_DATABASE_URL` (owner role `hc_schema`), or `BACKUP_DATABASE_URL` if set. The password is passed through `PGPASSWORD`, never on the command line. A `~/.pgpass` file also works.
- All tenant tables use `FORCE ROW LEVEL SECURITY`, so the dump runs with `--enable-row-security` and `PGOPTIONS=-c app.mode=platform`. The RLS policies then return every row. A dump made as a plain role without these settings fails with "query would be affected by row-level security policy".
- The Superadmin portal runs the same code synchronously. Gunicorn's `timeout` (60 s) can kill a large backup, so on big installations use the CLI (or cron it yourself; nothing is automatic).
- **Copy backups off the server** (e.g. `rsync`/`scp` to another machine or offline disk). `BACKUP_ROOT` is on the same disk as the data. The portal lists backups and downloads the three files one by one (`GET /api/v1/admin/backups/<name>/<file>`).
- Backups contain medical and financial data. Keep them encrypted at rest (e.g. `gpg -c` before moving them) and readable only by the operator (`chmod 700 BACKUP_ROOT`).
- Delete old backup directories by hand (`rm -r`). The application never deletes them.

## 2. Restoring on a fresh Linux server

Assumes the target follows `docs/DEPLOYMENT.md` sections 1-3 (packages, roles, app checkout, venv, env file). **Do not run `init-schema` before the restore.**

1. **Stop the application** (if it is running): `systemctl stop healthcenter`.
2. **Create roles + empty database** (as `postgres`). Use the same role names as the source:
   ```sql
   CREATE ROLE hc_schema LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS;
   CREATE ROLE hc_app    LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
   CREATE DATABASE healthcenter OWNER hc_schema;
   \c healthcenter
   CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS btree_gist;
   ```
3. **Restore the database** as the schema owner:
   ```
   pg_restore --no-owner --role=hc_schema --exit-on-error \
       -h 127.0.0.1 -U hc_schema -d healthcenter hc-backup-XXXX/database.dump
   ```
   `--no-owner` makes `hc_schema` own everything, whatever the source owner was. Warnings about existing extensions can be ignored. If the runtime role has a different name on the new server, step 5 grants it.
   If `--exit-on-error` stops on an RLS error while loading data, restore as the `postgres` superuser instead (`-U postgres --no-owner --role=hc_schema`). Superusers bypass RLS during the load.
4. **Restore the files** into `STORAGE_ROOT`:
   ```
   install -d -o healthcenter -m 700 /var/lib/healthcenter/storage
   cd /var/lib/healthcenter/storage && unzip /path/hc-backup-XXXX/files.zip
   chown -R healthcenter: /var/lib/healthcenter/storage
   ```
5. **Re-apply schema extras and grants** (idempotent, never drops data):
   ```
   set -a; . /etc/healthcenter/healthcenter.env; set +a
   cd /opt/healthcenter/app && /opt/healthcenter/venv/bin/flask --app backend.wsgi db init-schema
   ```
   This re-creates the RLS policies, the audit immutability trigger and the `GRANT`s for the runtime role named in `DATABASE_URL`.
6. **Environment**: copy the old `/etc/healthcenter/healthcenter.env` and adjust hosts/passwords. Keep `STORAGE_ROOT`, `BACKUP_ROOT` and `LOG_DIR` paths. A new `SECRET_KEY` only invalidates existing sessions (users log in again).
7. **Start and verify**: `systemctl start healthcenter`, reload Nginx (`deploy/nginx/healthcenter.conf`). Check `curl https://host/api/v1/health`, log in as a Superadmin, open a center and download a file. Run `flask --app backend.wsgi ops storage-gc --dry-run`: it should report 0 orphaned files. A non-zero count means `files.zip` did not match the dump (it removes nothing in dry-run mode).

Gunicorn/Nginx/systemd configuration: `deploy/gunicorn.conf.py`, `deploy/nginx/healthcenter.conf`, `deploy/systemd/healthcenter.service`, `docs/DEPLOYMENT.md`.

## 3. Center export (one tenant)

`GET /api/v1/center/backup/export` (permission `backup.create`: Health Center Manager, or Superadmin support view) streams a ZIP:

- `manifest.json`: center id/name/slug, time, exporting user, row counts per table, number of files, missing files.
- `tables/<table>.json`: a JSON array of rows for every table that has a `health_center_id` column (core and module tables, discovered from the metadata), plus `tables/health_centers.json` with the center row. Datetimes are ISO-8601, decimals are strings.
- `files/<storage_key>`: the bytes of every stored file of the center.

Not exported: password hashes (`users.password_hash`), sessions, offline idempotency records, staged deletions, notifications.

### Restoring a center export (manual)
A center export cannot be restored automatically into a running platform: IDs are global sequences and may already be used. Procedure:
1. Prefer the **full backup**: restore it on a scratch server (section 2) and copy what you need from there.
2. To re-import one center into a platform where its IDs are free (e.g. the center was deleted permanently and nothing reused the IDs): with the app stopped, load each `tables/*.json` file in the order of `manifest.json` → `row_counts`. That order is parents first (the metadata's dependency order). Load them as the `postgres` superuser with `INSERT ... SELECT * FROM json_populate_recordset(NULL::<table>, '<json>')`, starting with `health_centers`. Then copy `files/<key>` to `STORAGE_ROOT/<key>`. Then run `SELECT setval(pg_get_serial_sequence('<table>','id'), max(id)) FROM <table>` for every table and run `flask db init-schema`.
3. `users.password_hash` is NOT NULL but not exported: insert users with `password_hash = '!'` (`json_populate_recordset` + `COALESCE`), which matches no password. The Superadmin resets the center manager's password (`POST /api/v1/admin/users/<id>/password`), and the manager resets the staff passwords.
