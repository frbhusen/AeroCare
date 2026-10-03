"""Ophthalmology examinations: one structured exam per visit (OD/OS blocks + prescription)."""
from sqlalchemy import func, select

from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import DateTime, Enum, Id, JsonDict, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Visit
from backend.app.modules.dermatology import visitkit

from . import schemas
from .models import OphthalmologyExam

ENV = "ophthalmology"
RECORD_TYPE, VISIT_TYPE_KEY, OWNER_TYPE = "oph_exam", "oph_exam_visit", "oph_exam"

visitkit.register_record_type(OphthalmologyExam, record_type=RECORD_TYPE, visit_type_key=VISIT_TYPE_KEY,
                              owner_type=OWNER_TYPE)

TEXT_FIELDS = {
    "chief_complaint": Text(max_len=5000),
    "history": Text(max_len=10000),
    "diagnosis": Text(max_len=5000),
    "treatment": Text(max_len=10000),
    "follow_up": Str(max_len=200),
    "notes": Text(max_len=10000),
}
BLOCKS = {"right_eye": "eye", "left_eye": "eye", "glasses": "glasses"}
VISIT_FIELDS = {
    "visit_at": DateTime(),
    "visit_type": Enum(visitkit.VISIT_TYPES),
    "title": Str(max_len=200),
    "status": Enum(visitkit.VISIT_STATUSES),
}
_RAW = {k: JsonDict(max_keys=50) for k in BLOCKS}
CREATE_SCHEMA = {"visit_id": Id(), "patient_id": Id(), "clinic_id": Id(), **VISIT_FIELDS, **TEXT_FIELDS, **_RAW,
                 "extra": JsonDict()}
UPDATE_SCHEMA = {**VISIT_FIELDS, **TEXT_FIELDS, **_RAW, "extra": JsonDict()}
EYES = [{"code": "right_eye", "abbr": "OD", "en": "Right eye", "ar": "العين اليمنى"},
        {"code": "left_eye", "abbr": "OS", "en": "Left eye", "ar": "العين اليسرى"}]


def meta():
    return {"visit_types": list(visitkit.VISIT_TYPES), "visit_statuses": list(visitkit.VISIT_STATUSES),
            "eye_fields": schemas.describe(), "glasses_fields": schemas.describe(schemas.GLASSES), "eyes": EYES}


def _blocks(data):
    out, errors = {}, {}
    for key, kind in BLOCKS.items():
        if key in data:
            try:
                out[key] = schemas.validate_block(data[key], kind, key)
            except ValidationError as e:
                errors.update(e.details or {})
    if errors:
        raise ValidationError("Invalid input", details=errors)
    return out


def to_json(e, visit, clinic_name=None):
    return {"id": e.id, "patient_id": e.patient_id, "department_id": e.department_id, "clinic_id": e.clinic_id,
            "owns_visit": e.owns_visit, **{k: getattr(e, k) for k in TEXT_FIELDS},
            "right_eye": e.right_eye or {}, "left_eye": e.left_eye or {}, "glasses": e.glasses or {},
            "extra": e.extra or {}, **visitkit.visit_json(visit, clinic_name), **visitkit.author_json(e)}


def list_patient_exams(p, patient_id, clinic_id=None):
    stmt = visitkit.list_for_patient(p, OphthalmologyExam, patient_id, ENV, clinic_id)
    out = visitkit.paginate_rows(stmt)
    out["items"] = [to_json(*r) for r in out["items"]]
    return out


def _apply(e, data, blocks):
    for k in TEXT_FIELDS:
        if k in data:
            setattr(e, k, data[k])
    for k, v in blocks.items():
        setattr(e, k, v)
    if "extra" in data:
        e.extra = data["extra"] or {}


def create(p, body):
    data = validate(body, CREATE_SCHEMA)
    blocks = _blocks(data)
    visit, owns = visitkit.resolve_visit(p, data, ENV, "examination")
    if not owns and db.session.execute(select(OphthalmologyExam.id).where(OphthalmologyExam.visit_id == visit.id)
                                       ).first():
        raise Conflict("This visit already has an eye examination.", code="already_exists")
    e = OphthalmologyExam(health_center_id=p.center_id, patient_id=visit.patient_id,
                          department_id=visit.department_id, clinic_id=visit.clinic_id, visit_id=visit.id,
                          owns_visit=owns, right_eye={}, left_eye={}, glasses={}, extra={})
    _apply(e, data, blocks)
    e.set_author(p.user)
    db.session.add(e)
    db.session.commit()
    return get(p, e.id)


def get(p, exam_id):
    return to_json(*visitkit.get_record(p, OphthalmologyExam, exam_id, label="Eye examination"))


def update(p, exam_id, body):
    e, visit, _ = visitkit.get_record(p, OphthalmologyExam, exam_id, perm="medical_records.edit",
                                      label="Eye examination")
    check_version(e, (body or {}).get("version"))
    data = validate(body, UPDATE_SCHEMA, partial=True)
    blocks = _blocks(data)
    if any(k in data for k in VISIT_FIELDS):
        if not e.owns_visit:
            raise ValidationError("Visit details can only be changed from the visit itself.",
                                  code="visit_not_owned")
        visitkit.apply_visit_fields(visit, data)
    _apply(e, data, blocks)
    e.updated_at = utcnow()
    db.session.commit()
    return get(p, e.id)


def delete(p, exam_id):
    e, visit, _ = visitkit.get_record(p, OphthalmologyExam, exam_id, perm=None, label="Eye examination")
    return visitkit.stage_delete(p, e, visit, record_type=RECORD_TYPE, visit_type_key=VISIT_TYPE_KEY,
                                 label=f"Eye examination {iso(visit.visit_at)[:10]}")


def _eye_brief(d):
    va = d.get("visual_acuity") or {}
    return {"va": va.get("best_corrected") or va.get("uncorrected"), "iop": (d.get("iop") or {}).get("value")}


def patient_summary(p, patient_id, limit=5):
    """Ophthalmology part of the Complete Patient Summary (access-scoped). None if nothing visible."""
    if not p.has("medical_records.view"):
        return None
    stmt = visitkit.scoped_record_stmt(p, OphthalmologyExam).where(OphthalmologyExam.patient_id == patient_id)
    total = db.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    if not total:
        return None
    rows = db.session.execute(stmt.order_by(Visit.visit_at.desc()).limit(limit)).all()
    return {"type": "ophthalmology", "title": "Ophthalmology", "exam_count": total,
            "recent": [{"id": e.id, "visit_at": iso(v.visit_at), "clinic_name": cn, "diagnosis": e.diagnosis,
                        "od": _eye_brief(e.right_eye or {}), "os": _eye_brief(e.left_eye or {})}
                       for e, v, cn in rows]}


def _register_summary():
    try:
        from backend.app.modules.patients.summary import register_summary_provider
    except ImportError:  # patients module absent: patient_summary() stays callable directly
        return
    register_summary_provider("ophthalmology", lambda p, patient: patient_summary(p, patient.id), order=230)


_register_summary()
