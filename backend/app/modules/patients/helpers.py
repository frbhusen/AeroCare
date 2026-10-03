"""Small shared helpers for the patients / visits / prescriptions / files / generic modules."""
from sqlalchemy import select

from backend.app.extensions import db
from backend.app.models import Clinic, Department, DepartmentType


def like_escape(s):
    """Escape LIKE wildcards in user input (used with escape='\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def clinic_names(center_id, clinic_ids):
    ids = sorted({c for c in clinic_ids if c})
    if not ids:
        return {}
    rows = db.session.execute(select(Clinic.id, Clinic.name).where(Clinic.health_center_id == center_id,
                                                                   Clinic.id.in_(ids))).all()
    return dict(rows)


def department_info(center_id, department_ids):
    """department_id -> {name, environment, type_code, color} (including inactive departments)."""
    ids = sorted({d for d in department_ids if d})
    if not ids:
        return {}
    rows = db.session.execute(
        select(Department.id, Department.name, Department.color, DepartmentType.environment, DepartmentType.code,
               DepartmentType.name_en, DepartmentType.name_ar, DepartmentType.color)
        .join(DepartmentType, DepartmentType.id == Department.department_type_id)
        .where(Department.health_center_id == center_id, Department.id.in_(ids))).all()
    return {r[0]: {"name": r[1], "color": r[2] or r[7], "environment": r[3], "type_code": r[4],
                   "name_en": r[5], "name_ar": r[6]} for r in rows}


def accessible_clinics(p, clinic_ids=None):
    """Compact list of the principal's accessible clinics (optionally restricted to ids), with
    department name/environment. Used by meta endpoints so forms can offer choices."""
    ids = sorted(p.clinic_ids if clinic_ids is None else set(clinic_ids) & set(p.clinic_ids))
    if not ids:
        return []
    rows = db.session.execute(
        select(Clinic.id, Clinic.name, Clinic.location, Clinic.department_id)
        .where(Clinic.health_center_id == p.center_id, Clinic.id.in_(ids)).order_by(Clinic.name)).all()
    depts = department_info(p.center_id, [r[3] for r in rows])
    return [{"id": r[0], "name": r[1], "location": r[2], "department_id": r[3],
             "department_name": depts.get(r[3], {}).get("name"),
             "environment": p.department_env.get(r[3], depts.get(r[3], {}).get("environment"))} for r in rows]
