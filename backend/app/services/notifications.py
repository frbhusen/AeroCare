"""Simple in-app notifications (spec §76). No email/SMS. Fan-out to users whose scope covers
the clinic/department. Content must stay operational (no clinical details)."""
from sqlalchemy import or_, select

from backend.app.extensions import db
from backend.app.models import Clinic, Department, Notification, User, UserScope

TYPES = ("appointment_created", "appointment_cancelled", "patient_arrived", "payment_recorded", "low_stock",
         "lab_result_available", "radiology_result_available", "permission_changed", "prescription_pending",
         "lab_request", "radiology_request")


def recipients_for(center_id, clinic_id=None, department_id=None):
    if clinic_id and not department_id:
        department_id = db.session.execute(select(Clinic.department_id).where(Clinic.id == clinic_id)).scalar()
    conds = [User.role == "center_manager"]
    if department_id:
        conds.append((User.role == "department_manager") & (User.department_id == department_id))
        rec_scope = select(UserScope.user_id).where(or_(
            (UserScope.department_id.is_(None) & UserScope.clinic_id.is_(None)),
            UserScope.department_id == department_id,
            UserScope.clinic_id == clinic_id if clinic_id else False))
        conds.append((User.role == "receptionist") & User.id.in_(rec_scope))
    if clinic_id:
        conds.append((User.role.in_(["doctor", "department_manager"])) & (User.clinic_id == clinic_id))
    rows = db.session.execute(select(User.id).where(User.health_center_id == center_id, User.status == "active",
                                                    or_(*conds))).scalars().all()
    return set(rows)


def notify(center_id, type_, title, body=None, link=None, *, clinic_id=None, department_id=None, user_ids=None,
           exclude_user_id=None):
    targets = set(user_ids or []) | (recipients_for(center_id, clinic_id, department_id)
                                     if (clinic_id or department_id) else set())
    targets.discard(exclude_user_id)
    for uid in targets:
        db.session.add(Notification(health_center_id=center_id, user_id=uid, type=type_, title=title[:255],
                                    body=(body or "")[:500] or None, link=link))
    return len(targets)
