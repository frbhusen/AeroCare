"""Manual full backups (spec §78): PostgreSQL dump (pg_dump custom format) + ZIP of uploaded
files, written to BACKUP_ROOT/hc-backup-<UTC timestamp>/. Restore: docs/OPERATIONS.md.

    flask --app backend.wsgi backup create        (CLI)
    POST /api/v1/admin/backups                    (Superadmin portal)
"""
import json
import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.app.core.timeutil import utcnow

log = logging.getLogger("hc.backup")

NAME_RE = re.compile(r"^hc-backup-\d{8}-\d{6}(-\d+)?$")
FILES = ("database.dump", "files.zip", "manifest.json")
WINDOWS_DEFAULT = Path("C:/Program Files/PostgreSQL/18/bin/pg_dump.exe")


class BackupError(RuntimeError):
    pass


def find_pg_dump():
    env = os.environ.get("PG_DUMP")
    if env and Path(env).is_file():
        return str(env)
    found = shutil.which("pg_dump")
    if found:
        return found
    if WINDOWS_DEFAULT.is_file():
        return str(WINDOWS_DEFAULT)
    raise BackupError("pg_dump was not found. Install the PostgreSQL client or set PG_DUMP.")


def _db_url(app):
    url = (os.environ.get("BACKUP_DATABASE_URL") or app.config.get("SCHEMA_DATABASE_URL")
           or app.config.get("SQLALCHEMY_DATABASE_URI"))
    if not url:
        raise BackupError("SCHEMA_DATABASE_URL is not configured")
    return make_url(url)


def _new_dir(root):
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    base = root / f"hc-backup-{stamp}"
    path, n = base, 1
    while path.exists():
        n += 1
        path = root / f"hc-backup-{stamp}-{n}"
    path.mkdir(parents=True)
    return path


def dump_database(app, out_file):
    url = _db_url(app)
    # Tables use FORCE ROW LEVEL SECURITY, so even the owner role is filtered: dump with RLS
    # enabled and the session in platform mode (the policies then expose every row).
    cmd = [find_pg_dump(), "--format=custom", "--no-password", "--enable-row-security", f"--file={out_file}"]
    if url.host:
        cmd.append(f"--host={url.host}")
    if url.port:
        cmd.append(f"--port={url.port}")
    if url.username:
        cmd.append(f"--username={url.username}")
    cmd.append(url.database)
    env = dict(os.environ)
    env["PGOPTIONS"] = (env.get("PGOPTIONS", "") + " -c app.mode=platform").strip()
    if url.password:
        env["PGPASSWORD"] = url.password
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=6 * 3600)
    if proc.returncode != 0:
        # stderr contains only connection/dump diagnostics, never row data.
        raise BackupError(f"pg_dump failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}")


def zip_storage(app, out_file):
    root = Path(app.config["STORAGE_ROOT"]).resolve()
    count = 0
    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file() and not p.name.endswith(".tmp"):
                    z.write(p, p.relative_to(root).as_posix())
                    count += 1
    return count


def create_full_backup(app):
    """Create a backup directory and return its Path. Raises BackupError on failure (the
    partial directory is removed)."""
    root = Path(app.config["BACKUP_ROOT"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = _new_dir(root)
    try:
        started = utcnow()
        dump_database(app, target / "database.dump")
        files = zip_storage(app, target / "files.zip")
        url = _db_url(app)
        manifest = {"created_at": started.isoformat(), "finished_at": utcnow().isoformat(),
                    "database": url.database, "format": "pg_dump custom", "stored_files": files,
                    "restore": "see docs/OPERATIONS.md"}
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    log.info("full backup written to %s", target.name)
    return target


def list_backups(app):
    root = Path(app.config["BACKUP_ROOT"]).resolve()
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir(), reverse=True):
        if not (d.is_dir() and NAME_RE.match(d.name)):
            continue
        manifest = {}
        try:
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        files = [{"name": f, "size_bytes": (d / f).stat().st_size} for f in FILES if (d / f).is_file()]
        out.append({"name": d.name, "created_at": manifest.get("created_at"), "complete": len(files) == len(FILES),
                    "stored_files": manifest.get("stored_files"), "files": files,
                    "total_bytes": sum(f["size_bytes"] for f in files)})
    return out


def backup_file_path(app, name, filename):
    """Validated absolute path of one backup file (None when missing/invalid)."""
    if not NAME_RE.match(name or "") or filename not in FILES:
        return None
    root = Path(app.config["BACKUP_ROOT"]).resolve()
    p = (root / name / filename).resolve()
    if root not in p.parents or not p.is_file():
        return None
    return p
