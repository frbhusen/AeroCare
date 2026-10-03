"""Generic medical environment service: visit + GenericVisitRecord, only for clinics whose
department environment is 'generic'."""
from sqlalchemy import select

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import ValidationError
from backend.app.core.timeutil import iso
from backend.app.core.validation import Id, JsonDict, Num, Obj, Text, validate
from backend.app.extensions import db
from backend.app.models import Visit
from backend.app.services.clinical import get_patient, get_visit, require_environment

from backend.app.modules.patients import visits as visits_service
from .models import GenericVisitRecord

ENV = "generic"

# name -> (min, max, unit, decimals)
VITALS = {
    "bp_systolic": (30, 300, "mmHg", 0),
    "bp_diastolic": (10, 200, "mmHg", 0),
    "heart_rate": (10, 300, "bpm", 0),
    "temperature": (25, 45, "°C", 1),
    "resp_rate": (1, 100, "/min", 0),
    "spo2": (0, 100, "%", 0),
    "weight": (0.2, 500, "kg", 2),
    "height": (20, 260, "cm", 1),
}
TEXT_FIELDS = ("chief_complaint", "symptoms", "examination", "diagnosis", "assessment", "treatment_plan",
               "medications", "notes")

RECORD_SCHEMA = {
    **{k: Text(max_len=10000) for k in TEXT_FIELDS},
    "vitals": Obj({k: Num(min_value=lo, max_value=hi, places=dec) for k, (lo, hi, _u, dec) in VITALS.items()}),
    "extra": JsonDict(max_keys=100),
}


def _vitals(v):
    out = {}
    for k, val in (v or {}).items():
        if val is None:
            continue
        f = float(val)
        out[k] = int(f) if VITALS[k][3] == 0 else f
    return out


def record_json(r):
    if r is None:
        return None
    out = {k: getattr(r, k) for k in TEXT_FIELDS}
    out.update({"id": r.id, "visit_id": r.visit_id, "patient_id": r.patient_id, "clinic_id": r.clinic_id,
                "vitals": r.vitals or {}, "extra": r.extra or {}, "author_name": r.author_name,
                "author_role": r.author_role, "last_edited_name": r.last_edited_name,
                "created_at": iso(r.created_at), "updated_at": iso(r.updated_at), "version": r.version})
    if r.vitals and r.vitals.get("weight") and r.vitals.get("height"):
        h = r.vitals["height"] / 100.0
        out["bmi"] = round(r.vitals["weight"] / (h * h), 1)
    return out


def _record_for(visit_id):
    return db.session.execute(select(GenericVisitRecord).where(GenericVisitRecord.visit_id == visit_id)
                              ).scalar_one_or_none()


def _apply(rec, data, p):
    for k in TEXT_FIELDS:
        if k in data:
            setattr(rec, k, data[k])
    if "vitals" in data:
        rec.vitals = _vitals(data["vitals"])
    if "extra" in data:
        rec.extra = data["extra"] or {}
    rec.last_edited_by = p.user.id
    rec.last_edited_name = p.user.name


def _generic_visit(p, visit_id, perm):
    v = get_visit(p, visit_id, perm=perm)
    require_environment(p, v.clinic_id, ENV)
    return v


def create(p, body):
    """One call: visit + generic record (atomic)."""
    rec_data = validate((body or {}).get("record") or {}, RECORD_SCHEMA, partial=True)
    v = visits_service.create(p, body, environments=[ENV], commit=False)
    rec = GenericVisitRecord(health_center_id=p.center_id, visit_id=v.id, patient_id=v.patient_id,
                             clinic_id=v.clinic_id, vitals={}, extra={})
    rec.set_author(p.user)
    _apply(rec, rec_data, p)
    db.session.add(rec)
    db.session.commit()
    return v, rec


def get(p, visit_id):
    v = _generic_visit(p, visit_id, "medical_records.view")
    return v, _record_for(v.id)


def save_record(p, visit_id, body):
    """Create the record if the visit has none yet; otherwise a versioned update."""
    rec = None
    v = get_visit(p, visit_id, perm=None)
    require_environment(p, v.clinic_id, ENV)
    rec = _record_for(v.id)
    if rec is None:
        p.require("medical_records.create")
        data = validate(body, RECORD_SCHEMA, partial=True)
        rec = GenericVisitRecord(health_center_id=p.center_id, visit_id=v.id, patient_id=v.patient_id,
                                 clinic_id=v.clinic_id, vitals={}, extra={})
        rec.set_author(p.user)
        db.session.add(rec)
    else:
        p.require("medical_records.edit")
        data = validate(body, {**RECORD_SCHEMA, "version": Id(required=True)}, partial=True)
        if "version" not in data:
            raise ValidationError("version is required for updates", details={"version": "is required"})
        check_version(rec, data.pop("version"))
    _apply(rec, data, p)
    db.session.commit()
    return v, rec


def list_for_patient(p, patient_id, args):
    """Generic visits (with record digest) of a patient in the caller's generic clinics."""
    p.require("medical_records.view")
    get_patient(p, patient_id)
    clinics = [c for c, d in p.clinic_department.items() if p.department_env.get(d) == ENV]
    stmt = (select(Visit).where(Visit.patient_id == patient_id, p.tenant(Visit), Visit.live(),
                                Visit.clinic_id.in_(clinics or [-1]), p.clinic_clause(Visit.clinic_id))
            .order_by(Visit.visit_at.desc(), Visit.id.desc()))
    clinic_id = args.get("clinic_id")
    if clinic_id:
        try:
            clinic_id = int(clinic_id)
        except ValueError:
            raise ValidationError("Invalid input", details={"clinic_id": "must be an integer"})
        p.require(clinic_id=clinic_id)
        stmt = stmt.where(Visit.clinic_id == clinic_id)
    out = paginate(db.session, stmt, lambda v: v)
    rows = out["items"]
    recs = {r.visit_id: r for r in db.session.execute(select(GenericVisitRecord).where(
        GenericVisitRecord.visit_id.in_([v.id for v in rows] or [-1]))).scalars()}
    visits = visits_service.serialize_many(p.center_id, rows)
    for vj in visits:
        vj["record"] = record_json(recs.get(vj["id"]))
    out["items"] = visits
    return out


def summary_section(p, patient):
    if not p.has("medical_records.view"):
        return None
    clinics = [c for c, d in p.clinic_department.items() if p.department_env.get(d) == ENV]
    if not clinics:
        return None
    rows = db.session.execute(
        select(Visit, GenericVisitRecord).join(GenericVisitRecord, GenericVisitRecord.visit_id == Visit.id)
        .where(Visit.patient_id == patient.id, p.tenant(Visit), Visit.live(), Visit.clinic_id.in_(clinics),
               p.clinic_clause(Visit.clinic_id))
        .order_by(Visit.visit_at.desc()).limit(50)).all()
    if not rows:
        return None
    names = visits_service.clinic_names(p.center_id, [v.clinic_id for v, _ in rows])
    return {"items": [{"visit_id": v.id, "visit_at": iso(v.visit_at), "clinic_id": v.clinic_id,
                       "clinic_name": names.get(v.clinic_id), "author_name": r.author_name,
                       "chief_complaint": r.chief_complaint, "diagnosis": r.diagnosis,
                       "treatment_plan": r.treatment_plan, "medications": r.medications, "vitals": r.vitals or {}}
                      for v, r in rows]}
