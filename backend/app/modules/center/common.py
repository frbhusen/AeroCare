"""Helpers shared by the center (and admin) services: management level, user department,
session revocation and center row locking."""
from sqlalchemy import select

from backend.app.extensions import db
from backend.app.models import Clinic, HealthCenter, UserScope


def is_center_level(p):
    """Health Center Manager (or Superadmin support view): manages the whole center."""
    return bool(p.center_id) and (p.role == "center_manager" or p.support_mode)


def user_department_id(u):
    """Department an account belongs to, for audit scoping (None when center-wide / mixed)."""
    if u.role == "department_manager":
        return u.department_id
    if u.role == "doctor" and u.clinic_id:
        return db.session.execute(select(Clinic.department_id).where(
            Clinic.id == u.clinic_id, Clinic.health_center_id == u.health_center_id)).scalar()
    if u.role == "receptionist":
        rows = db.session.execute(select(UserScope.department_id, Clinic.department_id)
                                  .outerjoin(Clinic, (Clinic.id == UserScope.clinic_id)
                                             & (Clinic.health_center_id == UserScope.health_center_id))
                                  .where(UserScope.user_id == u.id)).all()
        depts = set()
        for d, cd in rows:
            if d is None and cd is None:
                return None
            depts.add(d or cd)
        return depts.pop() if len(depts) == 1 else None
    return None


def lock_center(center_id):
    """Serialize plan-limit checks per center (row lock until commit)."""
    db.session.execute(select(HealthCenter.id).where(HealthCenter.id == center_id).with_for_update())


def revoke_sessions(user_id, reason):
    from backend.app.auth.service import revoke_user_sessions
    db.session.flush()  # pending tenant rows must be written in the tenant context, not 'auth' mode
    revoke_user_sessions(user_id, reason)
