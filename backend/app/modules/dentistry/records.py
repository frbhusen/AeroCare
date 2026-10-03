"""Dental treatments and treatment-plan items (AeroDent field sets, re-keyed to clinic ownership)."""
from sqlalchemy import select

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.timeutil import iso, local_today, utcnow
from backend.app.core.validation import Bool, Date, Enum, Id, Int, Money, Str, Text, query_args, validate
from backend.app.extensions import db
from backend.app.services import clinical, deletion

from . import constants as C
from .models import Treatment, TreatmentPlan
from .service import (check_tooth, clinic_filter, default_doctor, eligible_doctor, resolve_clinic, resolve_visit,
                      visible_patient, writable_patient)

deletion.register("dental_treatment", Treatment)
deletion.register("dental_treatment_plan", TreatmentPlan)

_COMMON = {
    "tooth_mode": Enum(C.TOOTH_MODES),
    "tooth_number": Int(min_value=1, max_value=32),
    "procedure": Str(max_len=150),
    "fee": Money(max_value=99999999.99),
    "status": Enum(C.STATUSES),
    "doctor_user_id": Id(),
}
TREATMENT_SCHEMA = {**_COMMON, "description": Text(max_len=5000), "date": Date(), "visit_id": Id()}
PLAN_SCHEMA = {**_COMMON, "diagnosis": Text(max_len=5000), "notes": Text(max_len=5000),
               "priority": Enum(C.PRIORITIES)}
_CREATE_HEAD = {"clinic_id": Id(), "patient_id": Id(required=True), "create_visit": Bool()}


def _base_json(o):
    return {
        "id": o.id, "clinic_id": o.clinic_id, "department_id": o.department_id, "patient_id": o.patient_id,
        "tooth_mode": o.tooth_mode, "tooth_number": o.tooth_number,
        "tooth_label": C.tooth_label(o.tooth_mode, o.tooth_number) if o.tooth_number else None,
        "procedure": o.procedure, "fee": f"{o.fee:.2f}", "status": o.status, "doctor_user_id": o.doctor_user_id,
        "doctor_name": o.doctor_name, "author_name": o.author_name, "author_role": o.author_role,
        "created_at": iso(o.created_at), "updated_at": iso(o.updated_at), "version": o.version,
    }


def treatment_json(t):
    return _base_json(t) | {"visit_id": t.visit_id, "plan_id": t.plan_id, "description": t.description,
                            "date": iso(t.date)}


def plan_json(pl):
    return _base_json(pl) | {"diagnosis": pl.diagnosis, "notes": pl.notes, "priority": pl.priority,
                             "converted_treatment_id": pl.converted_treatment_id,
                             "converted_at": iso(pl.converted_at)}


def _get(p, model, obj_id, label):
    o = db.session.execute(select(model).where(model.id == obj_id, p.tenant(model), model.live(),
                                               clinic_filter(p, model.clinic_id))).scalar_one_or_none()
    if o is None:
        raise NotFound(f"{label} not found")
    return o


def _set_doctor(p, o, data, creating):
    if "doctor_user_id" in data:
        if data["doctor_user_id"] is None:
            o.doctor_user_id, o.doctor_name = None, None
        elif data["doctor_user_id"] != o.doctor_user_id:
            u = eligible_doctor(p, data["doctor_user_id"], o.clinic_id, o.department_id)
            o.doctor_user_id, o.doctor_name = u.id, u.name
    elif creating:
        u = default_doctor(p, o.clinic_id, o.department_id)
        if u is not None:
            o.doctor_user_id, o.doctor_name = u.id, u.name


def _assign(o, data, fields):
    for k in fields:
        if k in data:
            setattr(o, k, data[k])
    if o.tooth_mode is None:
        o.tooth_mode = "permanent"
    check_tooth(o.tooth_mode, o.tooth_number)


def _session_visit(p, o, title):
    v = clinical.create_visit(p, patient_id=o.patient_id, clinic_id=o.clinic_id, visit_type="treatment",
                              title=(title or "Dental treatment")[:200], environments="dentistry")
    return v.id


def _list(p, model, serialize, extra_schema, order):
    args = query_args({"clinic_id": Id(), "patient_id": Id(), "status": Enum(C.STATUSES), "doctor_user_id": Id(),
                       **extra_schema})
    p.require("medical_records.view")
    stmt = select(model).where(p.tenant(model), model.live(), clinic_filter(p, model.clinic_id, args.get("clinic_id")))
    if args.get("patient_id"):
        visible_patient(p, args["patient_id"])
        stmt = stmt.where(model.patient_id == args["patient_id"])
    for k in ("status", "doctor_user_id"):
        if args.get(k):
            stmt = stmt.where(getattr(model, k) == args[k])
    return args, stmt.order_by(*order)


# ---------------------------------------------------------------------------- treatments
def list_treatments(p):
    args, stmt = _list(p, Treatment, treatment_json, {"date_from": Date(), "date_to": Date()},
                       (Treatment.date.desc(), Treatment.id.desc()))
    if args.get("date_from"):
        stmt = stmt.where(Treatment.date >= args["date_from"])
    if args.get("date_to"):
        stmt = stmt.where(Treatment.date <= args["date_to"])
    return paginate(db.session, stmt, treatment_json)


def get_treatment(p, tid):
    t = _get(p, Treatment, tid, "Treatment")
    p.require("medical_records.view")
    return treatment_json(t)


def _new_record(p, model, body, schema, perm="medical_records.create"):
    head = validate(body, _CREATE_HEAD)
    data = validate(body, schema)
    clinic_id, dept = resolve_clinic(p, head.get("clinic_id"))
    p.require(perm, clinic_id=clinic_id)
    patient = writable_patient(p, head["patient_id"], clinic_id, dept)
    o = model(health_center_id=p.center_id, clinic_id=clinic_id, department_id=dept, patient_id=patient.id)
    o.set_author(p.user)
    return o, head, data


def create_treatment(p, body):
    t, head, data = _new_record(p, Treatment, body, TREATMENT_SCHEMA)
    if not (data.get("procedure") or data.get("description")):
        raise ValidationError("Enter the procedure.", details={"procedure": "is required"})
    _assign(t, data, ("tooth_mode", "tooth_number", "procedure", "description", "fee", "status", "date"))
    t.status = t.status or "planned"
    t.date = t.date or local_today()
    t.fee = t.fee if t.fee is not None else 0
    _set_doctor(p, t, data, creating=True)
    if data.get("visit_id"):
        t.visit_id = resolve_visit(p, data["visit_id"], t.clinic_id, t.patient_id).id
    elif head.get("create_visit"):
        t.visit_id = _session_visit(p, t, t.procedure or t.description)
    db.session.add(t)
    db.session.commit()
    return treatment_json(t)


def update_treatment(p, tid, body):
    t = _get(p, Treatment, tid, "Treatment")
    p.require("medical_records.edit", clinic_id=t.clinic_id)
    data = validate(body, {**TREATMENT_SCHEMA, "create_visit": Bool(), "version": Int()}, partial=True)
    check_version(t, data.get("version"))
    for k in ("status", "date", "fee", "tooth_mode"):
        if k in data and data[k] is None:
            raise ValidationError("Invalid input", details={k: "is required"})
    _assign(t, data, ("tooth_mode", "tooth_number", "procedure", "description", "fee", "status", "date"))
    _set_doctor(p, t, data, creating=False)
    if "visit_id" in data:
        t.visit_id = resolve_visit(p, data["visit_id"], t.clinic_id, t.patient_id).id if data["visit_id"] else None
    elif data.get("create_visit") and t.visit_id is None:
        t.visit_id = _session_visit(p, t, t.procedure or t.description)
    db.session.commit()
    return treatment_json(t)


def delete_treatment(p, tid):
    t = _get(p, Treatment, tid, "Treatment")
    p.require("medical_records.delete", clinic_id=t.clinic_id)
    return deletion.stage(p, t, "dental_treatment", label=f"Treatment {t.procedure or t.description or t.id}"[:255])


# ---------------------------------------------------------------------------- plans
def list_plans(p):
    args, stmt = _list(p, TreatmentPlan, plan_json, {"priority": Enum(C.PRIORITIES)}, (TreatmentPlan.id.desc(),))
    if args.get("priority"):
        stmt = stmt.where(TreatmentPlan.priority == args["priority"])
    return paginate(db.session, stmt, plan_json)


def get_plan(p, pid):
    pl = _get(p, TreatmentPlan, pid, "Treatment plan")
    p.require("medical_records.view")
    return plan_json(pl)


def create_plan(p, body):
    pl, _, data = _new_record(p, TreatmentPlan, body, PLAN_SCHEMA)
    _assign(pl, data, ("tooth_mode", "tooth_number", "procedure", "diagnosis", "notes", "fee", "status", "priority"))
    pl.status = pl.status or "planned"
    pl.priority = pl.priority or "medium"
    pl.fee = pl.fee if pl.fee is not None else 0
    _set_doctor(p, pl, data, creating=True)
    db.session.add(pl)
    db.session.commit()
    return plan_json(pl)


def update_plan(p, pid, body):
    pl = _get(p, TreatmentPlan, pid, "Treatment plan")
    p.require("medical_records.edit", clinic_id=pl.clinic_id)
    data = validate(body, {**PLAN_SCHEMA, "version": Int()}, partial=True)
    check_version(pl, data.get("version"))
    for k in ("status", "priority", "fee", "tooth_mode"):
        if k in data and data[k] is None:
            raise ValidationError("Invalid input", details={k: "is required"})
    _assign(pl, data, ("tooth_mode", "tooth_number", "procedure", "diagnosis", "notes", "fee", "status", "priority"))
    _set_doctor(p, pl, data, creating=False)
    db.session.commit()
    return plan_json(pl)


def delete_plan(p, pid):
    pl = _get(p, TreatmentPlan, pid, "Treatment plan")
    p.require("medical_records.delete", clinic_id=pl.clinic_id)
    return deletion.stage(p, pl, "dental_treatment_plan", label=f"Plan {pl.procedure or pl.id}"[:255])


def convert_plan(p, pid, body):
    """Create a treatment from a plan item (copies tooth, procedure, fee, doctor; description =
    diagnosis/notes). The plan keeps a link; a planned item becomes 'accepted'."""
    pl = _get(p, TreatmentPlan, pid, "Treatment plan")
    p.require("medical_records.create", clinic_id=pl.clinic_id)
    data = validate(body, {"version": Int(), "date": Date(), "status": Enum(C.STATUSES), "visit_id": Id(),
                           "create_visit": Bool(), "description": Text(max_len=5000)})
    check_version(pl, data.get("version"))
    if pl.converted_treatment_id is not None:
        exists = db.session.execute(select(Treatment.id).where(Treatment.id == pl.converted_treatment_id,
                                                               p.tenant(Treatment))).first()
        if exists:
            raise Conflict("This plan item was already converted to a treatment.", code="already_converted",
                           details={"treatment_id": pl.converted_treatment_id})
    if pl.status == "cancelled":
        raise ValidationError("A cancelled plan item cannot be converted.", code="plan_cancelled")
    t = Treatment(health_center_id=p.center_id, clinic_id=pl.clinic_id, department_id=pl.department_id,
                  patient_id=pl.patient_id, plan_id=pl.id, tooth_mode=pl.tooth_mode, tooth_number=pl.tooth_number,
                  procedure=pl.procedure, fee=pl.fee, status=data.get("status") or "planned",
                  date=data.get("date") or local_today(), doctor_user_id=pl.doctor_user_id,
                  doctor_name=pl.doctor_name,
                  description=data.get("description") or "\n".join(x for x in (pl.diagnosis, pl.notes) if x) or None)
    t.set_author(p.user)
    if data.get("visit_id"):
        t.visit_id = resolve_visit(p, data["visit_id"], t.clinic_id, t.patient_id).id
    elif data.get("create_visit"):
        t.visit_id = _session_visit(p, t, t.procedure)
    db.session.add(t)
    db.session.flush()
    pl.converted_treatment_id, pl.converted_at = t.id, utcnow()
    if pl.status == "planned":
        pl.status = "accepted"
    db.session.commit()
    return {"treatment": treatment_json(t), "plan": plan_json(pl)}


