"""Tenant-scoped center export (backup.create): a ZIP with one JSON array per tenant table
(every table in the metadata with a `health_center_id` column, rows of this center only), the
center row itself, and the stored file bytes under files/<storage_key>.

Password hashes, sessions, idempotency records, staged deletions and notifications are not
exported. Restore is a manual procedure (docs/OPERATIONS.md, "Center export").
"""
import base64
import json
import tempfile
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from backend.app.core.storage import get_storage
from backend.app.core.timeutil import utcnow
from backend.app.extensions import db
from backend.app.models import HealthCenter, StoredFile

EXCLUDED_TABLES = {"offline_sync_operations", "deletion_buffer", "notifications", "user_sessions"}
EXCLUDED_COLUMNS = {"users": {"password_hash"}}
FORMAT_VERSION = 1


def _default(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode("ascii")
    return str(v)


def _write_rows(z, name, rows):
    count = 0
    with z.open(f"tables/{name}.json", "w", force_zip64=True) as fh:
        fh.write(b"[")
        for row in rows:
            fh.write((b",\n" if count else b"\n") + json.dumps(row, default=_default, ensure_ascii=False).encode())
            count += 1
        fh.write(b"\n]")
    return count


def build_export(p):
    """Return (temporary file positioned at 0, download name). Caller streams and closes it."""
    import zipfile
    p.require("backup.create")
    cid = p.center_id
    center = db.session.get(HealthCenter, cid)
    tmp = tempfile.TemporaryFile()
    counts = {}
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        ht = HealthCenter.__table__
        counts["health_centers"] = _write_rows(
            z, "health_centers", (dict(r) for r in db.session.execute(select(ht).where(ht.c.id == cid)).mappings()))
        for t in db.metadata.sorted_tables:
            if "health_center_id" not in t.c or t.name in EXCLUDED_TABLES:
                continue
            skip = EXCLUDED_COLUMNS.get(t.name, set())
            cols = [c for c in t.c if c.name not in skip]
            stmt = select(*cols).where(t.c.health_center_id == cid)
            pk = list(t.primary_key.columns)
            if pk:
                stmt = stmt.order_by(*pk)
            result = db.session.execute(stmt.execution_options(yield_per=1000)).mappings()
            counts[t.name] = _write_rows(z, t.name, (dict(r) for r in result))
        storage = get_storage()
        files, missing = 0, []
        for key in db.session.execute(select(StoredFile.storage_key).where(StoredFile.health_center_id == cid)
                                      .order_by(StoredFile.id)).scalars():
            try:
                z.write(storage.path(key), f"files/{key}")
                files += 1
            except (OSError, ValueError):
                missing.append(key)
        manifest = {"format": "health-center-export", "format_version": FORMAT_VERSION,
                    "center": {"id": center.id, "name": center.name, "slug": center.slug},
                    "created_at": utcnow().isoformat(), "created_by": p.user.id, "row_counts": counts,
                    "files": files, "missing_files": missing,
                    "excluded": {"tables": sorted(EXCLUDED_TABLES), "columns": {k: sorted(v) for k, v in
                                                                                EXCLUDED_COLUMNS.items()}}}
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    tmp.seek(0)
    name = f"{center.slug}-export-{utcnow():%Y%m%d-%H%M%S}.zip"
    return tmp, name
