"""Radiology studies: scope, serialization, lists, request create/edit/delete.
Workflow transitions live in workflow.py.

Access levels for one study (`access_level`):
  "radiology"  `radiology.process` + target radiology department/clinic in scope -> full workflow.
  "requester"  requesting clinic in scope (+ radiology.request or medical_records.view); managers of
               the requesting department / center-wide principals fall here too. Report and images
               are visible once finalized.
  "shared"     study finalized + medical_records.view + an explicit study share to one of the
               principal's clinics/departments or to the user -> read-only report + images.
Anything else -> 404. Radiology staff see only the patient's basic identity, never other
specialty records.
"""
from sqlalchemy import and_, exists, false, or_, select, true

from backend.app.authz.principal import current_principal
from backend.app.core.api import check_version, page_params
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import DateTime, Enum, Id, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Department, Patient, StoredFile
from backend.app.services import deletion
from backend.app.services import files as files_svc
from backend.app.services.clinical import format_patient_code, get_patient, get_visit, link_patient_to_clinic

from backend.app.modules.laboratory import notify as N
from backend.app.modules.laboratory.routing import requesting_clinic_for, resolve_target
from .models import EXAM_TYPES, PRIORITIES, STATUSES, RadiologyStudy, RadiologyStudyShare

# Deletion is only allowed while "requested" (before any image can be uploaded).
deletion.register("radiology_study", RadiologyStudy)

ACTIVE = ("requested", "scheduled", "in_progress", "reported")


# ---- scope ------------------------------------------------------------------
def radiology_side(p, s):
    if not p.has("radiology.process"):
        return False
    if p.center_wide or p.can_department(s.radiology_department_id):
        return True
    if s.radiology_clinic_id is not None:
        return p.can_clinic(s.radiology_clinic_id)
    return any(p.clinic_department.get(c) == s.radiology_department_id for c in p.clinic_ids)


def requester_side(p, s):
    return p.can_clinic(s.requesting_clinic_id) and (p.has("radiology.request") or p.has("medical_records.view"))


def _share_clause(p):
    clinics = sorted(p.clinic_ids) or [-1]
    depts = sorted(p.visible_department_ids) or [-1]
    return exists().where(RadiologyStudyShare.study_id == RadiologyStudy.id,
                          RadiologyStudyShare.health_center_id == RadiologyStudy.health_center_id,
                          or_(RadiologyStudyShare.target_clinic_id.in_(clinics),
                              RadiologyStudyShare.target_department_id.in_(depts),
                              RadiologyStudyShare.target_user_id == p.user.id))


def shared_clause(p):
    if not p.has("medical_records.view"):
        return false()
    return and_(RadiologyStudy.status == "finalized", _share_clause(p))


def access_level(p, s):
    if radiology_side(p, s):
        return "radiology"
    if requester_side(p, s):
        return "requester"
    if s.status == "finalized" and p.has("medical_records.view"):
        hit = db.session.execute(select(RadiologyStudy.id).where(RadiologyStudy.id == s.id, _share_clause(p))).first()
        if hit:
            return "shared"
    return None


def radiology_side_clause(p):
    if not p.has("radiology.process"):
        return false()
    if p.center_wide:
        return true()
    managed = sorted(d for d in p.managed_department_ids if p.department_env.get(d) == "radiology")
    clinics = sorted(c for c in p.clinic_ids if p.department_env.get(p.clinic_department.get(c)) == "radiology")
    depts = sorted({p.clinic_department[c] for c in clinics})
    return or_(RadiologyStudy.radiology_department_id.in_(managed or [-1]),
               RadiologyStudy.radiology_clinic_id.in_(clinics or [-1]),
               and_(RadiologyStudy.radiology_clinic_id.is_(None),
                    RadiologyStudy.radiology_department_id.in_(depts or [-1])))


def requester_clause(p):
    if not (p.has("radiology.request") or p.has("medical_records.view")):
        return false()
    return p.clinic_clause(RadiologyStudy.requesting_clinic_id)


def load(p, sid, for_update=False):
    stmt = select(RadiologyStudy).where(RadiologyStudy.id == sid, p.tenant(RadiologyStudy), RadiologyStudy.live())
    if for_update:
        stmt = stmt.with_for_update()
    s = db.session.execute(stmt).scalar_one_or_none()
    level = access_level(p, s) if s is not None else None
    if level is None:
        raise NotFound("Radiology study not found")
    return s, level


def require_status(s, *allowed):
    if s.status not in allowed:
        raise Conflict(f"This action is not allowed while the study is {s.status}.", code="invalid_status",
                       details={"status": s.status})


def require_radiology(level):
    if level != "radiology":
        raise Forbidden("Radiology processing access required.", details={"permission": "radiology.process"})


# ---- serialization ----------------------------------------------------------
def _names(center_id, dept_ids, clinic_ids):
    d = dict(db.session.execute(select(Department.id, Department.name).where(
        Department.health_center_id == center_id, Department.id.in_(list(dept_ids) or [-1]))).all())
    c = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        Clinic.health_center_id == center_id, Clinic.id.in_(list(clinic_ids) or [-1]))).all())
    return d, c


def images(s):
    return db.session.execute(select(StoredFile).where(
        StoredFile.health_center_id == s.health_center_id, StoredFile.owner_type == "radiology_study",
        StoredFile.owner_id == s.id, StoredFile.category == "radiology_image", StoredFile.live())
        .order_by(StoredFile.id)).scalars().all()


def study_json(p, s, level, patient=None, names=None, with_images=True):
    if patient is None:
        patient = db.session.get(Patient, s.patient_id)
    if names is None:
        names = _names(s.health_center_id, {s.requesting_department_id, s.radiology_department_id},
                       {s.requesting_clinic_id, s.radiology_clinic_id} - {None})
    dn, cn = names
    show_report = level == "radiology" or s.status == "finalized"
    out = {
        "id": s.id, "status": s.status, "priority": s.priority, "access": level, "exam_type": s.exam_type,
        "body_region": s.body_region, "clinical_question": s.clinical_question,
        "patient": {"id": patient.id, "code": format_patient_code(patient.code), "full_name": patient.full_name,
                    "gender": patient.gender, "date_of_birth": iso(patient.date_of_birth)} if patient else None,
        "requesting_department": {"id": s.requesting_department_id, "name": dn.get(s.requesting_department_id)},
        "requesting_clinic": {"id": s.requesting_clinic_id, "name": cn.get(s.requesting_clinic_id)},
        "radiology_department": {"id": s.radiology_department_id, "name": dn.get(s.radiology_department_id)},
        "radiology_clinic": ({"id": s.radiology_clinic_id, "name": cn.get(s.radiology_clinic_id)}
                             if s.radiology_clinic_id else None),
        "visit_id": s.visit_id if level in ("radiology", "requester") else None,
        "requested_by": {"user_id": s.author_user_id, "name": s.author_name, "role": s.author_role},
        "requested_at": iso(s.requested_at), "scheduled_at": iso(s.scheduled_at),
        "performed_at": iso(s.performed_at),
        "report": ({"findings": s.findings, "impression": s.impression, "reported_at": iso(s.reported_at),
                    "radiologist": {"user_id": s.radiologist_user_id, "name": s.radiologist_name,
                                    "role": s.radiologist_role} if s.radiologist_name else None}
                   if show_report else None),
        "finalized_at": iso(s.finalized_at), "finalized_by": s.finalized_by_name,
        "cancelled_at": iso(s.cancelled_at), "cancelled_by": s.cancelled_by_name, "cancel_reason": s.cancel_reason,
        "report_file_id": s.report_file_id if s.status == "finalized" else None,
        "can": capabilities(p, s, level),
        "version": s.version, "created_at": iso(s.created_at), "updated_at": iso(s.updated_at),
    }
    if with_images:
        out["images"] = [files_svc.serialize(f, p) for f in images(s)] if show_report else []
    return out


def capabilities(p, s, level):
    rad = level == "radiology"
    req = p.has("radiology.request") and p.can_clinic(s.requesting_clinic_id)
    return {
        "edit": req and s.status == "requested",
        "schedule": rad and s.status in ("requested", "scheduled"),
        "start": rad and s.status in ("requested", "scheduled"),
        "upload_images": rad and s.status in ("in_progress", "reported") and p.has("files.upload"),
        "write_report": rad and s.status in ("in_progress", "reported"),
        "finalize": rad and s.status == "reported",
        "cancel": (rad and s.status in ("requested", "scheduled", "in_progress"))
        or (req and s.status in ("requested", "scheduled")),
        "delete": req and s.status == "requested",
        "share": s.status == "finalized" and (rad or (level == "requester" and p.has("files.share"))),
    }


def _list(p, stmt):
    page, per_page = page_params()
    total = db.session.execute(select(db.func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.session.execute(stmt.add_columns(Patient).join(
        Patient, (Patient.id == RadiologyStudy.patient_id) & (Patient.health_center_id ==
                                                               RadiologyStudy.health_center_id))
        .limit(per_page).offset((page - 1) * per_page)).all()
    studies = [s for s, _ in rows]
    names = _names(p.center_id, {x for s in studies for x in (s.requesting_department_id, s.radiology_department_id)},
                   {x for s in studies for x in (s.requesting_clinic_id, s.radiology_clinic_id) if x})
    items = [study_json(p, s, access_level(p, s), patient=pt, names=names, with_images=False) for s, pt in rows]
    return {"items": items, "page": page, "per_page": per_page, "total": total}


LIST_FILTERS = {
    "status": Enum(STATUSES + ("active",)), "priority": Enum(PRIORITIES), "exam_type": Enum(EXAM_TYPES),
    "patient_id": Id(), "clinic_id": Id(), "department_id": Id(), "date_from": DateTime(), "date_to": DateTime(),
}


def _filters(stmt, f, clinic_col):
    st = f.get("status")
    if st == "active":
        stmt = stmt.where(RadiologyStudy.status.in_(ACTIVE))
    elif st:
        stmt = stmt.where(RadiologyStudy.status == st)
    for k in ("priority", "exam_type", "patient_id"):
        if f.get(k):
            stmt = stmt.where(getattr(RadiologyStudy, k) == f[k])
    if f.get("clinic_id"):
        stmt = stmt.where(clinic_col == f["clinic_id"])
    if f.get("date_from"):
        stmt = stmt.where(RadiologyStudy.requested_at >= f["date_from"])
    if f.get("date_to"):
        stmt = stmt.where(RadiologyStudy.requested_at < f["date_to"])
    return stmt


def list_requested(args):
    p = current_principal()
    if not (p.has("radiology.request") or p.has("medical_records.view")):
        raise Forbidden("You do not have permission to view radiology studies.",
                        details={"permission": "radiology.request"})
    f = validate(args, LIST_FILTERS)
    stmt = select(RadiologyStudy).where(p.tenant(RadiologyStudy), RadiologyStudy.live(), requester_clause(p))
    stmt = _filters(stmt, f, RadiologyStudy.requesting_clinic_id)
    if f.get("department_id"):
        stmt = stmt.where(RadiologyStudy.requesting_department_id == f["department_id"])
    return _list(p, stmt.order_by(RadiologyStudy.requested_at.desc(), RadiologyStudy.id.desc()))


def list_worklist(args):
    p = current_principal()
    p.require("radiology.process")
    f = validate(args, LIST_FILTERS)
    if "status" not in args:
        f["status"] = "active"
    stmt = select(RadiologyStudy).where(p.tenant(RadiologyStudy), RadiologyStudy.live(), radiology_side_clause(p))
    stmt = _filters(stmt, f, RadiologyStudy.radiology_clinic_id)
    urgent_first = db.case((RadiologyStudy.priority == "urgent", 0), else_=1)
    return _list(p, stmt.order_by(urgent_first, RadiologyStudy.scheduled_at.asc().nulls_last(),
                                  RadiologyStudy.requested_at, RadiologyStudy.id))


def list_for_patient(patient_id, args):
    p = current_principal()
    get_patient(p, patient_id)
    f = validate(args, {"status": Enum(STATUSES + ("active",)), "exam_type": Enum(EXAM_TYPES)})
    stmt = select(RadiologyStudy).where(p.tenant(RadiologyStudy), RadiologyStudy.live(),
                                        RadiologyStudy.patient_id == patient_id,
                                        or_(requester_clause(p), radiology_side_clause(p), shared_clause(p)))
    stmt = _filters(stmt, f, RadiologyStudy.requesting_clinic_id)
    return _list(p, stmt.order_by(RadiologyStudy.requested_at.desc(), RadiologyStudy.id.desc()))


def get_study(sid):
    p = current_principal()
    s, level = load(p, sid)
    return study_json(p, s, level)


# ---- create / edit / delete -------------------------------------------------
CREATE_SCHEMA = {
    "patient_id": Id(required=True),
    "requesting_clinic_id": Id(),
    "radiology_department_id": Id(),
    "radiology_clinic_id": Id(),
    "visit_id": Id(),
    "exam_type": Enum(EXAM_TYPES, required=True),
    "body_region": Str(max_len=150),
    "clinical_question": Text(max_len=4000),
    "priority": Enum(PRIORITIES, default="routine"),
}
UPDATE_SCHEMA = {"exam_type": Enum(EXAM_TYPES), "body_region": Str(max_len=150),
                 "clinical_question": Text(max_len=4000), "priority": Enum(PRIORITIES)}


def create_study(data):
    p = current_principal()
    d = validate(data, CREATE_SCHEMA)
    if not p.has("radiology.request"):
        raise Forbidden("You do not have permission to request radiology studies.",
                        details={"permission": "radiology.request"})
    clinic_id, dept_id = requesting_clinic_for(p, d.get("requesting_clinic_id"), "radiology.request")
    patient = get_patient(p, d["patient_id"])
    rdept, rclinic, rclinics = resolve_target(p.center_id, "radiology", d.get("radiology_department_id"),
                                              d.get("radiology_clinic_id"), "radiology")
    if d.get("visit_id"):
        v = get_visit(p, d["visit_id"])
        if v.patient_id != patient.id or v.clinic_id != clinic_id:
            raise ValidationError("Invalid input", details={"visit_id": "does not belong to this patient/clinic"})
    s = RadiologyStudy(health_center_id=p.center_id, patient_id=patient.id, requesting_department_id=dept_id,
                       requesting_clinic_id=clinic_id, radiology_department_id=rdept, radiology_clinic_id=rclinic,
                       visit_id=d.get("visit_id"), exam_type=d["exam_type"], body_region=d.get("body_region"),
                       clinical_question=d.get("clinical_question"), priority=d["priority"], status="requested",
                       requested_at=utcnow())
    s.set_author(p.user)
    db.session.add(s)
    db.session.flush()
    for c in ([rclinic] if rclinic else rclinics):
        link_patient_to_clinic(p.center_id, patient.id, c, rdept)
    N.radiology_request(p, s, rclinics)
    db.session.commit()
    return study_json(p, s, access_level(p, s))


def update_study(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    if not (p.has("radiology.request") and p.can_clinic(s.requesting_clinic_id)):
        raise Forbidden("Only the requesting clinic can edit this request.",
                        details={"permission": "radiology.request"})
    check_version(s, data.get("version"))
    require_status(s, "requested")
    d = validate(data, UPDATE_SCHEMA, partial=True)
    for k in ("exam_type", "priority"):
        if k in d and d[k] is None:
            raise ValidationError("Invalid input", details={k: "is required"})
    for k, v in d.items():
        setattr(s, k, v)
    db.session.commit()
    return study_json(p, s, level)


def delete_study(sid):
    p = current_principal()
    s, level = load(p, sid)
    if not (p.has("radiology.request") and p.can_clinic(s.requesting_clinic_id)):
        raise Forbidden("Only the requesting clinic can delete this request.",
                        details={"permission": "radiology.request"})
    require_status(s, "requested")
    return deletion.stage(p, s, "radiology_study", f"Radiology study #{s.id}")
