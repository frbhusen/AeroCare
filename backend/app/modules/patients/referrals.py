"""Patient Internal Referrals & Cross-Department Consultations service."""
from sqlalchemy import or_, select

from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import Enum, Id, Str, Text, validate
from backend.app.extensions import db
from backend.app.models.clinical import Patient, PatientReferral, REFERRAL_STATUSES, REFERRAL_URGENCIES, Visit
from backend.app.models.org import Clinic, Department
from backend.app.services import deletion
from backend.app.services.clinical import get_patient


def _referral_json(r, p_obj=None, from_dept=None, from_cl=None, to_dept=None, to_cl=None):
    if r is None:
        return None
    return {
        "id": r.id,
        "patient_id": r.patient_id,
        "patient_name": p_obj.full_name if p_obj else None,
        "patient_code": p_obj.display_code if p_obj else None,
        "from_department_id": r.from_department_id,
        "from_department_name": from_dept.name if from_dept else None,
        "from_clinic_id": r.from_clinic_id,
        "from_clinic_name": from_cl.name if from_cl else None,
        "to_department_id": r.to_department_id,
        "to_department_name": to_dept.name if to_dept else None,
        "to_clinic_id": r.to_clinic_id,
        "to_clinic_name": to_cl.name if to_cl else None,
        "visit_id": r.visit_id,
        "completed_visit_id": r.completed_visit_id,
        "reason": r.reason,
        "urgency": r.urgency,
        "status": r.status,
        "referred_at": iso(r.referred_at),
        "accepted_at": iso(r.accepted_at),
        "accepted_by_name": r.accepted_by_name,
        "completed_at": iso(r.completed_at),
        "notes": r.notes,
        "author_name": r.author_name,
        "author_role": r.author_role,
        "created_at": iso(r.created_at),
        "version": r.version,
    }


def _is_sender(p, r):
    return p.center_wide or p.can_clinic(r.from_clinic_id)


def _is_receiver(p, r):
    """Receiving side: the target clinic (when one was chosen) or any clinic of the target department."""
    if p.center_wide:
        return True
    if r.to_clinic_id:
        return p.can_clinic(r.to_clinic_id)
    return p.sees_department(r.to_department_id)


def _involved(p, r):
    return _is_sender(p, r) or _is_receiver(p, r)


def _restrict(item):
    """Referral of another department/clinic: show that it exists (spec §20) but not its clinical text."""
    item.update(reason=None, notes=None, restricted=True)
    return item


def _enrich_many(p, items):
    if not items:
        return []
    patient_ids = {r.patient_id for r in items}
    dept_ids = {r.from_department_id for r in items} | {r.to_department_id for r in items}
    clinic_ids = {r.from_clinic_id for r in items} | {r.to_clinic_id for r in items if r.to_clinic_id}

    patients = {pt.id: pt for pt in db.session.execute(
        select(Patient).where(p.tenant(Patient), Patient.id.in_(patient_ids))
    ).scalars()}
    departments = {d.id: d for d in db.session.execute(
        select(Department).where(p.tenant(Department), Department.id.in_(dept_ids))
    ).scalars()}
    clinics = {c.id: c for c in db.session.execute(
        select(Clinic).where(p.tenant(Clinic), Clinic.id.in_(clinic_ids))
    ).scalars()}

    return [_referral_json(r,
                           p_obj=patients.get(r.patient_id),
                           from_dept=departments.get(r.from_department_id),
                           from_cl=clinics.get(r.from_clinic_id),
                           to_dept=departments.get(r.to_department_id),
                           to_cl=clinics.get(r.to_clinic_id)) for r in items]


def list_referrals(p, patient_id):
    p.require("medical_records.view")
    get_patient(p, patient_id)
    stmt = (select(PatientReferral)
            .where(p.tenant(PatientReferral), PatientReferral.patient_id == patient_id, PatientReferral.live())
            .order_by(PatientReferral.referred_at.desc(), PatientReferral.id.desc()))
    items = db.session.execute(stmt).scalars().all()
    out = []
    for r, j in zip(items, _enrich_many(p, items)):
        j["restricted"] = False
        out.append(j if _involved(p, r) else _restrict(j))
    return {"items": out}


def create_referral(p, patient_id, body):
    p.require("medical_records.create")
    get_patient(p, patient_id)
    data = validate(body, {
        "from_department_id": Id(required=True),
        "from_clinic_id": Id(required=True),
        "to_department_id": Id(required=True),
        "to_clinic_id": Id(),
        "visit_id": Id(),
        "reason": Str(required=True, min_len=3, max_len=5000),
        "urgency": Enum(REFERRAL_URGENCIES),
        "notes": Text(max_len=2000),
    })

    p.require(clinic_id=data["from_clinic_id"])
    from_clinic = db.session.execute(select(Clinic).where(p.tenant(Clinic), Clinic.id == data["from_clinic_id"],
                                                          Clinic.live())).scalar_one_or_none()
    if from_clinic is None or from_clinic.department_id != data["from_department_id"]:
        raise ValidationError("Invalid input", details={"from_department_id": "does not match the clinic"})
    if data.get("visit_id"):
        v = db.session.execute(select(Visit).where(p.tenant(Visit), Visit.id == data["visit_id"], Visit.live(),
                                                   Visit.patient_id == patient_id,
                                                   Visit.clinic_id == data["from_clinic_id"])).scalar_one_or_none()
        if v is None:
            raise ValidationError("Invalid input", details={"visit_id": "must be this patient's visit in the referring clinic"})

    # Ensure target department exists in this center
    to_dept = db.session.execute(
        select(Department).where(p.tenant(Department), Department.id == data["to_department_id"], Department.live())
    ).scalar_one_or_none()
    if not to_dept:
        raise ValidationError("Target department does not exist in this center.", code="invalid_department")
    if data.get("to_clinic_id"):
        to_clinic = db.session.execute(select(Clinic).where(p.tenant(Clinic), Clinic.id == data["to_clinic_id"],
                                                            Clinic.live())).scalar_one_or_none()
        if to_clinic is None or to_clinic.department_id != to_dept.id:
            raise ValidationError("Invalid input", details={"to_clinic_id": "is not a clinic of the target department"})

    r = PatientReferral(
        health_center_id=p.center_id,
        patient_id=patient_id,
        from_department_id=data["from_department_id"],
        from_clinic_id=data["from_clinic_id"],
        to_department_id=data["to_department_id"],
        to_clinic_id=data.get("to_clinic_id"),
        visit_id=data.get("visit_id"),
        reason=data["reason"].strip(),
        urgency=data.get("urgency") or "routine",
        status="pending",
        referred_at=utcnow(),
        notes=data.get("notes"),
    )
    r.set_author(p.user)
    db.session.add(r)
    db.session.commit()
    return _enrich_many(p, [r])[0]


def incoming_referrals(p, query=None):
    p.require("medical_records.view")
    q = query or {}
    stmt = select(PatientReferral).where(p.tenant(PatientReferral), PatientReferral.live())

    # Filter to user's accessible departments if not superadmin / center_wide
    if not p.center_wide:
        accessible_depts = p.visible_department_ids
        if not accessible_depts:
            return {"items": [], "total": 0}
        stmt = stmt.where(PatientReferral.to_department_id.in_(accessible_depts))
        # A chosen target clinic narrows it further: only that clinic's staff (and department-level users).
        clinics = sorted(p.clinic_ids) or [-1]
        managed = sorted(p.managed_department_ids) or [-1]
        stmt = stmt.where(or_(PatientReferral.to_clinic_id.is_(None), PatientReferral.to_clinic_id.in_(clinics),
                              PatientReferral.to_department_id.in_(managed)))

    dept_id = q.get("department_id")
    if dept_id:
        stmt = stmt.where(PatientReferral.to_department_id == int(dept_id))

    status = q.get("status") or "pending"
    if status != "all":
        stmt = stmt.where(PatientReferral.status == status)

    stmt = stmt.order_by(PatientReferral.referred_at.desc(), PatientReferral.id.desc())
    items = db.session.execute(stmt).scalars().all()
    return {"items": _enrich_many(p, items), "total": len(items)}


def update_referral_status(p, referral_id, body):
    """Receiver accepts/completes; sender or receiver may cancel. Out-of-scope referrals are 404."""
    from backend.app.core.api import check_version
    p.require("medical_records.edit")
    r = db.session.execute(
        select(PatientReferral).where(p.tenant(PatientReferral), PatientReferral.id == referral_id,
                                      PatientReferral.live()).with_for_update()
    ).scalar_one_or_none()
    if r is None or not _involved(p, r):
        raise NotFound("Referral not found")

    data = validate(body, {
        "status": Enum(REFERRAL_STATUSES, required=True),
        "notes": Text(max_len=2000),
        "completed_visit_id": Id(),
        "version": Id(),
    })
    if data.get("version") is not None:
        check_version(r, data["version"])

    new_status = data["status"]
    if new_status in ("accepted", "completed") and not _is_receiver(p, r):
        raise Forbidden("Only the receiving department can accept or complete this referral.")
    if r.status in ("completed", "cancelled") and new_status != r.status:
        raise ValidationError(f"This referral is already {r.status}.", code="invalid_transition")
    allowed = {"pending": {"accepted", "completed", "cancelled"}, "accepted": {"completed", "cancelled"}}
    if new_status != r.status and new_status not in allowed.get(r.status, set()):
        raise ValidationError(f"Cannot change status from {r.status} to {new_status}.", code="invalid_transition")

    now = utcnow()
    if new_status == "accepted" and r.status == "pending":
        r.status = "accepted"
        r.accepted_at = now
        r.accepted_by_user_id = p.user.id
        r.accepted_by_name = p.user.name
    elif new_status == "completed" and r.status != "completed":
        if data.get("completed_visit_id"):
            v = db.session.execute(select(Visit).where(
                p.tenant(Visit), Visit.id == data["completed_visit_id"], Visit.live(), Visit.patient_id == r.patient_id,
                Visit.department_id == r.to_department_id, p.clinic_clause(Visit.clinic_id))).scalar_one_or_none()
            if v is None:
                raise ValidationError("Invalid input", details={
                    "completed_visit_id": "must be this patient's visit in the receiving department"})
            r.completed_visit_id = v.id
        if r.status == "pending":
            r.accepted_at = now
            r.accepted_by_user_id = p.user.id
            r.accepted_by_name = p.user.name
        r.status = "completed"
        r.completed_at = now
    elif new_status == "cancelled" and r.status != "cancelled":
        r.status = "cancelled"

    if data.get("notes"):
        r.notes = (r.notes + "\n" + data["notes"]).strip() if r.notes else data["notes"]

    db.session.commit()
    out = _enrich_many(p, [r])[0]
    out["restricted"] = False
    return out
