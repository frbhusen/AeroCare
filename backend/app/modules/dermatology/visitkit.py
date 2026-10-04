"""Helpers for specialty detail records that hang off a core Visit one-to-one
(DermVisitRecord, OphthalmologyExam). Shared by the dermatology and ophthalmology modules.

Lifecycle:
  * create: either create a new visit + detail (owns_visit=True) or attach the detail to an
    existing visit of a clinic of the right environment (owns_visit=False).
  * delete: owns_visit -> the whole encounter (Visit) is staged; purge cascades the detail row.
            otherwise   -> only the detail row is staged.
    Files attached to the record/visit are removed (rows + stored bytes) on purge.
"""
import logging

import re

from sqlalchemy import event, func, or_, select

from backend.app.core.api import page_params

from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.storage import get_storage
from backend.app.core.timeutil import iso, local_day_bounds
from backend.app.core.validation import Date, Id, Str
from backend.app.extensions import db
from backend.app.models import Clinic, Patient, StoredFile, Visit
from backend.app.services import clinical, deletion

log = logging.getLogger("hc.visitkit")

VISIT_TYPES = ("consultation", "follow_up", "treatment", "procedure", "session", "examination", "other")
VISIT_STATUSES = ("open", "completed")


def purge_files(clause):
    """Delete StoredFile rows matching clause now; delete their bytes after the purge commits."""
    rows = db.session.execute(select(StoredFile).where(clause)).scalars().all()
    keys = [f.storage_key for f in rows]
    for f in rows:
        db.session.delete(f)
    # Flush now: the files -> visits FK must not be hit by a later visit delete in the same flush.
    db.session.flush()
    if not keys:
        return
    sess = db.session()

    @event.listens_for(sess, "after_commit", once=True)
    def _remove_bytes(_session):
        storage = get_storage()
        for k in keys:
            try:
                storage.delete(k)
            except Exception:  # pragma: no cover - filesystem failure only
                log.exception("failed to delete stored bytes of a purged record file")


def register_record_type(model, *, record_type, visit_type_key, owner_type):
    """Register the two deletable types for a visit-owned detail model."""

    def _record_files(rec):
        return (StoredFile.health_center_id == rec.health_center_id) & (StoredFile.owner_type == owner_type) & (
            StoredFile.owner_id == rec.id)

    def _before_record_purge(rec):
        purge_files(_record_files(rec))

    def _before_visit_purge(visit):
        ids = list(db.session.execute(select(model.id).where(model.visit_id == visit.id)).scalars())
        clause = (StoredFile.health_center_id == visit.health_center_id) & or_(
            StoredFile.visit_id == visit.id,
            (StoredFile.owner_type == owner_type) & StoredFile.owner_id.in_(ids or [-1]))
        purge_files(clause)

    deletion.register(record_type, model, before_purge=_before_record_purge)
    deletion.register(visit_type_key, Visit, before_purge=_before_visit_purge)


def resolve_visit(p, data, environment, default_visit_type):
    """Return (visit, owns_visit) for a new detail record. `data` is validated input with
    visit_id | (patient_id, clinic_id, visit_at, visit_type, title)."""
    if data.get("visit_id"):
        v = db.session.execute(select(Visit).where(Visit.id == data["visit_id"], p.tenant(Visit), Visit.live(),
                                                   p.clinic_clause(Visit.clinic_id))).scalar_one_or_none()
        if v is None:
            raise NotFound("Visit not found")
        clinical.require_environment(p, v.clinic_id, environment)
        p.require("medical_records.create", clinic_id=v.clinic_id)
        if data.get("patient_id") and data["patient_id"] != v.patient_id:
            raise ValidationError("Invalid input", details={"patient_id": "does not match the visit"})
        if data.get("clinic_id") and data["clinic_id"] != v.clinic_id:
            raise ValidationError("Invalid input", details={"clinic_id": "does not match the visit"})
        return v, False
    errors = {k: "is required" for k in ("patient_id", "clinic_id") if not data.get(k)}
    if errors:
        raise ValidationError("Invalid input", details=errors)
    clinical.require_environment(p, data["clinic_id"], environment)
    v = clinical.create_visit(p, patient_id=data["patient_id"], clinic_id=data["clinic_id"],
                              visit_type=data.get("visit_type") or default_visit_type, visit_at=data.get("visit_at"),
                              title=data.get("title"), status=data.get("status") or "open",
                              environments=[environment])
    return v, True


def scoped_record_stmt(p, model):
    """SELECT (record, visit, clinic name) limited to the principal's clinics, live rows only."""
    return (select(model, Visit, Clinic.name)
            .join(Visit, (Visit.id == model.visit_id) & (Visit.health_center_id == model.health_center_id))
            .join(Clinic, (Clinic.id == model.clinic_id) & (Clinic.health_center_id == model.health_center_id))
            .where(p.tenant(model), model.live(), Visit.live(),
                   model.clinic_id.in_(sorted(p.clinic_ids) or [-1])))


def get_record(p, model, record_id, perm="medical_records.view", label="Record"):
    row = db.session.execute(scoped_record_stmt(p, model).where(model.id == record_id)).first()
    if row is None:
        raise NotFound(f"{label} not found")
    rec, visit, clinic_name = row
    if perm:
        p.require(perm, clinic_id=rec.clinic_id)
    return rec, visit, clinic_name


def list_for_patient(p, model, patient_id, environment, clinic_id=None):
    clinical.get_patient(p, patient_id, perm="medical_records.view")
    stmt = scoped_record_stmt(p, model).where(model.patient_id == patient_id)
    if clinic_id:
        clinical.require_environment(p, clinic_id, environment)
        stmt = stmt.where(model.clinic_id == clinic_id)
    return stmt.order_by(Visit.visit_at.desc(), model.id.desc())


LIST_ARGS = {"department_id": Id(), "clinic_id": Id(), "q": Str(max_len=100), "date_from": Date(), "date_to": Date()}


def patient_json(pid, name, code):
    return {"id": pid, "full_name": name, "display_code": clinical.format_patient_code(code)}


def search_patients(stmt, q):
    """Filter a statement already joined to Patient by name / phone / PAT code."""
    q = (q or "").strip()
    if not q:
        return stmt
    digits = re.sub(r"\D", "", q)
    conds = [Patient.search_name.contains(clinical.normalize_name(q), autoescape=True)]
    if digits and (q.upper().startswith("PAT") or q.isdigit()):
        conds.append(Patient.code == int(digits[:9]))
    if len(digits) >= 3:
        conds.append(Patient.phone_digits.contains(digits, autoescape=True))
    return stmt.where(or_(*conds))


def scope_filters(p, stmt, model, environment, args, date_col):
    if args.get("department_id"):
        p.require(department_id=args["department_id"])
        stmt = stmt.where(model.department_id == args["department_id"])
    if args.get("clinic_id"):
        clinical.require_environment(p, args["clinic_id"], environment)
        stmt = stmt.where(model.clinic_id == args["clinic_id"])
    if date_col is None:
        return search_patients(stmt, args.get("q"))
    if args.get("date_from"):
        stmt = stmt.where(date_col >= local_day_bounds(args["date_from"])[0])
    if args.get("date_to"):
        stmt = stmt.where(date_col < local_day_bounds(args["date_to"])[1])
    return search_patients(stmt, args.get("q"))


def department_list_stmt(p, model, environment, args):
    """Visit-owned records across the caller's clinics (optionally one department/clinic), with patient."""
    p.require("medical_records.view")
    stmt = (scoped_record_stmt(p, model).add_columns(Patient.id, Patient.full_name, Patient.code)
            .join(Patient, (Patient.id == model.patient_id) & (Patient.health_center_id == model.health_center_id))
            .where(Patient.live()))
    stmt = scope_filters(p, stmt, model, environment, args, Visit.visit_at)
    return stmt.order_by(Visit.visit_at.desc(), model.id.desc())


def paginate_rows(stmt, default_per_page=25):
    """Like core.api.paginate but keeps multi-entity rows (record, visit, clinic name)."""
    page, per_page = page_params(default_per_page)
    rows = db.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    total = db.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    return {"items": rows, "page": page, "per_page": per_page, "total": total}


def apply_visit_fields(visit, data):
    for k in ("visit_at", "visit_type", "title", "status"):
        if k in data and (data[k] is not None or k == "title"):
            setattr(visit, k, data[k])


def stage_delete(p, rec, visit, *, record_type, visit_type_key, label):
    p.require("medical_records.delete", clinic_id=rec.clinic_id)
    if rec.owns_visit:
        return deletion.stage(p, visit, visit_type_key, label)
    return deletion.stage(p, rec, record_type, label)


def visit_json(visit, clinic_name=None):
    return {"visit_id": visit.id, "visit_at": iso(visit.visit_at), "visit_type": visit.visit_type,
            "visit_status": visit.status, "title": visit.title, "clinic_name": clinic_name}


def author_json(rec):
    return {"author_user_id": rec.author_user_id, "author_name": rec.author_name, "author_role": rec.author_role,
            "created_at": iso(rec.created_at), "updated_at": iso(rec.updated_at), "version": rec.version}
