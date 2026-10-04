"""Lab request workflow and visibility.

Access levels for one request (computed by `access_level`):
  "lab"        laboratory side: `lab.process` + the target lab department/clinic in scope
               -> full workflow, draft results visible.
  "requester"  requesting clinic in scope (+ lab.request or medical_records.view)
               -> request metadata; results only once finalized (completed).
  "result"     request completed + `medical_records.view` + patient visible to the principal
               -> read-only finalized results (center-wide availability, spec §104). This never
               grants workflow access.
Anything else -> 404. Lab staff see only the patient's basic identity in these payloads and
never other specialty records (their clinic scope is the lab clinic only).
"""
from sqlalchemy import and_, false, or_, select, true

from backend.app.authz.principal import current_principal
from backend.app.core.api import check_version, page_params
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import Bool, DateTime, Enum, Id, List, Obj, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Department, Patient
from backend.app.services import deletion
from backend.app.services.clinical import format_patient_code, get_patient, get_visit, link_patient_to_clinic

from . import flags as F
from .catalog import _num, active_tests_by_id
from .models import PRIORITIES, STATUSES, LabRequest, LabRequestItem
from .routing import requesting_clinic_for, resolve_target
from . import notify as N

deletion.register("lab_request", LabRequest)

ACTIVE = ("requested", "in_progress")


# ---- scope ------------------------------------------------------------------
def lab_side(p, r):
    if not p.has("lab.process"):
        return False
    if p.center_wide or p.can_department(r.lab_department_id):
        return True
    if r.lab_clinic_id is not None:
        return p.can_clinic(r.lab_clinic_id)
    return any(p.clinic_department.get(c) == r.lab_department_id for c in p.clinic_ids)


def requester_side(p, r):
    return p.can_clinic(r.requesting_clinic_id) and (p.has("lab.request") or p.has("medical_records.view"))


def _patient_visible(p, patient_id):
    return db.session.execute(select(Patient.id).where(Patient.id == patient_id, p.tenant(Patient), Patient.live(),
                                                       p.patient_clause(Patient.id))).first() is not None


def access_level(p, r):
    if lab_side(p, r):
        return "lab"
    if requester_side(p, r):
        return "requester"
    if r.status == "completed" and p.has("medical_records.view") and _patient_visible(p, r.patient_id):
        return "result"
    return None


def lab_side_clause(p):
    if not p.has("lab.process"):
        return false()
    if p.center_wide:
        return true()
    managed = sorted(d for d in p.managed_department_ids if p.department_env.get(d) == "laboratory")
    lab_clinics = sorted(c for c in p.clinic_ids if p.department_env.get(p.clinic_department.get(c)) == "laboratory")
    lab_depts = sorted({p.clinic_department[c] for c in lab_clinics})
    return or_(LabRequest.lab_department_id.in_(managed or [-1]),
               LabRequest.lab_clinic_id.in_(lab_clinics or [-1]),
               and_(LabRequest.lab_clinic_id.is_(None), LabRequest.lab_department_id.in_(lab_depts or [-1])))


def requester_clause(p):
    if not (p.has("lab.request") or p.has("medical_records.view")):
        return false()
    return p.clinic_clause(LabRequest.requesting_clinic_id)


def result_clause(p):
    if not p.has("medical_records.view"):
        return false()
    return and_(LabRequest.status == "completed", p.patient_clause(LabRequest.patient_id))


def _load(p, rid, for_update=False):
    stmt = select(LabRequest).where(LabRequest.id == rid, p.tenant(LabRequest), LabRequest.live())
    if for_update:
        stmt = stmt.with_for_update()
    r = db.session.execute(stmt).scalar_one_or_none()
    if r is None:
        raise NotFound("Lab request not found")
    level = access_level(p, r)
    if level is None:
        raise NotFound("Lab request not found")
    return r, level


def _require_status(r, *allowed):
    if r.status not in allowed:
        raise Conflict(f"This action is not allowed while the request is {r.status}.", code="invalid_status",
                       details={"status": r.status})


# ---- serialization ----------------------------------------------------------
def _names(center_id, dept_ids, clinic_ids):
    d = dict(db.session.execute(select(Department.id, Department.name).where(
        Department.health_center_id == center_id, Department.id.in_(list(dept_ids) or [-1]))).all())
    c = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        Clinic.health_center_id == center_id, Clinic.id.in_(list(clinic_ids) or [-1]))).all())
    return d, c


def patient_identity(pt):
    return {"id": pt.id, "code": format_patient_code(pt.code), "full_name": pt.full_name, "gender": pt.gender,
            "date_of_birth": iso(pt.date_of_birth)}


def item_json(i, show_results):
    out = {"id": i.id, "test_id": i.test_id, "test_code": i.test_code, "test_name": i.test_name,
           "category_name": i.category_name, "unit": i.unit, "result_type": i.result_type,
           "choices": i.choices or [], "normal_choices": i.normal_choices or [], "ref_low": _num(i.ref_low), "ref_high": _num(i.ref_high),
           "ref_text": i.ref_text}
    if show_results:
        out.update({"result_value": i.result_value, "numeric_value": _num(i.numeric_value),
                    "abnormal_flag": i.abnormal_flag, "comment": i.comment})
    return out


def request_json(p, r, level, patient=None, items=None, names=None):
    if patient is None:
        patient = db.session.get(Patient, r.patient_id)
    if items is None:
        items = db.session.execute(select(LabRequestItem).where(LabRequestItem.request_id == r.id)
                                   .order_by(LabRequestItem.sort_order, LabRequestItem.id)).scalars().all()
    if names is None:
        names = _names(r.health_center_id, {r.requesting_department_id, r.lab_department_id},
                       {r.requesting_clinic_id, r.lab_clinic_id} - {None})
    dn, cn = names
    show = level == "lab" or r.status == "completed"
    abnormal = sum(1 for i in items if i.abnormal_flag in ("L", "H", "A")) if show else None
    return {
        "id": r.id, "status": r.status, "priority": r.priority, "access": level,
        "patient": patient_identity(patient) if patient else {"id": r.patient_id},
        "requesting_department": {"id": r.requesting_department_id, "name": dn.get(r.requesting_department_id)},
        "requesting_clinic": {"id": r.requesting_clinic_id, "name": cn.get(r.requesting_clinic_id)},
        "lab_department": {"id": r.lab_department_id, "name": dn.get(r.lab_department_id)},
        "lab_clinic": {"id": r.lab_clinic_id, "name": cn.get(r.lab_clinic_id)} if r.lab_clinic_id else None,
        "visit_id": r.visit_id if level in ("lab", "requester") else None,
        "requested_by": {"user_id": r.author_user_id, "name": r.author_name, "role": r.author_role},
        "requested_at": iso(r.requested_at), "clinical_notes": r.clinical_notes,
        "started_at": iso(r.started_at), "performed_by": r.performed_by_name,
        "finalized_at": iso(r.finalized_at),
        "finalized_by": {"user_id": r.finalized_by_user_id, "name": r.finalized_by_name,
                         "role": r.finalized_by_role} if r.finalized_at else None,
        "cancelled_at": iso(r.cancelled_at), "cancelled_by": r.cancelled_by_name, "cancel_reason": r.cancel_reason,
        "result_notes": r.result_notes if show else None,
        "report_file_id": r.report_file_id if r.status == "completed" else None,
        "abnormal_count": abnormal,
        "items": [item_json(i, show) for i in items],
        "can": _capabilities(p, r, level),
        "version": r.version, "created_at": iso(r.created_at), "updated_at": iso(r.updated_at),
    }


def _capabilities(p, r, level):
    lab = level == "lab"
    req = level == "requester" and p.has("lab.request")
    return {
        "edit": (req or (lab and p.has("lab.request") and p.can_clinic(r.requesting_clinic_id)))
        and r.status == "requested",
        "start": lab and r.status == "requested",
        "enter_results": lab and r.status in ACTIVE,
        "finalize": lab and r.status == "in_progress",
        "cancel": ((lab and r.status in ACTIVE) or (req and r.status == "requested")),
        "delete": p.has("lab.request") and p.can_clinic(r.requesting_clinic_id) and r.status == "requested",
    }


def _list(p, stmt):
    page, per_page = page_params()
    total = db.session.execute(select(db.func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.session.execute(stmt.add_columns(Patient).join(
        Patient, (Patient.id == LabRequest.patient_id) & (Patient.health_center_id == LabRequest.health_center_id))
        .limit(per_page).offset((page - 1) * per_page)).all()
    reqs = [r for r, _ in rows]
    items = {}
    if reqs:
        for i in db.session.execute(select(LabRequestItem).where(LabRequestItem.request_id.in_([r.id for r in reqs]))
                                    .order_by(LabRequestItem.sort_order, LabRequestItem.id)).scalars():
            items.setdefault(i.request_id, []).append(i)
    names = _names(p.center_id, {x for r in reqs for x in (r.requesting_department_id, r.lab_department_id)},
                   {x for r in reqs for x in (r.requesting_clinic_id, r.lab_clinic_id) if x})
    out = []
    for r, pt in rows:
        level = access_level(p, r)
        j = request_json(p, r, level, patient=pt, items=items.get(r.id, []), names=names)
        j["tests"] = [i["test_name"] for i in j.pop("items")]
        out.append(j)
    return {"items": out, "page": page, "per_page": per_page, "total": total}


LIST_FILTERS = {
    "status": Enum(STATUSES + ("active",)), "priority": Enum(PRIORITIES), "patient_id": Id(), "clinic_id": Id(),
    "department_id": Id(), "date_from": DateTime(), "date_to": DateTime(),
}


def _filters(stmt, f, clinic_col):
    st = f.get("status")
    if st == "active":
        stmt = stmt.where(LabRequest.status.in_(ACTIVE))
    elif st:
        stmt = stmt.where(LabRequest.status == st)
    if f.get("priority"):
        stmt = stmt.where(LabRequest.priority == f["priority"])
    if f.get("patient_id"):
        stmt = stmt.where(LabRequest.patient_id == f["patient_id"])
    if f.get("clinic_id"):
        stmt = stmt.where(clinic_col == f["clinic_id"])
    if f.get("date_from"):
        stmt = stmt.where(LabRequest.requested_at >= f["date_from"])
    if f.get("date_to"):
        stmt = stmt.where(LabRequest.requested_at < f["date_to"])
    return stmt


def list_requested(args):
    """Requests made by the principal's clinics (requesting side)."""
    p = current_principal()
    if not (p.has("lab.request") or p.has("medical_records.view")):
        raise Forbidden("You do not have permission to view lab requests.", details={"permission": "lab.request"})
    f = validate(args, LIST_FILTERS)
    stmt = select(LabRequest).where(p.tenant(LabRequest), LabRequest.live(), requester_clause(p))
    stmt = _filters(stmt, f, LabRequest.requesting_clinic_id)
    if f.get("department_id"):
        stmt = stmt.where(LabRequest.requesting_department_id == f["department_id"])
    return _list(p, stmt.order_by(LabRequest.requested_at.desc(), LabRequest.id.desc()))


def list_queue(args):
    """Laboratory worklist: requests addressed to the principal's laboratory department(s)."""
    p = current_principal()
    p.require("lab.process")
    f = validate(args, LIST_FILTERS)
    if "status" not in args:
        f["status"] = "active"
    stmt = select(LabRequest).where(p.tenant(LabRequest), LabRequest.live(), lab_side_clause(p))
    stmt = _filters(stmt, f, LabRequest.lab_clinic_id)
    urgent_first = db.case((LabRequest.priority == "urgent", 0), else_=1)
    stmt = stmt.order_by(urgent_first, LabRequest.requested_at, LabRequest.id)
    return _list(p, stmt)


def list_for_patient(patient_id, args):
    p = current_principal()
    get_patient(p, patient_id)  # patient must be visible (404 otherwise)
    f = validate(args, {"status": Enum(STATUSES + ("active",))})
    stmt = select(LabRequest).where(p.tenant(LabRequest), LabRequest.live(), LabRequest.patient_id == patient_id,
                                    or_(requester_clause(p), lab_side_clause(p), result_clause(p)))
    stmt = _filters(stmt, f, LabRequest.requesting_clinic_id).order_by(LabRequest.requested_at.desc(),
                                                                         LabRequest.id.desc())
    return _list(p, stmt)


def get_request(rid):
    p = current_principal()
    r, level = _load(p, rid)
    return request_json(p, r, level)


# ---- workflow ---------------------------------------------------------------
CREATE_SCHEMA = {
    "patient_id": Id(required=True),
    "requesting_clinic_id": Id(),
    "lab_department_id": Id(),
    "lab_clinic_id": Id(),
    "visit_id": Id(),
    "priority": Enum(PRIORITIES, default="routine"),
    "clinical_notes": Text(max_len=4000),
    "test_ids": List(Id(required=True), min_items=1, max_items=100, required=True),
}


def create_request(data):
    p = current_principal()
    d = validate(data, CREATE_SCHEMA)
    if not p.has("lab.request"):
        raise Forbidden("You do not have permission to request lab tests.", details={"permission": "lab.request"})
    clinic_id, dept_id = requesting_clinic_for(p, d.get("requesting_clinic_id"), "lab.request")
    patient = get_patient(p, d["patient_id"])
    lab_dept, lab_clinic, lab_clinics = resolve_target(p.center_id, "laboratory", d.get("lab_department_id"),
                                                       d.get("lab_clinic_id"), "lab")
    if d.get("visit_id"):
        v = get_visit(p, d["visit_id"])
        if v.patient_id != patient.id or v.clinic_id != clinic_id:
            raise ValidationError("Invalid input", details={"visit_id": "does not belong to this patient/clinic"})
    ids = list(dict.fromkeys(d["test_ids"]))
    tests = active_tests_by_id(p, ids)
    missing = [i for i in ids if i not in tests]
    if missing:
        raise ValidationError("Invalid input", details={"test_ids": f"unknown or inactive tests: {missing}"})
    r = LabRequest(health_center_id=p.center_id, patient_id=patient.id, requesting_department_id=dept_id,
                   requesting_clinic_id=clinic_id, lab_department_id=lab_dept, lab_clinic_id=lab_clinic,
                   visit_id=d.get("visit_id"), priority=d["priority"], status="requested",
                   clinical_notes=d.get("clinical_notes"), patient_gender=patient.gender, requested_at=utcnow())
    r.set_author(p.user)
    db.session.add(r)
    db.session.flush()
    for n, tid in enumerate(ids):
        t, cat = tests[tid]
        low, high = F.ranges_for(t, patient.gender)
        db.session.add(LabRequestItem(
            health_center_id=p.center_id, request_id=r.id, test_id=t.id, test_code=t.code, test_name=t.name,
            category_name=cat, unit=t.unit, result_type=t.result_type, choices=t.choices,
            normal_choices=t.normal_choices, ref_low=low, ref_high=high, ref_text=t.ref_text, price=t.price,
            sort_order=n))
    # Lab staff must be able to see the patient's basic profile (never other specialty records).
    for c in ([lab_clinic] if lab_clinic else lab_clinics):
        link_patient_to_clinic(p.center_id, patient.id, c, lab_dept)
    N.lab_request(p, r, lab_clinics)
    db.session.commit()
    return request_json(p, r, access_level(p, r))


UPDATE_SCHEMA = {"priority": Enum(PRIORITIES), "clinical_notes": Text(max_len=4000)}


def update_request(rid, data):
    p = current_principal()
    r, level = _load(p, rid, for_update=True)
    if not (p.can_clinic(r.requesting_clinic_id) and p.has("lab.request")):
        raise Forbidden("Only the requesting clinic can edit this request.", details={"permission": "lab.request"})
    check_version(r, data.get("version"))
    _require_status(r, "requested")
    d = validate(data, UPDATE_SCHEMA, partial=True)
    if "priority" in d and d["priority"] is None:
        raise ValidationError("Invalid input", details={"priority": "is required"})
    for k, v in d.items():
        setattr(r, k, v)
    db.session.commit()
    return request_json(p, r, level)


def _require_processing(p, r, level):
    """Visible but not on the laboratory side -> 403 (the object is in view, the action is not)."""
    if level != "lab":
        raise Forbidden("Laboratory processing access required.", details={"permission": "lab.process"})


def start(rid, data):
    p = current_principal()
    r, level = _load(p, rid, for_update=True)
    _require_processing(p, r, level)
    check_version(r, data.get("version"))
    _require_status(r, "requested")
    d = validate(data, {"lab_clinic_id": Id()})
    _assign_lab_clinic(p, r, d.get("lab_clinic_id"))
    r.status, r.started_at = "in_progress", utcnow()
    r.performed_by_user_id, r.performed_by_name = p.user.id, p.user.name
    db.session.commit()
    return request_json(p, r, level)


def _assign_lab_clinic(p, r, clinic_id):
    if clinic_id is not None:
        if r.lab_clinic_id not in (None, clinic_id):
            raise ValidationError("Invalid input", details={"lab_clinic_id": "does not match the request"})
        if p.clinic_department.get(clinic_id) != r.lab_department_id or not p.can_clinic(clinic_id):
            raise ValidationError("Invalid input", details={"lab_clinic_id": "is invalid"})
        r.lab_clinic_id = clinic_id
    elif r.lab_clinic_id is None:
        mine = [c for c in sorted(p.clinic_ids) if p.clinic_department.get(c) == r.lab_department_id]
        if len(mine) == 1 or (p.user.clinic_id in mine):
            r.lab_clinic_id = p.user.clinic_id if p.user.clinic_id in mine else mine[0]
    if r.lab_clinic_id is not None:
        link_patient_to_clinic(p.center_id, r.patient_id, r.lab_clinic_id, r.lab_department_id)


RESULT_ITEM = {"id": Id(required=True), "result_value": Str(max_len=500), "comment": Text(max_len=2000),
               "abnormal": Bool()}


def enter_results(rid, data):
    p = current_principal()
    r, level = _load(p, rid, for_update=True)
    _require_processing(p, r, level)
    check_version(r, data.get("version"))
    _require_status(r, *ACTIVE)
    d = validate(data, {"items": List(Obj(RESULT_ITEM), max_items=200, required=True),
                        "result_notes": Text(max_len=4000)}, partial=False)
    items = {i.id: i for i in db.session.execute(select(LabRequestItem).where(LabRequestItem.request_id == r.id)
                                                 ).scalars()}
    errors = {}
    for n, row in enumerate(d["items"] or []):
        it = items.get(row["id"])
        if it is None:
            errors[f"items.{n}.id"] = "is not part of this request"
            continue
        if "result_value" not in row and "comment" not in row and "abnormal" not in row:
            continue
        if "result_value" in row:
            try:
                num, flag = F.compute_flag(it.result_type, row["result_value"], low=it.ref_low, high=it.ref_high,
                                           choices=it.choices, normal_choices=it.normal_choices,
                                           abnormal=row.get("abnormal") if it.result_type != "numeric" else None)
            except ValueError as e:
                errors[f"items.{n}.result_value"] = str(e)
                continue
            it.result_value = str(num) if num is not None else row["result_value"]
            it.numeric_value, it.abnormal_flag = num, flag
        elif "abnormal" in row and it.result_type != "numeric" and it.result_value:
            it.abnormal_flag = None if row["abnormal"] is None else ("A" if row["abnormal"] else "N")
        if "comment" in row:
            it.comment = row["comment"]
    if errors:
        raise ValidationError("Invalid results", details=errors)
    if "result_notes" in data:
        r.result_notes = d.get("result_notes")
    if r.status == "requested":
        _assign_lab_clinic(p, r, None)
        r.status, r.started_at = "in_progress", utcnow()
        r.performed_by_user_id, r.performed_by_name = p.user.id, p.user.name
    r.updated_at = utcnow()  # bumps the version even when only items changed
    db.session.commit()
    return request_json(p, r, level)


def finalize(rid, data):
    p = current_principal()
    r, level = _load(p, rid, for_update=True)
    _require_processing(p, r, level)
    check_version(r, data.get("version"))
    _require_status(r, "in_progress")
    missing = db.session.execute(select(LabRequestItem.test_name).where(
        LabRequestItem.request_id == r.id,
        or_(LabRequestItem.result_value.is_(None), LabRequestItem.result_value == ""))).scalars().all()
    if missing:
        raise ValidationError("Enter all results before finalizing.", code="missing_results",
                              details={"missing": missing})
    if r.lab_clinic_id is None:
        _assign_lab_clinic(p, r, None)
    now = utcnow()
    r.status, r.finalized_at = "completed", now
    r.finalized_by_user_id, r.finalized_by_name, r.finalized_by_role = p.user.id, p.user.name, p.user.role
    N.lab_result(p, r)
    db.session.commit()
    from .report import attach_pdf
    attach_pdf(p, r)  # best-effort, separate transaction
    return request_json(p, r, level)


def cancel(rid, data):
    p = current_principal()
    r, level = _load(p, rid, for_update=True)
    check_version(r, data.get("version"))
    d = validate(data, {"reason": Str(max_len=500)})
    if level == "lab":
        _require_status(r, *ACTIVE)
    elif level == "requester" and p.has("lab.request"):
        _require_status(r, "requested")
    else:
        raise Forbidden("You cannot cancel this request.", details={"permission": "lab.request"})
    r.status, r.cancelled_at = "cancelled", utcnow()
    r.cancelled_by_name, r.cancel_reason = p.user.name, d.get("reason")
    db.session.commit()
    return request_json(p, r, level)


def delete_request(rid):
    p = current_principal()
    r, level = _load(p, rid)
    if not (p.has("lab.request") and p.can_clinic(r.requesting_clinic_id)):
        raise Forbidden("Only the requesting clinic can delete this request.", details={"permission": "lab.request"})
    _require_status(r, "requested")
    return deletion.stage(p, r, "lab_request", f"Lab request #{r.id}")
