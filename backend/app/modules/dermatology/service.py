"""Dermatology visits (structured dermatology detail per encounter) + photos."""
from sqlalchemy import func, select

from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import DateTime, Enum, Id, JsonDict, List, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import StoredFile, Visit
from backend.app.services import files as file_service

from . import visitkit
from .models import SEVERITIES, DermVisitRecord
from .regions import REGION_CODES, catalog

ENV = "dermatology"
RECORD_TYPE, VISIT_TYPE_KEY, OWNER_TYPE = "derm_record", "derm_visit", "derm_visit"
PHOTO_CATEGORIES = ("photo", "medical_image")

visitkit.register_record_type(DermVisitRecord, record_type=RECORD_TYPE, visit_type_key=VISIT_TYPE_KEY,
                              owner_type=OWNER_TYPE)

FIELDS = {
    "affected_areas": List(Enum(REGION_CODES), max_items=len(REGION_CODES)),
    "condition": Str(max_len=200),
    "symptoms": Text(max_len=5000),
    "severity": Enum(SEVERITIES),
    "diagnosis": Text(max_len=5000),
    "examination_findings": Text(max_len=10000),
    "treatment": Text(max_len=10000),
    "notes": Text(max_len=10000),
    "extra": JsonDict(),
}
VISIT_FIELDS = {
    "visit_at": DateTime(),
    "visit_type": Enum(visitkit.VISIT_TYPES),
    "title": Str(max_len=200),
    "status": Enum(visitkit.VISIT_STATUSES),
}
CREATE_SCHEMA = {"visit_id": Id(), "patient_id": Id(), "clinic_id": Id(), **VISIT_FIELDS, **FIELDS}
UPDATE_SCHEMA = {**VISIT_FIELDS, **FIELDS}


def meta():
    return {"severities": list(SEVERITIES), "visit_types": list(visitkit.VISIT_TYPES),
            "visit_statuses": list(visitkit.VISIT_STATUSES), "photo_categories": list(PHOTO_CATEGORIES),
            "body_regions": catalog()}


def _dedupe(seq):
    return list(dict.fromkeys(seq or []))


def to_json(rec, visit, clinic_name=None, photo_count=None):
    out = {
        "id": rec.id, "patient_id": rec.patient_id, "department_id": rec.department_id, "clinic_id": rec.clinic_id,
        "owns_visit": rec.owns_visit, "affected_areas": rec.affected_areas or [], "condition": rec.condition,
        "symptoms": rec.symptoms, "severity": rec.severity, "diagnosis": rec.diagnosis,
        "examination_findings": rec.examination_findings, "treatment": rec.treatment, "notes": rec.notes,
        "extra": rec.extra or {},
        **visitkit.visit_json(visit, clinic_name), **visitkit.author_json(rec),
    }
    if photo_count is not None:
        out["photo_count"] = photo_count
    return out


def _photo_counts(p, ids):
    if not ids:
        return {}
    rows = db.session.execute(select(StoredFile.owner_id, func.count()).where(
        file_service.visible_clause(p), StoredFile.owner_type == OWNER_TYPE, StoredFile.owner_id.in_(ids))
        .group_by(StoredFile.owner_id)).all()
    return dict(rows)


def list_patient_visits(p, patient_id, clinic_id=None):
    stmt = visitkit.list_for_patient(p, DermVisitRecord, patient_id, ENV, clinic_id)
    out = visitkit.paginate_rows(stmt)
    counts = _photo_counts(p, [r[0].id for r in out["items"]])
    out["items"] = [to_json(*r, photo_count=counts.get(r[0].id, 0)) for r in out["items"]]
    return out


def create(p, body):
    data = validate(body, CREATE_SCHEMA)
    visit, owns = visitkit.resolve_visit(p, data, ENV, "consultation")
    if not owns:
        exists = db.session.execute(select(DermVisitRecord.id).where(DermVisitRecord.visit_id == visit.id)).first()
        if exists:
            raise Conflict("This visit already has a dermatology record.", code="already_exists")
    rec = DermVisitRecord(health_center_id=p.center_id, patient_id=visit.patient_id,
                          department_id=visit.department_id, clinic_id=visit.clinic_id, visit_id=visit.id,
                          owns_visit=owns)
    _apply(rec, data)
    rec.set_author(p.user)
    db.session.add(rec)
    db.session.commit()
    return get(p, rec.id)


def _apply(rec, data):
    for k in FIELDS:
        if k in data:
            v = data[k]
            if k == "affected_areas":
                v = _dedupe(v)
            elif k == "extra":
                v = v or {}
            setattr(rec, k, v)


def get(p, record_id):
    rec, visit, clinic_name = visitkit.get_record(p, DermVisitRecord, record_id, label="Dermatology visit")
    return to_json(rec, visit, clinic_name, photo_count=_photo_counts(p, [rec.id]).get(rec.id, 0))


def update(p, record_id, body):
    rec, visit, _ = visitkit.get_record(p, DermVisitRecord, record_id, perm="medical_records.edit",
                                        label="Dermatology visit")
    check_version(rec, (body or {}).get("version"))
    data = validate(body, UPDATE_SCHEMA, partial=True)
    if any(k in data for k in VISIT_FIELDS):
        if not rec.owns_visit:
            raise ValidationError("Visit details can only be changed from the visit itself.",
                                  code="visit_not_owned")
        visitkit.apply_visit_fields(visit, data)
    _apply(rec, data)
    rec.updated_at = utcnow()  # bump version even when only the visit changed
    db.session.commit()
    return get(p, rec.id)


def delete(p, record_id):
    rec, visit, _ = visitkit.get_record(p, DermVisitRecord, record_id, perm=None, label="Dermatology visit")
    return visitkit.stage_delete(p, rec, visit, record_type=RECORD_TYPE, visit_type_key=VISIT_TYPE_KEY,
                                 label=f"Dermatology visit {iso(visit.visit_at)[:10]}")


# ---- photos ---------------------------------------------------------------
def upload_photos(p, record_id, uploads, category="photo", description=None):
    rec, visit, _ = visitkit.get_record(p, DermVisitRecord, record_id, perm=None, label="Dermatology visit")
    p.require("files.upload", clinic_id=rec.clinic_id)
    if category not in PHOTO_CATEGORIES:
        raise ValidationError("Invalid input", details={"category": "must be one of: " + ", ".join(PHOTO_CATEGORIES)})
    if description and len(description) > 2000:
        raise ValidationError("Invalid input", details={"description": "must be at most 2000 characters"})
    rows = file_service.store_upload(p, uploads, clinic_id=rec.clinic_id, department_id=rec.department_id,
                                     patient_id=rec.patient_id, visit_id=visit.id, category=category,
                                     owner_type=OWNER_TYPE, owner_id=rec.id, description=description)
    return {"items": [file_service.serialize(f, p) for f in rows]}


def list_photos(p, record_id):
    rec, _, _ = visitkit.get_record(p, DermVisitRecord, record_id, perm=None, label="Dermatology visit")
    p.require("files.view", clinic_id=rec.clinic_id)
    return {"items": owned_files(p, OWNER_TYPE, rec.id)}


def owned_files(p, owner_type, owner_id):
    rows = db.session.execute(select(StoredFile).where(
        file_service.visible_clause(p), StoredFile.owner_type == owner_type, StoredFile.owner_id == owner_id)
        .order_by(StoredFile.created_at, StoredFile.id)).scalars().all()
    return [file_service.serialize(f, p) for f in rows]


# ---- summary (access-scoped) ------------------------------------------------
def patient_summary(p, patient_id, limit=5):
    """Dermatology part of the Complete Patient Summary, limited to the principal's clinics.
    Returns None when the principal has no medical_records.view or no visible derm data."""
    if not p.has("medical_records.view"):
        return None
    stmt = visitkit.scoped_record_stmt(p, DermVisitRecord).where(DermVisitRecord.patient_id == patient_id)
    total = db.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    if not total:
        return None
    recent = db.session.execute(stmt.order_by(Visit.visit_at.desc()).limit(limit)).all()
    return {"type": "dermatology", "title": "Dermatology", "visit_count": total,
            "recent": [{"id": r.id, "visit_at": iso(v.visit_at), "clinic_name": cn, "condition": r.condition,
                        "diagnosis": r.diagnosis, "severity": r.severity, "affected_areas": r.affected_areas or []}
                       for r, v, cn in recent]}


def _register_summary():
    try:
        from backend.app.modules.patients.summary import register_summary_provider
    except ImportError:  # patients module absent: patient_summary() stays callable directly
        return
    register_summary_provider("dermatology", lambda p, patient: patient_summary(p, patient.id), order=210)


_register_summary()
