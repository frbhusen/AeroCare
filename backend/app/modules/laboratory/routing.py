"""Helpers shared by the laboratory and radiology modules: resolving target service departments
(by environment) across the whole center, and the processing-side scope of a principal.

A requester may address a laboratory/radiology department that is outside their own scope, so
target departments are resolved from the center's active structure (never from client-chosen
tenant ids) instead of the principal's scope maps.
"""
from sqlalchemy import select

from backend.app.authz.principal import active_structure
from backend.app.core.errors import NotFound, ValidationError
from backend.app.extensions import db
from backend.app.models import Clinic, Department


def env_structure(center_id, env):
    """{department_id: [clinic_id, ...]} for active departments of `env` (and their active clinics)."""
    clinic_dept, dept_env = active_structure(center_id)
    out = {d: [] for d, e in dept_env.items() if e == env}
    for c, d in clinic_dept.items():
        if d in out:
            out[d].append(c)
    for d in out:
        out[d].sort()
    return out


def env_options(center_id, env):
    """Departments + clinics of an environment, with names (for request forms)."""
    struct = env_structure(center_id, env)
    if not struct:
        return []
    names = dict(db.session.execute(select(Department.id, Department.name)
                                    .where(Department.health_center_id == center_id,
                                           Department.id.in_(list(struct)))).all())
    cl_ids = [c for cs in struct.values() for c in cs]
    cnames = dict(db.session.execute(select(Clinic.id, Clinic.name).where(Clinic.health_center_id == center_id,
                                                                          Clinic.id.in_(cl_ids or [-1]))).all())
    return [{"id": d, "name": names.get(d), "clinics": [{"id": c, "name": cnames.get(c)} for c in cs]}
            for d, cs in sorted(struct.items())]


def resolve_target(center_id, env, department_id=None, clinic_id=None, label="laboratory"):
    """Validate a target service department/clinic; returns (department_id, clinic_id_or_None, clinic_ids)."""
    struct = env_structure(center_id, env)
    if clinic_id is not None:
        dept = next((d for d, cs in struct.items() if clinic_id in cs), None)
        if dept is None or (department_id is not None and dept != department_id):
            raise ValidationError(f"Unknown {label} clinic.", details={f"{label}_clinic_id": "is invalid"})
        return dept, clinic_id, struct[dept]
    if department_id is None:
        if len(struct) == 1:
            department_id = next(iter(struct))
        elif not struct:
            raise ValidationError(f"This health center has no active {label} department.", code=f"no_{label}")
        else:
            raise ValidationError("Choose a department.", details={f"{label}_department_id": "is required"})
    if department_id not in struct:
        raise ValidationError(f"Unknown {label} department.", details={f"{label}_department_id": "is invalid"})
    cs = struct[department_id]
    return department_id, (cs[0] if len(cs) == 1 else None), cs


def processing_clinics(p, env):
    """Clinics in the principal's scope that belong to departments of `env`."""
    return sorted(c for c, d in p.clinic_department.items() if p.department_env.get(d) == env)


def processing_departments(p, env):
    """Service departments where the principal works (has a clinic in scope or manages it)."""
    depts = {d for d, e in p.department_env.items() if e == env and
             (p.can_department(d) or any(p.clinic_department.get(c) == d for c in p.clinic_ids))}
    return depts


def requesting_clinic_for(p, clinic_id, perm):
    """The requesting clinic: explicit (must be in scope) or the principal's only clinic."""
    if clinic_id is None:
        if len(p.clinic_ids) == 1 and not p.center_wide:
            clinic_id = next(iter(p.clinic_ids))
        elif p.role == "department_manager" and p.user.clinic_id and p.can_clinic(p.user.clinic_id):
            clinic_id = p.user.clinic_id
        else:
            raise ValidationError("Choose the requesting clinic.", details={"requesting_clinic_id": "is required"})
    if not p.can_clinic(clinic_id):
        raise NotFound("Clinic not found")
    p.require(perm, clinic_id=clinic_id)
    return clinic_id, p.clinic_department[clinic_id]
