"""Dental X-rays: metadata rows + bytes in the platform file store (services.files)."""
from sqlalchemy import select

from backend.app.core.api import check_version
from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.storage import get_storage, sha256, validate_upload
from backend.app.core.timeutil import iso, local_today
from backend.app.core.validation import Date, Enum, Id, Int, Str, Text, Time, validate
from backend.app.extensions import db
from backend.app.models import StoredFile
from backend.app.services import deletion, files

from . import constants as C
from .models import XRay
from .service import clinic_filter, resolve_clinic, resolve_visit, visible_patient, writable_patient

OWNER_TYPE = "dental_xray"

# The staged entity is the X-ray's StoredFile row: while staged it is hidden from generic file
# lists AND (via the join in _query) from X-ray lists; undo restores both. Purging the file
# cascades to dental_xrays (fk_dxray_file ON DELETE CASCADE) and the purger removes the bytes.
deletion.register("dental_xray", StoredFile, files=lambda f: StoredFile.id == f.id)

META_SCHEMA = {
    "filename": Str(max_len=255),
    "type": Enum(C.XRAY_TYPES),
    "tooth_tag": Str(max_len=100),
    "date": Date(),
    "time": Time(),
    "notes": Text(max_len=5000),
    "visit_id": Id(),
}


def xray_json(x, f):
    return {
        "id": x.id, "clinic_id": x.clinic_id, "department_id": x.department_id, "patient_id": x.patient_id,
        "visit_id": x.visit_id, "filename": x.filename, "type": x.type, "tooth_tag": x.tooth_tag,
        "date": iso(x.date), "time": x.time.strftime("%H:%M") if x.time else None, "notes": x.notes,
        "uploaded_by": x.author_name, "author_role": x.author_role, "created_at": iso(x.created_at),
        "updated_at": iso(x.updated_at), "version": x.version,
        "file": {"id": f.id, "url": f"/api/v1/files/{f.id}/content", "mime_type": f.mime_type,
                 "size_bytes": f.size_bytes, "sha256": f.sha256, "is_image": f.mime_type.startswith("image/"),
                 "original_name": f.original_name},
    }


def _query(p):
    return (select(XRay, StoredFile).join(StoredFile, (StoredFile.id == XRay.file_id)
                                          & (StoredFile.health_center_id == XRay.health_center_id))
            .where(p.tenant(XRay), XRay.live(), StoredFile.live(), clinic_filter(p, XRay.clinic_id)))


def _get(p, xid):
    row = db.session.execute(_query(p).where(XRay.id == xid)).first()
    if row is None:
        raise NotFound("X-ray not found")
    return row


def upload(p, patient_id, form, uploads):
    head = validate(dict(form), {"clinic_id": Id()})
    data = validate(dict(form), META_SCHEMA)
    clinic_id, dept = resolve_clinic(p, head.get("clinic_id"))
    p.require("medical_records.create", clinic_id=clinic_id)
    p.require("files.upload")
    if not uploads:
        raise ValidationError("Choose an X-ray image.", code="no_files", details={"file": "is required"})
    if len(uploads) > 1:
        raise ValidationError("Upload one X-ray at a time.", details={"file": "only one file is allowed"})
    up = uploads[0]
    raw = up.read()
    name, mime = validate_upload(up.filename, raw)  # size, extension allow-list, magic bytes
    if mime not in C.XRAY_MIMES:
        raise ValidationError("X-rays must be images (JPEG, PNG, WebP, GIF, BMP, TIFF) or DICOM.",
                              code="xray_type_not_allowed")
    up.stream.seek(0)
    patient = writable_patient(p, patient_id, clinic_id, dept)
    visit = resolve_visit(p, data.get("visit_id"), clinic_id, patient.id)
    (f,) = files.store_upload(p, [up], clinic_id=clinic_id, department_id=dept, patient_id=patient.id,
                              visit_id=visit.id if visit else None,
                              category="xray", owner_type=OWNER_TYPE, commit=False)
    try:
        x = XRay(health_center_id=p.center_id, clinic_id=clinic_id, department_id=dept, patient_id=patient.id,
                 visit_id=visit.id if visit else None, file_id=f.id,
                 filename=data.get("filename") or name, type=data.get("type") or "other",
                 tooth_tag=data.get("tooth_tag"), date=data.get("date") or local_today(), time=data.get("time"),
                 notes=data.get("notes"))
        x.set_author(p.user)
        db.session.add(x)
        db.session.flush()
        f.owner_id = x.id
        db.session.commit()
    except Exception:
        db.session.rollback()
        get_storage().delete(f.storage_key)
        raise
    return xray_json(x, f)


def list_xrays(p, patient_id, args):
    a = validate(args, {"clinic_id": Id(), "type": Enum(C.XRAY_TYPES), "tooth_tag": Str(max_len=100),
                        "date": Date()})
    p.require("medical_records.view")
    patient = visible_patient(p, patient_id)
    stmt = _query(p).where(XRay.patient_id == patient.id)
    if a.get("clinic_id"):
        stmt = stmt.where(clinic_filter(p, XRay.clinic_id, a["clinic_id"]))
    for k in ("type", "tooth_tag", "date"):
        if a.get(k):
            stmt = stmt.where(getattr(XRay, k) == a[k])
    rows = db.session.execute(stmt.order_by(XRay.date.desc(), XRay.id.desc()).limit(500)).all()
    return {"items": [xray_json(x, f) for x, f in rows], "patient_id": patient.id}


def get_xray(p, xid):
    x, f = _get(p, xid)
    p.require("medical_records.view")
    return xray_json(x, f)


def update_xray(p, xid, body):
    x, f = _get(p, xid)
    p.require("medical_records.edit", clinic_id=x.clinic_id)
    data = validate(body, {**META_SCHEMA, "version": Int()}, partial=True)
    check_version(x, data.get("version"))
    for k in ("filename", "type", "date"):
        if k in data and not data[k]:
            raise ValidationError("Invalid input", details={k: "is required"})
    for k in ("filename", "type", "tooth_tag", "date", "time", "notes"):
        if k in data:
            setattr(x, k, data[k])
    if "visit_id" in data:
        x.visit_id = resolve_visit(p, data["visit_id"], x.clinic_id, x.patient_id).id if data["visit_id"] else None
        f.visit_id = x.visit_id
    if "filename" in data:
        f.display_name = data["filename"]
    db.session.commit()
    return xray_json(x, f)


def delete_xray(p, xid):
    x, f = _get(p, xid)
    p.require("medical_records.delete", clinic_id=x.clinic_id)
    return deletion.stage(p, f, "dental_xray", label=f"X-ray {x.filename}"[:255])


def verify_xray(p, xid):
    """Integrity check (AeroDent /verify): stored bytes still match the recorded SHA-256."""
    x, f = _get(p, xid)
    p.require("medical_records.view")
    try:
        data = get_storage().read(f.storage_key)
    except (OSError, ValueError):
        return {"id": x.id, "verified": False, "reason": "missing"}
    ok = sha256(data) == f.sha256 and len(data) == f.size_bytes
    return {"id": x.id, "verified": ok, "reason": None if ok else "checksum_mismatch", "sha256": f.sha256}
