"""Visits (encounters) service. Ownership boundary is the clinic: every query is clinic-scoped.

Specialty modules create visits through `services.clinical.create_visit` and attach their own
rows to `visits.id`; this module provides the shared list/get/edit/complete/delete endpoints.
"""
from sqlalchemy import select

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import ValidationError
from backend.app.core.timeutil import iso, local_day_bounds
from backend.app.core.validation import Date, DateTime, Enum, Id, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Patient, StoredFile, Visit
from backend.app.models.clinical import VISIT_TYPES
from backend.app.services import deletion
from backend.app.services.clinical import create_visit, get_patient, get_visit

from .helpers import clinic_names, department_info

VISIT_STATUSES = ("open", "completed")


def _before_visit_purge(visit):
    """Runs in the purger before the visit row is hard-deleted.

    * Files attached to the visit are removed with it: they are detached (visit_id=NULL), hidden
      and staged as already-expired 'file' deletions, so the purger deletes rows + bytes on its
      next pass.
    * Prescriptions keep existing but lose the visit reference.
    Both are done explicitly because the core composite FKs `(health_center_id, visit_id)` use
    ON DELETE SET NULL, which would also null `health_center_id` (NOT NULL) and fail the purge.
    """
    import secrets
    from sqlalchemy import update as sa_update
    from backend.app.core.timeutil import utcnow
    from backend.app.models import DeletionStage, Prescription
    now = utcnow()
    rows = db.session.execute(select(StoredFile).where(StoredFile.visit_id == visit.id)).scalars().all()
    for f in rows:
        f.visit_id = None
        if f.pending_delete_until is None:
            f.pending_delete_until = now
            db.session.add(DeletionStage(health_center_id=f.health_center_id, token=secrets.token_urlsafe(24),
                                         entity_type="file", entity_id=f.id, label=f.display_name[:255],
                                         user_id=visit.author_user_id or 0, expires_at=now))
    db.session.execute(sa_update(Prescription).where(Prescription.visit_id == visit.id).values(visit_id=None))
    db.session.flush()


deletion.register("visit", Visit, before_purge=_before_visit_purge)


def visit_json(v, names=None, depts=None, patients=None):
    names = names if names is not None else clinic_names(v.health_center_id, [v.clinic_id])
    depts = depts if depts is not None else department_info(v.health_center_id, [v.department_id])
    d = depts.get(v.department_id, {})
    out = {"id": v.id, "patient_id": v.patient_id, "department_id": v.department_id,
           "department_name": d.get("name"), "environment": d.get("environment"), "clinic_id": v.clinic_id,
           "clinic_name": names.get(v.clinic_id), "appointment_id": v.appointment_id, "visit_at": iso(v.visit_at),
           "visit_type": v.visit_type, "status": v.status, "title": v.title, "notes": v.notes,
           "author_user_id": v.author_user_id, "author_name": v.author_name, "author_role": v.author_role,
           "created_at": iso(v.created_at), "updated_at": iso(v.updated_at), "version": v.version}
    if patients is not None:
        pt = patients.get(v.patient_id)
        out["patient"] = {"id": pt.id, "display_code": pt.display_code, "full_name": pt.full_name} if pt else None
    return out


def serialize_many(center_id, visits, with_patient=False):
    names = clinic_names(center_id, [v.clinic_id for v in visits])
    depts = department_info(center_id, [v.department_id for v in visits])
    patients = None
    if with_patient:
        ids = sorted({v.patient_id for v in visits}) or [-1]
        patients = {pt.id: pt for pt in db.session.execute(select(Patient).where(Patient.id.in_(ids))).scalars()}
    return [visit_json(v, names, depts, patients) for v in visits]


def list_visits(p, args, patient_id=None):
    p.require("medical_records.view")
    a = validate(args, {"patient_id": Id(), "clinic_id": Id(), "department_id": Id(),
                        "status": Enum(VISIT_STATUSES), "visit_type": Enum(VISIT_TYPES),
                        "date_from": Date(), "date_to": Date()})
    patient_id = patient_id or a.get("patient_id")
    stmt = select(Visit).where(p.tenant(Visit), Visit.live(), p.clinic_clause(Visit.clinic_id))
    if patient_id:
        get_patient(p, patient_id)
        stmt = stmt.where(Visit.patient_id == patient_id)
    else:
        stmt = stmt.where(Visit.patient_id.in_(select(Patient.id).where(p.tenant(Patient), Patient.live())))
    if a.get("clinic_id"):
        p.require(clinic_id=a["clinic_id"])
        stmt = stmt.where(Visit.clinic_id == a["clinic_id"])
    if a.get("department_id"):
        p.require(department_id=a["department_id"])
        stmt = stmt.where(Visit.department_id == a["department_id"])
    if a.get("status"):
        stmt = stmt.where(Visit.status == a["status"])
    if a.get("visit_type"):
        stmt = stmt.where(Visit.visit_type == a["visit_type"])
    if a.get("date_from"):
        stmt = stmt.where(Visit.visit_at >= local_day_bounds(a["date_from"])[0])
    if a.get("date_to"):
        stmt = stmt.where(Visit.visit_at < local_day_bounds(a["date_to"])[1])
    stmt = stmt.order_by(Visit.visit_at.desc(), Visit.id.desc())
    out = paginate(db.session, stmt, lambda v: v)
    out["items"] = serialize_many(p.center_id, out["items"], with_patient=not patient_id)
    return out


VISIT_SCHEMA = {
    "visit_type": Enum(VISIT_TYPES),
    "visit_at": DateTime(),
    "title": Str(max_len=200),
    "notes": Text(max_len=20000),
    "appointment_id": Id(),
}


def create(p, body, environments=None, commit=True):
    data = validate(body, {"patient_id": Id(required=True), "clinic_id": Id(required=True), **VISIT_SCHEMA})
    # Clinic scope + permission first (404 / 403), then patient visibility.
    p.require("medical_records.create", clinic_id=data["clinic_id"])
    get_patient(p, data["patient_id"])
    v = create_visit(p, patient_id=data["patient_id"], clinic_id=data["clinic_id"],
                     visit_type=data.get("visit_type") or "consultation", visit_at=data.get("visit_at"),
                     title=data.get("title"), notes=data.get("notes"), appointment_id=data.get("appointment_id"),
                     environments=environments)
    if commit:
        db.session.commit()
    return v


def update(p, visit_id, body):
    v = get_visit(p, visit_id, perm="medical_records.edit")
    data = validate(body, {"version": Id(required=True), **VISIT_SCHEMA}, partial=True)
    check_version(v, data.pop("version", None))
    if "visit_type" in data and data["visit_type"] is None:
        raise ValidationError("Invalid input", details={"visit_type": "is required"})
    if "visit_at" in data and data["visit_at"] is None:
        raise ValidationError("Invalid input", details={"visit_at": "is required"})
    for k, val in data.items():
        setattr(v, k, val)
    db.session.commit()
    return v


def set_status(p, visit_id, body, status):
    v = get_visit(p, visit_id, perm="medical_records.edit")
    data = validate(body, {"version": Id(required=True)})
    check_version(v, data["version"])
    v.status = status
    db.session.commit()
    return v


def delete(p, visit_id):
    v = get_visit(p, visit_id, perm="medical_records.delete")
    names = clinic_names(p.center_id, [v.clinic_id])
    return deletion.stage(p, v, "visit", f"{v.visit_type} {iso(v.visit_at)[:10]} {names.get(v.clinic_id, '')}")
