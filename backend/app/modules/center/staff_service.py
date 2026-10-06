"""Staff accounts of a health center (spec §6, §9-11, §100).

Who manages whom:
* Health Center Manager (or Superadmin support view): doctors, department managers, receptionists
  anywhere in the center. Center managers themselves are managed from the Superadmin portal.
* Department manager: doctors of clinics in their department and receptionists whose every
  scope lies inside their department. Never managers, never center-wide receptionists.
Visibility (staff.view) follows the principal's departments/clinics; out of scope => 404.
"""
from sqlalchemy import Integer, false, literal, or_, select, true, update
from sqlalchemy.exc import IntegrityError

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import (PHONE_RE, Bool, Enum, Id, Int, List, Obj, Str, query_args, validate)
from backend.app.extensions import db
from backend.app.models import Clinic, Department, User, UserScope
from backend.app.services import accounts, audit

from .common import is_center_level, lock_center, revoke_sessions, user_department_id

STAFF_ROLES = ("department_manager", "doctor", "receptionist")
SCOPE_SCHEMA = Obj({"type": Enum(["center", "department", "clinic"], required=True), "id": Id()})


# ---------------------------------------------------------------- scope helpers
def _clinic_depts(center_id, clinic_ids=None):
    stmt = select(Clinic.id, Clinic.department_id).where(Clinic.health_center_id == center_id)
    if clinic_ids is not None:
        stmt = stmt.where(Clinic.id.in_(list(clinic_ids) or [-1]))
    return dict(db.session.execute(stmt).all())


def _managed_clinic_ids(p):
    """All clinics (incl. inactive) of departments the principal manages."""
    m = sorted(p.managed_department_ids)
    if not m:
        return set()
    return set(db.session.execute(select(Clinic.id).where(Clinic.health_center_id == p.center_id,
                                                          Clinic.department_id.in_(m))).scalars())


def scope_clause(p):
    if p.center_wide:
        return true()
    depts = sorted(p.visible_department_ids | p.managed_department_ids) or [-1]
    clinics = sorted(set(p.clinic_ids) | _managed_clinic_ids(p)) or [-1]
    rec = select(UserScope.user_id).where(or_(UserScope.department_id.in_(depts), UserScope.clinic_id.in_(clinics)))
    return or_(User.id == p.user.id,
               (User.role == "doctor") & User.clinic_id.in_(clinics),
               (User.role == "department_manager") & User.department_id.in_(depts),
               (User.role == "receptionist") & User.id.in_(rec))


def _scopes_of(user_ids):
    out = {}
    rows = db.session.execute(select(UserScope).where(UserScope.user_id.in_(list(user_ids) or [-1]))
                              .order_by(UserScope.id)).scalars()
    for s in rows:
        out.setdefault(s.user_id, []).append(s)
    return out


def can_manage(p, u, scopes=None, clinic_depts=None):
    if u.id == p.user.id or u.role not in STAFF_ROLES:
        return False
    if is_center_level(p):
        return True
    managed = p.managed_department_ids
    if not managed or u.role == "department_manager":
        return False
    if clinic_depts is None:
        clinic_depts = _clinic_depts(p.center_id)
    if u.role == "doctor":
        return clinic_depts.get(u.clinic_id) in managed
    scopes = scopes if scopes is not None else _scopes_of([u.id]).get(u.id, [])
    if not scopes:
        return False
    for s in scopes:
        if s.department_id is None and s.clinic_id is None:
            return False
        dept = s.department_id if s.department_id is not None else clinic_depts.get(s.clinic_id)
        if dept not in managed:
            return False
    return True


# ---------------------------------------------------------------- serialization
def staff_json(u, p, scopes=None, clinic_depts=None, names=None, heads=None):
    names = names or {}
    scopes = scopes or []
    return {"id": u.id, "username": u.username, "name": u.name, "email": u.email,
            "email_is_generated": u.email_is_generated, "role": u.role, "status": u.status,
            "clinic_id": u.clinic_id, "clinic_name": names.get(("c", u.clinic_id)),
            "department_id": u.department_id if u.role == "department_manager" else
            (clinic_depts or {}).get(u.clinic_id),
            "department_name": names.get(("d", u.department_id if u.role == "department_manager" else
                                          (clinic_depts or {}).get(u.clinic_id))),
            "phone": u.phone, "specialty_title": u.specialty_title, "is_head": u.id in (heads or set()),
            "scopes": [_scope_json(s, names) for s in scopes] if u.role == "receptionist" else [],
            "last_login_at": iso(u.last_login_at), "created_at": iso(u.created_at), "version": u.version,
            "can_manage": can_manage(p, u, scopes, clinic_depts)}


def _scope_json(s, names):
    if s.clinic_id is not None:
        return {"type": "clinic", "id": s.clinic_id, "name": names.get(("c", s.clinic_id))}
    if s.department_id is not None:
        return {"type": "department", "id": s.department_id, "name": names.get(("d", s.department_id))}
    return {"type": "center", "id": None, "name": None}


def _names(center_id):
    out = {("c", i): n for i, n in db.session.execute(select(Clinic.id, Clinic.name).where(
        Clinic.health_center_id == center_id)).all()}
    out.update({("d", i): n for i, n in db.session.execute(select(Department.id, Department.name).where(
        Department.health_center_id == center_id)).all()})
    return out


def _heads(center_id):
    return set(db.session.execute(select(Department.head_user_id).where(
        Department.health_center_id == center_id, Department.head_user_id.isnot(None))).scalars())


def serialize_many(p, users):
    scopes = _scopes_of([u.id for u in users])
    cd, names, heads = _clinic_depts(p.center_id), _names(p.center_id), _heads(p.center_id)
    return [staff_json(u, p, scopes.get(u.id, []), cd, names, heads) for u in users]


def detail(p, u):
    return serialize_many(p, [u])[0]


# ---------------------------------------------------------------- queries
def list_staff(p):
    p.require("staff.view")
    a = query_args({"role": Enum(("center_manager",) + STAFF_ROLES), "status": Enum(["active", "archived"]),
                    "department_id": Id(), "clinic_id": Id(), "q": Str(max_len=100)})
    stmt = select(User).where(User.health_center_id == p.center_id, scope_clause(p)).order_by(User.name, User.id)
    if a.get("role"):
        stmt = stmt.where(User.role == a["role"])
    if a.get("status"):
        stmt = stmt.where(User.status == a["status"])
    if a.get("clinic_id"):
        rec = select(UserScope.user_id).where(UserScope.clinic_id == a["clinic_id"])
        stmt = stmt.where(or_(User.clinic_id == a["clinic_id"], User.id.in_(rec)))
    if a.get("department_id"):
        dept = a["department_id"]
        clinics = select(Clinic.id).where(Clinic.health_center_id == p.center_id, Clinic.department_id == dept)
        rec = select(UserScope.user_id).where(or_(UserScope.department_id == dept, UserScope.clinic_id.in_(clinics)))
        stmt = stmt.where(or_(User.clinic_id.in_(clinics) & (User.role == "doctor"),
                              (User.role == "department_manager") & (User.department_id == dept),
                              User.id.in_(rec)))
    if a.get("q"):
        like = f"%{a['q'].replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.username.ilike(like), User.email.ilike(like)))
    out = paginate(db.session, stmt, lambda u: u, default_per_page=50)
    out["items"] = serialize_many(p, out["items"])
    return out


def get_staff(p, user_id):
    p.require("staff.view")
    u = db.session.execute(select(User).where(User.id == user_id, User.health_center_id == p.center_id,
                                              scope_clause(p))).scalar_one_or_none()
    if u is None:
        raise NotFound("Staff member not found")
    return u


def _manageable(p, user_id, perm):
    p.require("staff.view")
    u = get_staff(p, user_id)
    p.require(perm)
    if not can_manage(p, u):
        raise Forbidden("You cannot manage this account.")
    return u


def meta(p):
    """Form choices for the staff screens, already restricted to what p may assign."""
    p.require("staff.view")
    center_level = is_center_level(p)
    depts = db.session.execute(select(Department).where(p.tenant(Department), Department.live())
                               .order_by(Department.name)).scalars().all()
    if not center_level:
        depts = [d for d in depts if d.id in p.managed_department_ids]
    clinics = db.session.execute(select(Clinic).where(p.tenant(Clinic), Clinic.live(),
                                                      Clinic.department_id.in_([d.id for d in depts] or [-1]))
                                 .order_by(Clinic.name)).scalars().all()
    roles = list(STAFF_ROLES) if center_level else ["doctor", "receptionist"]
    return {"roles": roles if p.has("staff.create") else [],
            "scope_types": (["center", "department", "clinic"] if center_level else ["department", "clinic"]),
            "departments": [{"id": d.id, "name": d.name, "has_head": d.head_user_id is not None} for d in depts],
            "clinics": [{"id": c.id, "name": c.name, "department_id": c.department_id, "is_active": c.is_active}
                        for c in clinics],
            "can_reset_passwords": center_level}


# ---------------------------------------------------------------- validation of assignments
def _assignable_clinic(p, clinic_id):
    c = db.session.execute(select(Clinic).where(Clinic.id == clinic_id, p.tenant(Clinic), Clinic.live())
                           ).scalar_one_or_none()
    if c is None or not (is_center_level(p) or c.department_id in p.managed_department_ids):
        raise ValidationError("Invalid input", details={"clinic_id": "unknown clinic or outside your scope"})
    return c


def _assignable_department(p, dept_id):
    d = db.session.execute(select(Department).where(Department.id == dept_id, p.tenant(Department),
                                                    Department.live())).scalar_one_or_none()
    if d is None or not (is_center_level(p) or d.id in p.managed_department_ids):
        raise ValidationError("Invalid input", details={"department_id": "unknown department or outside your scope"})
    return d


def _resolve_scopes(p, raw):
    if not raw:
        raise ValidationError("Invalid input", details={"scopes": "at least one scope is required"})
    out = set()
    for s in raw:
        if s["type"] == "center":
            if not is_center_level(p):
                raise ValidationError("Invalid input", details={"scopes": "center-wide scope is not allowed"})
            return [(None, None)]
        if not s.get("id"):
            raise ValidationError("Invalid input", details={"scopes": f"{s['type']} scope requires an id"})
        if s["type"] == "department":
            out.add((_assignable_department(p, s["id"]).id, None))
        else:
            out.add((None, _assignable_clinic(p, s["id"]).id))
    return sorted(out, key=lambda x: (x[0] or 0, x[1] or 0))


def _other_manager(center_id, dept_id, exclude_id=None):
    stmt = select(User.id).where(User.health_center_id == center_id, User.role == "department_manager",
                                 User.department_id == dept_id, User.status == "active")
    if exclude_id:
        stmt = stmt.where(User.id != exclude_id)
    return db.session.execute(stmt).first() is not None


def _audit(p, u, action, fields=None):
    audit.log_change(p, "user", action, "user", u.id, f"{u.name} ({u.username})",
                     department_id=user_department_id(u), changed_fields=fields)


# ---------------------------------------------------------------- create / edit
def create_staff(p, body):
    p.require("staff.create")
    data = validate(body, {
        "role": Enum(STAFF_ROLES, required=True), "username": Str(required=True, max_len=50),
        "name": Str(required=True, max_len=200), "password": Str(required=True, strip=False, max_len=200),
        "email": Str(max_len=255), "phone": Str(max_len=40, pattern=PHONE_RE), "specialty_title": Str(max_len=150),
        "clinic_id": Id(), "department_id": Id(), "scopes": List(SCOPE_SCHEMA, max_items=50)})
    role = data["role"]
    if role == "department_manager" and not is_center_level(p):
        raise Forbidden("Only the health center manager can create department managers.")
    clinic_id = dept = None
    scopes = []
    if role == "doctor":
        if not data.get("clinic_id"):
            raise ValidationError("Invalid input", details={"clinic_id": "a doctor must belong to exactly one clinic"})
        clinic_id = _assignable_clinic(p, data["clinic_id"]).id
    elif role == "department_manager":
        if not data.get("department_id"):
            raise ValidationError("Invalid input", details={"department_id": "is required"})
        dept = _assignable_department(p, data["department_id"])
        if data.get("clinic_id"):
            c = _assignable_clinic(p, data["clinic_id"])
            if c.department_id != dept.id:
                raise ValidationError("Invalid input", details={"clinic_id": "must belong to the department"})
            clinic_id = c.id
    else:
        scopes = _resolve_scopes(p, data.get("scopes"))
    lock_center(p.center_id)
    if role == "department_manager":
        if _other_manager(p.center_id, dept.id):
            raise Conflict("This department already has a department manager.", code="department_has_manager")
        if dept.head_user_id is None:
            accounts.check_limit(p.center_id, "max_head_doctors")
    else:
        accounts.check_limit(p.center_id, accounts.role_limit_key(role))
    u = accounts.create_user_record(center_id=p.center_id, username=data["username"], name=data["name"], role=role,
                                    password=data["password"], email=data.get("email"), clinic_id=clinic_id,
                                    department_id=dept.id if dept else None, phone=data.get("phone"),
                                    specialty_title=data.get("specialty_title"), must_change_password=True)
    for d_id, c_id in scopes:
        db.session.add(UserScope(health_center_id=p.center_id, user_id=u.id, department_id=d_id, clinic_id=c_id))
    if dept is not None and dept.head_user_id is None:
        dept.head_user_id = u.id
    db.session.flush()
    _audit(p, u, "create")
    db.session.commit()
    return u


def update_staff(p, user_id, body):
    u = _manageable(p, user_id, "staff.edit")
    data = validate(body, {"name": Str(max_len=200, nullable=False), "username": Str(max_len=50, nullable=False),
                           "email": Str(max_len=255), "reset_email": Bool(), "phone": Str(max_len=40, pattern=PHONE_RE),
                           "specialty_title": Str(max_len=150), "version": Int()}, partial=True)
    check_version(u, data.get("version"))
    changed = []
    if "name" in data:
        if not data["name"]:
            raise ValidationError("Invalid input", details={"name": "is required"})
        if data["name"] != u.name:
            u.name = data["name"]
            changed.append("name")
    for k in ("phone", "specialty_title"):
        if k in data and data[k] != getattr(u, k):
            setattr(u, k, data[k])
            changed.append(k)
    old = (u.username, u.email)
    accounts.apply_identity_change(u, username=data.get("username"), email=data.get("email") or None,
                                   reset_email_to_generated=bool(data.get("reset_email")))
    changed += [f for f, a, b in (("username", old[0], u.username), ("email", old[1], u.email)) if a != b]
    if changed:
        _audit(p, u, "edit", changed)
    db.session.commit()
    return u


def reassign_doctor(p, user_id, body):
    """Move a doctor to another clinic: access switches immediately (sessions are revoked so the
    client reloads its scope); history stays with the old clinic."""
    u = _manageable(p, user_id, "staff.edit")
    if u.role != "doctor":
        raise ValidationError("Only doctors can be reassigned to another clinic.", code="not_a_doctor")
    data = validate(body, {"clinic_id": Id(required=True), "version": Int()})
    if data.get("version") is not None:
        check_version(u, data["version"])
    c = _assignable_clinic(p, data["clinic_id"])
    if c.id != u.clinic_id:
        u.clinic_id = c.id
        revoke_sessions(u.id, "scope_changed")
        _audit(p, u, "edit", ["clinic_id"])
    db.session.commit()
    return u


def set_scopes(p, user_id, body):
    u = _manageable(p, user_id, "staff.edit")
    if u.role != "receptionist":
        raise ValidationError("Only receptionists have scope assignments.", code="not_a_receptionist")
    data = validate(body, {"scopes": List(SCOPE_SCHEMA, required=True, max_items=50)})
    new = _resolve_scopes(p, data["scopes"])
    current = db.session.execute(select(UserScope).where(UserScope.user_id == u.id)).scalars().all()
    if sorted(((s.department_id, s.clinic_id) for s in current), key=lambda x: (x[0] or 0, x[1] or 0)) != new:
        for s in current:
            db.session.delete(s)
        db.session.flush()
        for d_id, c_id in new:
            db.session.add(UserScope(health_center_id=p.center_id, user_id=u.id, department_id=d_id, clinic_id=c_id))
        u.updated_at = utcnow()
        revoke_sessions(u.id, "scope_changed")
        db.session.flush()
        _audit(p, u, "edit", ["scopes"])
    db.session.commit()
    return u


# ---------------------------------------------------------------- status / password / delete
def _archive(p, u):
    db.session.execute(update(Department).where(Department.health_center_id == p.center_id,
                                                Department.head_user_id == u.id).values(head_user_id=None))
    u.status = "archived"
    revoke_sessions(u.id, "archived")


def archive_staff(p, user_id):
    u = _manageable(p, user_id, "staff.delete")
    if u.status != "archived":
        _archive(p, u)
        _audit(p, u, "edit", ["status"])
        db.session.commit()
    return u


def reactivate_staff(p, user_id):
    u = _manageable(p, user_id, "staff.edit")
    if u.status == "active":
        return u
    lock_center(p.center_id)
    if u.role == "department_manager":
        if _other_manager(p.center_id, u.department_id, exclude_id=u.id):
            raise Conflict("This department already has an active department manager.",
                           code="department_has_manager")
    else:
        accounts.check_limit(p.center_id, accounts.role_limit_key(u.role))
    if u.role == "doctor":
        live = db.session.execute(select(Clinic.id).where(Clinic.id == u.clinic_id, p.tenant(Clinic), Clinic.live())
                                  ).first()
        if not live:
            raise ValidationError("Reassign the doctor to an existing clinic first.", code="clinic_missing")
    u.status = "active"
    _audit(p, u, "edit", ["status"])
    db.session.commit()
    return u


def reset_password(p, user_id, body):
    """Health Center Manager only (spec §7). Center managers are reset by the Superadmin."""
    from backend.app.auth.service import hash_password, validate_password
    p.require_center_manager()
    p.require("staff.edit")
    u = get_staff(p, user_id)
    if u.id == p.user.id or u.role not in STAFF_ROLES:
        raise Forbidden("This password must be changed from the account itself or by the platform administrator.")
    data = validate(body, {"password": Str(required=True, strip=False, max_len=200)})
    validate_password(data["password"], u.username)
    u.password_hash = hash_password(data["password"])
    u.password_changed_at = utcnow()
    u.must_change_password = True  # chosen by the manager: the staff member must set their own
    revoke_sessions(u.id, "password_reset")
    _audit(p, u, "edit", ["password"])
    db.session.commit()


# Tables whose user references are not "history" (cleaned up with the account).
_NON_HISTORY = {"users", "user_scopes", "user_permissions", "user_sessions", "notifications",
                "offline_sync_operations", "login_attempts", "audit_logs", "deletion_buffer",
                "health_center_departments"}


def _is_user_ref(col):
    if col.name == "health_center_id" or not isinstance(col.type, Integer):
        return False
    if any(fk.column.table.name == "users" and fk.column.name == "id" for fk in col.foreign_keys):
        return True
    n = col.name
    return n == "user_id" or n.endswith("_user_id") or n.endswith("_by") or n.endswith("_by_id") or n == "doctor_id"


def user_referenced(center_id, user_id):
    for t in db.metadata.sorted_tables:
        if t.name in _NON_HISTORY:
            continue
        cols = [c for c in t.c if _is_user_ref(c)]
        if not cols:
            continue
        stmt = select(literal(1)).select_from(t).where(or_(*[c == user_id for c in cols]))
        if "health_center_id" in t.c:
            stmt = stmt.where(t.c.health_center_id == center_id)
        if db.session.execute(stmt.limit(1)).first():
            return t.name
    return None


def delete_staff(p, user_id):
    """Hard delete only if the account was never referenced by history; otherwise archive."""
    u = _manageable(p, user_id, "staff.delete")
    ref = user_referenced(p.center_id, u.id)
    if ref is None:
        label, uid, dept = f"{u.name} ({u.username})", u.id, user_department_id(u)
        db.session.execute(update(Department).where(Department.health_center_id == p.center_id,
                                                    Department.head_user_id == u.id).values(head_user_id=None))
        sp = db.session.begin_nested()
        try:
            db.session.delete(u)
            db.session.flush()
            sp.commit()
        except IntegrityError:
            sp.rollback()
            ref = "constraint"
        else:
            audit.log_change(p, "user", "delete", "user", uid, label, department_id=dept)
            db.session.commit()
            return {"deleted": True, "archived": False}
        u = get_staff(p, user_id)
    if u.status != "archived":
        _archive(p, u)
        _audit(p, u, "edit", ["status"])
    db.session.commit()
    return {"deleted": False, "archived": True, "reason": "referenced", "referenced_by": ref}
