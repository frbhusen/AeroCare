"""Departments and clinics of a health center.

Departments can only be created from module types the Superadmin activated (one per type,
plan `max_departments`). The Health Center Manager manages all of them; a department manager
manages only their own department and its clinics. Deletion (30 s undo) is allowed only when
nothing references the department/clinic; otherwise deactivate it.
"""
import re

from sqlalchemy import func, literal, select
from sqlalchemy.exc import IntegrityError

from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.validation import COLOR_RE, EMAIL_RE, PHONE_RE, Bool, Id, Int, JsonDict, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Department, DepartmentType, HealthCenterModule, User
from backend.app.services import accounts, audit, deletion
from backend.app.services.centers import active_module_type_ids

from .common import is_center_level, lock_center

deletion.register("department", Department)
deletion.register("clinic", Clinic)

DAYS = ("sat", "sun", "mon", "tue", "wed", "thu", "fri")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------------------------------------------------------------- helpers
def references(column, value, center_id, skip):
    """Name of the first table (other than `skip`) holding a row whose `column` == value."""
    for t in db.metadata.sorted_tables:
        if t.name in skip or column not in t.c:
            continue
        stmt = select(literal(1)).select_from(t).where(t.c[column] == value)
        if "health_center_id" in t.c:
            stmt = stmt.where(t.c.health_center_id == center_id)
        if db.session.execute(stmt.limit(1)).first():
            return t.name
    return None


def validate_working_hours(value):
    """{"sat": [["09:00","13:00"], ["16:00","20:00"]], ...}; missing day = closed."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("Invalid input", details={"working_hours": "must be an object keyed by day"})
    out = {}
    for day, intervals in value.items():
        if day not in DAYS:
            raise ValidationError("Invalid input", details={"working_hours": f"unknown day '{day}' (use {', '.join(DAYS)})"})
        if not isinstance(intervals, list) or len(intervals) > 4:
            raise ValidationError("Invalid input", details={"working_hours": f"{day}: list of at most 4 intervals"})
        clean, prev_end = [], None
        for iv in sorted(intervals, key=lambda x: str(x[0]) if isinstance(x, (list, tuple)) and x else ""):
            if (not isinstance(iv, (list, tuple)) or len(iv) != 2 or not all(isinstance(x, str) for x in iv)
                    or not all(_HHMM.match(x) for x in iv)):
                raise ValidationError("Invalid input", details={"working_hours": f"{day}: intervals are [\"HH:MM\", \"HH:MM\"]"})
            if iv[0] >= iv[1]:
                raise ValidationError("Invalid input", details={"working_hours": f"{day}: start must be before end"})
            if prev_end and iv[0] < prev_end:
                raise ValidationError("Invalid input", details={"working_hours": f"{day}: intervals overlap"})
            prev_end = iv[1]
            clean.append([iv[0], iv[1]])
        out[day] = clean
    return out


def _type_json(t):
    return {"id": t.id, "code": t.code, "name_en": t.name_en, "name_ar": t.name_ar, "environment": t.environment,
            "icon": t.icon, "color": t.color, "is_custom": t.is_custom}


def department_json(d, p, clinic_counts=None, heads=None, active_types=None):
    head = (heads or {}).get(d.head_user_id)
    return {"id": d.id, "name": d.name, "color": d.color or d.department_type.color,
            "type": _type_json(d.department_type), "environment": d.environment,
            "head": {"id": d.head_user_id, "name": head} if d.head_user_id else None,
            "is_active": d.is_active, "module_active": (d.department_type_id in active_types)
            if active_types is not None else None,
            "settings": d.settings or {}, "clinic_count": (clinic_counts or {}).get(d.id, 0), "version": d.version,
            "can_manage": is_center_level(p) or p.can_department(d.id)}


def clinic_json(c, p, dept_names=None):
    return {"id": c.id, "department_id": c.department_id, "department_name": (dept_names or {}).get(c.department_id),
            "name": c.name, "location": c.location, "phone": c.phone, "email": c.email,
            "working_hours": c.working_hours or {}, "settings": c.settings or {}, "notes": c.notes,
            "is_active": c.is_active, "version": c.version,
            "can_manage": is_center_level(p) or p.can_department(c.department_id)}


# ---------------------------------------------------------------- departments
def get_department(p, dept_id, manage=False):
    d = db.session.execute(select(Department).where(Department.id == dept_id, p.tenant(Department),
                                                    Department.live())).scalar_one_or_none()
    if d is None:
        raise NotFound("Department not found")
    if not is_center_level(p):
        ok = p.can_department(d.id) if manage else (p.sees_department(d.id) or p.can_department(d.id))
        if not ok:
            raise NotFound("Department not found")
    return d


def _dept_extras(p, depts):
    ids = [d.id for d in depts] or [-1]
    counts = dict(db.session.execute(select(Clinic.department_id, func.count()).where(
        p.tenant(Clinic), Clinic.live(), Clinic.department_id.in_(ids)).group_by(Clinic.department_id)).all())
    head_ids = [d.head_user_id for d in depts if d.head_user_id] or [-1]
    heads = dict(db.session.execute(select(User.id, User.name).where(User.health_center_id == p.center_id,
                                                                     User.id.in_(head_ids))).all())
    return counts, heads, active_module_type_ids(p.center_id)


def department_detail(p, d):
    counts, heads, types = _dept_extras(p, [d])
    return department_json(d, p, counts, heads, types)


def list_departments(p):
    p.require("settings.view")
    stmt = select(Department).where(p.tenant(Department), Department.live()).order_by(Department.name)
    if not is_center_level(p):
        stmt = stmt.where(Department.id.in_(sorted(p.visible_department_ids | p.managed_department_ids) or [-1]))
    depts = db.session.execute(stmt).scalars().all()
    counts, heads, types = _dept_extras(p, depts)
    return {"items": [department_json(d, p, counts, heads, types) for d in depts]}


def department_meta(p):
    """Module types activated for this center (choices for 'create department')."""
    p.require("settings.view")
    active = active_module_type_ids(p.center_id)
    types = db.session.execute(select(DepartmentType).where(DepartmentType.id.in_(sorted(active) or [-1]),
                                                            DepartmentType.is_active.is_(True))
                               .order_by(DepartmentType.sort_order)).scalars().all()
    existing = dict(db.session.execute(select(Department.department_type_id, Department.id).where(
        p.tenant(Department))).all())
    use = accounts.usage(p.center_id)
    from backend.app.models import HealthCenter
    c = db.session.get(HealthCenter, p.center_id)
    return {"types": [{**_type_json(t), "department_id": existing.get(t.id), "available": t.id not in existing}
                      for t in types],
            "limits": {"max_departments": c.max_departments, "used_departments": use["max_departments"],
                       "max_clinics": c.max_clinics, "used_clinics": use["max_clinics"],
                       "max_head_doctors": c.max_head_doctors, "used_head_doctors": use["max_head_doctors"]},
            "days": list(DAYS)}


def create_department(p, body):
    p.require_center_manager()
    p.require("settings.edit")
    data = validate(body, {"department_type_id": Id(required=True), "name": Str(max_len=150),
                           "color": Str(pattern=COLOR_RE), "settings": JsonDict()})
    t = db.session.get(DepartmentType, data["department_type_id"])
    if t is None or not t.is_active or t.id not in active_module_type_ids(p.center_id):
        raise ValidationError("This department type is not activated for your health center.",
                              code="module_not_active", details={"department_type_id": "not activated"})
    lock_center(p.center_id)
    existing = db.session.execute(select(Department).where(p.tenant(Department),
                                                           Department.department_type_id == t.id)).scalar_one_or_none()
    if existing is not None:
        code = "department_pending_delete" if existing.pending_delete_until else "department_exists"
        raise Conflict("This health center already has a department of this type.", code=code)
    accounts.check_limit(p.center_id, "max_departments")
    d = Department(health_center_id=p.center_id, department_type_id=t.id, name=data.get("name") or t.name_en,
                   color=data.get("color"), settings=data.get("settings") or {}, is_active=True)
    db.session.add(d)
    db.session.flush()
    audit.log_change(p, "department", "create", "department", d.id, d.name, department_id=d.id)
    db.session.commit()
    return department_detail(p, d)


def update_department(p, dept_id, body):
    p.require("settings.edit")
    d = get_department(p, dept_id, manage=True)
    data = validate(body, {"name": Str(max_len=150, nullable=False), "color": Str(pattern=COLOR_RE),
                           "settings": JsonDict(), "is_active": Bool(nullable=False), "version": Int()}, partial=True)
    check_version(d, data.pop("version", None))
    if "is_active" in data and not is_center_level(p):
        raise ValidationError("Only the health center manager can activate or deactivate departments.",
                              code="forbidden_field", details={"is_active": "not allowed"})
    if "name" in data and not data["name"]:
        raise ValidationError("Invalid input", details={"name": "is required"})
    if "settings" in data:
        data["settings"] = data["settings"] or {}
    changed = [k for k, v in data.items() if getattr(d, k) != v]
    for k in changed:
        setattr(d, k, data[k])
    if changed:
        audit.log_change(p, "department", "edit", "department", d.id, d.name, department_id=d.id,
                         changed_fields=changed)
    db.session.commit()
    return department_detail(p, d)


def set_head(p, dept_id, body):
    """Assign/remove the head doctor. The head must be an active department_manager of this
    department; one head per department (plan max_head_doctors)."""
    p.require_center_manager()
    p.require("staff.edit")
    d = get_department(p, dept_id, manage=True)
    data = validate(body, {"user_id": Id()})
    uid = data.get("user_id")
    if uid == d.head_user_id:
        return department_detail(p, d)
    if uid:
        u = db.session.execute(select(User).where(User.id == uid, User.health_center_id == p.center_id)
                               ).scalar_one_or_none()
        if u is None:
            raise NotFound("User not found")
        if u.role != "department_manager" or u.department_id != d.id or u.status != "active":
            raise ValidationError("The head doctor must be an active department manager of this department.",
                                  code="invalid_head", details={"user_id": "not a manager of this department"})
        if d.head_user_id is None:
            lock_center(p.center_id)
            accounts.check_limit(p.center_id, "max_head_doctors")
    d.head_user_id = uid
    audit.log_change(p, "department", "edit", "department", d.id, d.name, department_id=d.id,
                     changed_fields=["head_user_id"])
    db.session.commit()
    return department_detail(p, d)


def delete_department(p, dept_id):
    p.require_center_manager()
    p.require("settings.edit")
    d = get_department(p, dept_id, manage=True)
    ref = references("department_id", d.id, p.center_id,
                     skip={"health_center_departments", "audit_logs", "user_scopes", "deletion_buffer"})
    if ref:
        raise Conflict("This department still has clinics, staff or records. Remove them or deactivate the "
                       "department instead.", code="department_in_use", details={"referenced_by": ref})
    audit.log_change(p, "department", "delete", "department", d.id, d.name, department_id=d.id)
    return deletion.stage(p, d, "department", label=d.name)


# ---------------------------------------------------------------- clinics
def _clinic_scope(p, stmt):
    if is_center_level(p):
        return stmt
    return stmt.where((Clinic.department_id.in_(sorted(p.managed_department_ids) or [-1]))
                      | Clinic.id.in_(sorted(p.clinic_ids) or [-1]))


def get_clinic(p, clinic_id, manage=False):
    c = db.session.execute(_clinic_scope(p, select(Clinic).where(Clinic.id == clinic_id, p.tenant(Clinic),
                                                                 Clinic.live()))).scalar_one_or_none()
    if c is None:
        raise NotFound("Clinic not found")
    if manage and not (is_center_level(p) or p.can_department(c.department_id)):
        raise NotFound("Clinic not found") if not p.can_clinic(c.id) else _forbidden()
    return c


def _forbidden():
    from backend.app.core.errors import Forbidden
    return Forbidden("You cannot manage this clinic.")


def _dept_names(p):
    return dict(db.session.execute(select(Department.id, Department.name).where(p.tenant(Department))).all())


def list_clinics(p, args):
    p.require("settings.view")
    a = validate(dict(args), {"department_id": Id(), "include_inactive": Bool(), "q": Str(max_len=100)})
    stmt = _clinic_scope(p, select(Clinic).where(p.tenant(Clinic), Clinic.live())).order_by(Clinic.name)
    if a.get("department_id"):
        stmt = stmt.where(Clinic.department_id == a["department_id"])
    if a.get("include_inactive") is False:
        stmt = stmt.where(Clinic.is_active.is_(True))
    if a.get("q"):
        stmt = stmt.where(Clinic.name.ilike(f"%{a['q'].replace('%', '')}%"))
    names = _dept_names(p)
    return {"items": [clinic_json(c, p, names) for c in db.session.execute(stmt).scalars()]}


def clinic_detail(p, c):
    return clinic_json(c, p, _dept_names(p))


def _clinic_schema():
    return {"name": Str(max_len=150, nullable=False), "location": Str(max_len=200),
            "phone": Str(max_len=40, pattern=PHONE_RE), "email": Str(max_len=200, pattern=EMAIL_RE),
            "working_hours": JsonDict(max_keys=7), "settings": JsonDict(), "notes": Text(max_len=5000),
            "is_active": Bool(nullable=False)}


def _flush_clinic():
    try:
        db.session.flush()
    except IntegrityError as e:
        db.session.rollback()
        if "uq_clinic_name" in str(e.orig):
            raise Conflict("A clinic with this name already exists in this department.", code="clinic_name_taken")
        raise


def create_clinic(p, body):
    p.require("settings.edit")
    schema = _clinic_schema()
    schema["department_id"] = Id(required=True)
    data = validate(body, schema, partial=True)
    if not data.get("department_id"):
        raise ValidationError("Invalid input", details={"department_id": "is required"})
    if not data.get("name"):
        raise ValidationError("Invalid input", details={"name": "is required"})
    d = get_department(p, data["department_id"], manage=True)
    lock_center(p.center_id)
    accounts.check_limit(p.center_id, "max_clinics")
    c = Clinic(health_center_id=p.center_id, department_id=d.id, name=data["name"], location=data.get("location"),
               phone=data.get("phone"), email=data.get("email"),
               working_hours=validate_working_hours(data.get("working_hours")), settings=data.get("settings") or {},
               notes=data.get("notes"), is_active=data.get("is_active", True))
    db.session.add(c)
    _flush_clinic()
    audit.log_change(p, "clinic", "create", "clinic", c.id, c.name, department_id=d.id)
    db.session.commit()
    return clinic_detail(p, c)


def update_clinic(p, clinic_id, body):
    p.require("settings.edit")
    c = get_clinic(p, clinic_id, manage=True)
    schema = _clinic_schema()
    schema["version"] = Int()
    data = validate(body, schema, partial=True)
    check_version(c, data.pop("version", None))
    if "name" in data and not data["name"]:
        raise ValidationError("Invalid input", details={"name": "is required"})
    if "working_hours" in data:
        data["working_hours"] = validate_working_hours(data["working_hours"])
    if "settings" in data:
        data["settings"] = data["settings"] or {}
    changed = [k for k, v in data.items() if getattr(c, k) != v]
    for k in changed:
        setattr(c, k, data[k])
    _flush_clinic()
    if changed:
        audit.log_change(p, "clinic", "edit", "clinic", c.id, c.name, department_id=c.department_id,
                         changed_fields=changed)
    db.session.commit()
    return clinic_detail(p, c)


def delete_clinic(p, clinic_id):
    p.require("settings.edit")
    c = get_clinic(p, clinic_id, manage=True)
    ref = references("clinic_id", c.id, p.center_id, skip={"clinics", "audit_logs", "user_scopes", "deletion_buffer"})
    if ref:
        raise Conflict("This clinic has staff, patients or records. Deactivate it instead.", code="clinic_in_use",
                       details={"referenced_by": ref})
    audit.log_change(p, "clinic", "delete", "clinic", c.id, c.name, department_id=c.department_id)
    return deletion.stage(p, c, "clinic", label=c.name)
