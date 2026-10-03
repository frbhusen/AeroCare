"""Dentistry business logic: scope helpers, odontogram, timeline, summary, meta.
Treatments/plans live in records.py, X-rays in xrays.py.

Scope: every dental record is owned by a clinic whose department has environment 'dentistry'.
Lists are restricted to the principal's accessible dental clinics (doctor = own clinic, department
manager / department receptionist = the dentistry department's clinics, center-wide = all).
Out of scope => 404; in scope without permission => 403.
"""
from sqlalchemy import func, select

from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.timeutil import iso
from backend.app.core.validation import Enum, Id, Int, List, Obj, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Patient, User
from backend.app.services import clinical

from . import constants as C
from .models import OdontogramEntry, OdontogramTooth

ENV = "dentistry"


# ---------------------------------------------------------------------------- scope helpers
def dental_clinic_ids(p):
    return sorted(c for c, d in p.clinic_department.items() if p.department_env.get(d) == ENV)


def resolve_clinic(p, clinic_id):
    """Return (clinic_id, department_id) for an accessible dental clinic. When clinic_id is omitted
    and the principal has exactly one dental clinic, that clinic is used."""
    if clinic_id is None:
        ids = dental_clinic_ids(p)
        if len(ids) != 1:
            raise ValidationError("Choose a dental clinic.", details={"clinic_id": "is required"})
        clinic_id = ids[0]
    dept = clinical.require_environment(p, clinic_id, ENV)  # 404 if out of scope, 422 if not dental
    return clinic_id, dept


def clinic_filter(p, column, clinic_id=None):
    """WHERE clause limiting `column` to accessible dental clinics (optionally one clinic)."""
    if clinic_id is not None:
        resolve_clinic(p, clinic_id)
        return column == clinic_id
    ids = dental_clinic_ids(p)
    return column.in_(ids or [-1])


def visible_patient(p, patient_id):
    """Patient visible to the principal (404 otherwise)."""
    return clinical.get_patient(p, patient_id, perm=None)


def writable_patient(p, patient_id, clinic_id, department_id):
    """A live patient of this center; links it to the clinic (same rule as clinical.create_visit)."""
    patient = db.session.execute(select(Patient).where(Patient.id == patient_id, p.tenant(Patient), Patient.live())
                                 ).scalar_one_or_none()
    if patient is None:
        raise NotFound("Patient not found")
    clinical.link_patient_to_clinic(p.center_id, patient.id, clinic_id, department_id)
    return patient


def resolve_visit(p, visit_id, clinic_id, patient_id):
    if visit_id is None:
        return None
    v = clinical.get_visit(p, visit_id, perm=None)
    if v.clinic_id != clinic_id or v.patient_id != patient_id:
        raise ValidationError("The visit belongs to another clinic or patient.",
                              details={"visit_id": "must be a visit of this patient in this clinic"})
    return v


def check_tooth(mode, number, field="tooth_number"):
    if number is None:
        return
    lo, hi = C.TOOTH_RANGES[mode]
    if not lo <= number <= hi:
        raise ValidationError("Invalid tooth number.", details={field: f"must be {lo}-{hi} for {mode} teeth"})


def clinic_names(p, ids):
    if not ids:
        return {}
    return dict(db.session.execute(select(Clinic.id, Clinic.name).where(p.tenant(Clinic), Clinic.id.in_(list(ids))))
                .all())


# ---------------------------------------------------------------------------- meta
def meta(p):
    ids = dental_clinic_ids(p)
    names = clinic_names(p, ids)
    return {
        "numbering": C.numbering(),
        "tooth_modes": list(C.TOOTH_MODES),
        "conditions": list(C.CONDITIONS),
        "chart_actions": list(C.CHART_ACTIONS),
        "surfaces": list(C.SURFACES),
        "procedures": list(C.PROCEDURES),
        "statuses": list(C.STATUSES),
        "priorities": list(C.PRIORITIES),
        "xray_types": list(C.XRAY_TYPES),
        "xray_mime_types": sorted(C.XRAY_MIMES),
        "clinics": [{"id": c, "name": names.get(c), "department_id": p.clinic_department[c]} for c in ids],
        "permissions": {k: p.has(f"medical_records.{k}") for k in ("view", "create", "edit", "delete")}
        | {"upload": p.has("files.upload")},
    }


# ---------------------------------------------------------------------------- odontogram
def tooth_json(t):
    return {
        "id": t.id, "clinic_id": t.clinic_id, "patient_id": t.patient_id, "tooth_mode": t.tooth_mode,
        "tooth_number": t.tooth_number, "label": C.tooth_label(t.tooth_mode, t.tooth_number),
        "condition": t.condition, "procedure": t.procedure, "notes": t.notes, "surfaces": t.surfaces or [],
        "created_by": t.author_name, "updated_by": t.updated_by_name or t.author_name,
        "created_at": iso(t.created_at), "updated_at": iso(t.updated_at), "version": t.version,
    }


def entry_json(e):
    return {
        "id": e.id, "tooth_id": e.tooth_id, "clinic_id": e.clinic_id, "patient_id": e.patient_id,
        "visit_id": e.visit_id, "tooth_mode": e.tooth_mode, "tooth_number": e.tooth_number,
        "label": C.tooth_label(e.tooth_mode, e.tooth_number), "action": e.action, "condition": e.condition,
        "procedure": e.procedure, "notes": e.notes, "surfaces": e.surfaces or [], "author_name": e.author_name,
        "author_role": e.author_role, "tooth_version": e.tooth_version, "created_at": iso(e.created_at),
    }


def get_chart(p, patient_id, clinic_id=None, mode=None):
    clinic_id, _ = resolve_clinic(p, clinic_id)
    p.require("medical_records.view", clinic_id=clinic_id)
    patient = visible_patient(p, patient_id)
    if mode is not None and mode not in C.TOOTH_MODES:
        raise ValidationError("Invalid tooth mode.", details={"mode": "must be permanent or primary"})
    stmt = select(OdontogramTooth).where(p.tenant(OdontogramTooth), OdontogramTooth.clinic_id == clinic_id,
                                         OdontogramTooth.patient_id == patient.id)
    if mode:
        stmt = stmt.where(OdontogramTooth.tooth_mode == mode)
    rows = db.session.execute(stmt.order_by(OdontogramTooth.tooth_mode, OdontogramTooth.tooth_number)).scalars()
    return {"patient_id": patient.id, "clinic_id": clinic_id, "teeth": [tooth_json(t) for t in rows],
            "can_edit": p.has("medical_records.edit")}


_TOOTH_SCHEMA = {
    "condition": Enum(list(C.CONDITIONS) + [C.CLEAR]),
    "procedure": Str(max_len=150),
    "notes": Text(max_len=5000),
    "surfaces": List(Enum(C.SURFACES), max_items=5),
    "version": Int(min_value=0),
}


def _apply_tooth(p, clinic_id, dept, patient_id, mode, number, data, visit_id):
    if mode not in C.TOOTH_MODES:
        raise ValidationError("Invalid tooth mode.", details={"tooth_mode": "must be permanent or primary"})
    check_tooth(mode, number)
    if not any(k in data for k in ("condition", "procedure", "notes", "surfaces")):
        raise ValidationError("Nothing to update.", details={"condition": "or procedure/notes/surfaces is required"})
    t = db.session.execute(select(OdontogramTooth).where(
        p.tenant(OdontogramTooth), OdontogramTooth.clinic_id == clinic_id, OdontogramTooth.patient_id == patient_id,
        OdontogramTooth.tooth_mode == mode, OdontogramTooth.tooth_number == number).with_for_update()
    ).scalar_one_or_none()
    created = t is None
    if created:
        if data.get("version") not in (None, 0):
            raise Conflict("This tooth has no saved state yet.", code="version_conflict",
                                  details={"current_version": 0})
        t = OdontogramTooth(health_center_id=p.center_id, department_id=dept, clinic_id=clinic_id,
                            patient_id=patient_id, tooth_mode=mode, tooth_number=number)
        t.set_author(p.user)
        db.session.add(t)
    else:
        check_version(t, data.get("version"))
    clear = data.get("condition") == C.CLEAR
    if clear:
        t.condition = t.procedure = t.notes = None
        t.surfaces = None
    else:
        for k in ("condition", "procedure", "notes"):
            if k in data:
                setattr(t, k, data[k])
        if "surfaces" in data:
            t.surfaces = sorted(set(data["surfaces"] or []), key=C.SURFACES.index) or None
    t.updated_by_user_id, t.updated_by_name = p.user.id, p.user.name
    db.session.flush()
    e = OdontogramEntry(health_center_id=p.center_id, tooth_id=t.id, department_id=dept, clinic_id=clinic_id,
                        patient_id=patient_id, visit_id=visit_id, tooth_mode=mode, tooth_number=number,
                        action="clear" if clear else "set", condition=t.condition, procedure=t.procedure,
                        notes=t.notes, surfaces=t.surfaces, tooth_version=t.version)
    e.set_author(p.user)
    db.session.add(e)
    return t, created


def _prepare_write(p, patient_id, clinic_id, visit_id):
    clinic_id, dept = resolve_clinic(p, clinic_id)
    p.require("medical_records.edit", clinic_id=clinic_id)
    patient = writable_patient(p, patient_id, clinic_id, dept)
    visit = resolve_visit(p, visit_id, clinic_id, patient.id)
    return clinic_id, dept, patient, visit


def update_tooth(p, patient_id, mode, number, body):
    head = validate(body, {"clinic_id": Id(), "visit_id": Id()})
    data = validate(body, _TOOTH_SCHEMA, partial=True)
    clinic_id, dept, patient, visit = _prepare_write(p, patient_id, head.get("clinic_id"), head.get("visit_id"))
    t, created = _apply_tooth(p, clinic_id, dept, patient.id, mode, number, data, visit.id if visit else None)
    db.session.commit()
    return tooth_json(t), created


def bulk_update(p, patient_id, body):
    head = validate(body, {"clinic_id": Id(), "visit_id": Id(),
                           "teeth": List(Obj({"tooth_mode": Enum(C.TOOTH_MODES, required=True),
                                              "tooth_number": Int(required=True)}), min_items=1, max_items=52,
                                         required=True)})
    clinic_id, dept, patient, visit = _prepare_write(p, patient_id, head.get("clinic_id"), head.get("visit_id"))
    seen, out = set(), []
    for i, raw in enumerate(body["teeth"]):
        key = (raw["tooth_mode"], int(raw["tooth_number"]))
        if key in seen:
            raise ValidationError("A tooth appears twice.", details={f"teeth[{i}]": "duplicate tooth"})
        seen.add(key)
        try:
            data = validate(raw, _TOOTH_SCHEMA, partial=True)
        except ValidationError as e:
            raise ValidationError("Invalid input", details={f"teeth[{i}]": e.details})
        t, _ = _apply_tooth(p, clinic_id, dept, patient.id, key[0], key[1], data, visit.id if visit else None)
        out.append(t)
    db.session.commit()
    return {"patient_id": patient.id, "clinic_id": clinic_id, "teeth": [tooth_json(t) for t in out]}


def tooth_history(p, patient_id, clinic_id=None, mode=None, number=None, limit=200):
    clinic_id, _ = resolve_clinic(p, clinic_id)
    p.require("medical_records.view", clinic_id=clinic_id)
    patient = visible_patient(p, patient_id)
    stmt = select(OdontogramEntry).where(p.tenant(OdontogramEntry), OdontogramEntry.clinic_id == clinic_id,
                                         OdontogramEntry.patient_id == patient.id)
    if mode:
        stmt = stmt.where(OdontogramEntry.tooth_mode == mode)
    if number:
        stmt = stmt.where(OdontogramEntry.tooth_number == number)
    rows = db.session.execute(stmt.order_by(OdontogramEntry.created_at.desc(), OdontogramEntry.id.desc())
                              .limit(limit)).scalars()
    return {"patient_id": patient.id, "clinic_id": clinic_id, "items": [entry_json(e) for e in rows]}


# ---------------------------------------------------------------------------- doctors
def eligible_doctor(p, user_id, clinic_id, department_id):
    u = db.session.execute(select(User).where(User.id == user_id, User.health_center_id == p.center_id,
                                              User.status == "active")).scalar_one_or_none()
    if u is None or not ((u.role == "doctor" and u.clinic_id == clinic_id)
                         or (u.role == "department_manager" and u.department_id == department_id)):
        raise ValidationError("Choose a doctor of this clinic.", details={"doctor_user_id": "is not a doctor here"})
    return u


def default_doctor(p, clinic_id, department_id):
    u = p.user
    if (u.role == "doctor" and u.clinic_id == clinic_id) or (u.role == "department_manager"
                                                             and u.department_id == department_id):
        return u
    return None


def clinic_doctors(p, clinic_id=None):
    clinic_id, dept = resolve_clinic(p, clinic_id)
    p.require("medical_records.view", clinic_id=clinic_id)
    rows = db.session.execute(select(User.id, User.name, User.role).where(
        User.health_center_id == p.center_id, User.status == "active",
        ((User.role == "doctor") & (User.clinic_id == clinic_id))
        | ((User.role == "department_manager") & (User.department_id == dept))).order_by(User.name)).all()
    return {"clinic_id": clinic_id, "items": [{"id": i, "name": n, "role": r} for i, n, r in rows]}


# ---------------------------------------------------------------------------- summary
def dental_summary(p, patient):
    """Dental section of the patient summary, built only from clinics the principal can access.
    Returns None when the principal has no dental clinic or lacks medical_records.view."""
    from .models import Treatment, TreatmentPlan, XRay
    ids = dental_clinic_ids(p)
    if not ids or not p.has("medical_records.view"):
        return None
    pid = patient.id if hasattr(patient, "id") else int(patient)

    def scoped(model):
        return (p.tenant(model), model.patient_id == pid, model.clinic_id.in_(ids))

    by_status = dict(db.session.execute(select(Treatment.status, func.count()).where(
        *scoped(Treatment), Treatment.live()).group_by(Treatment.status)).all())
    open_plans = db.session.execute(select(func.count()).select_from(TreatmentPlan).where(
        *scoped(TreatmentPlan), TreatmentPlan.live(),
        TreatmentPlan.status.notin_(("completed", "cancelled")))).scalar_one()
    xrays = db.session.execute(select(func.count()).select_from(XRay).where(*scoped(XRay), XRay.live())
                               ).scalar_one()
    charted = db.session.execute(select(func.count()).select_from(OdontogramTooth).where(
        *scoped(OdontogramTooth), OdontogramTooth.condition.isnot(None),
        OdontogramTooth.condition != "healthy")).scalar_one()
    last = db.session.execute(select(func.max(Treatment.date)).where(*scoped(Treatment), Treatment.live())
                              ).scalar_one()
    if not (by_status or open_plans or xrays or charted):
        return None
    return {"section": "dentistry", "title": "Dentistry", "treatments_by_status": by_status,
            "treatments_total": sum(by_status.values()), "open_plan_items": open_plans, "xrays": xrays,
            "charted_teeth": charted, "last_treatment_date": iso(last)}


try:  # Complete Patient Summary section (patients module, spec §22)
    from backend.app.modules.patients.summary import register_summary_provider
except ImportError:  # pragma: no cover - patients module absent
    register_summary_provider = None
if register_summary_provider:
    register_summary_provider("dentistry", dental_summary, order=200)
