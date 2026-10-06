"""Superadmin: plans, department types, platform users, audit logs, platform settings/branding."""
import base64
import hashlib
import re
from datetime import timedelta

from sqlalchemy import func, or_, select, update

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import local_day_bounds
from backend.app.core.validation import (COLOR_RE, PHONE_RE, Bool, Date, Enum, Id, Int, Str, query_args,
                                         validate)
from backend.app.extensions import db
from backend.app.models import (AuditLog, Department, DepartmentType, HealthCenter, HealthCenterModule, Plan,
                                PlatformSetting, User)
from backend.app.models.ops import AUDIT_CATEGORIES
from backend.app.models.users import ROLES
from backend.app.services import accounts, audit
from backend.app.services.centers import LIMIT_FIELDS

from .serializers import audit_json, department_type_json, plan_json, user_json

ICON_RE = r"[a-z0-9-]{1,50}"


# ---------------------------------------------------------------- plans
def list_plans():
    plans = db.session.execute(select(Plan).order_by(Plan.id)).scalars().all()
    used = dict(db.session.execute(select(HealthCenter.plan_id, func.count()).group_by(HealthCenter.plan_id)).all())
    return {"items": [{**plan_json(pl), "center_count": used.get(pl.id, 0)} for pl in plans]}


def _plan_schema():
    s = {f: Int(min_value=0, max_value=100000) for f in LIMIT_FIELDS}
    s.update({"code": Str(max_len=40, pattern=r"[a-z0-9_-]{2,40}", nullable=False),
              "name": Str(max_len=100, nullable=False), "is_active": Bool(nullable=False),
              "storage_quota_bytes": Int(min_value=1024 * 1024, max_value=2 ** 50)})
    return s


def create_plan(body):
    data = validate(body, _plan_schema(), partial=True)
    for k in ("code", "name"):
        if not data.get(k):
            raise ValidationError("Invalid input", details={k: "is required"})
    if db.session.execute(select(Plan.id).where(Plan.code == data["code"])).first():
        raise Conflict("A plan with this code already exists.", code="plan_code_taken")
    pl = Plan(**{k: v for k, v in data.items()})
    db.session.add(pl)
    db.session.commit()
    return plan_json(pl)


def update_plan(plan_id, body):
    pl = db.session.get(Plan, plan_id)
    if pl is None:
        raise NotFound("Plan not found")
    data = validate(body, _plan_schema(), partial=True)
    if "code" in data and data["code"] != pl.code and db.session.execute(
            select(Plan.id).where(Plan.code == data["code"])).first():
        raise Conflict("A plan with this code already exists.", code="plan_code_taken")
    for k, v in data.items():
        setattr(pl, k, v)
    db.session.commit()
    return plan_json(pl)


def delete_plan(plan_id):
    pl = db.session.get(Plan, plan_id)
    if pl is None:
        raise NotFound("Plan not found")
    if db.session.execute(select(HealthCenter.id).where(HealthCenter.plan_id == pl.id)).first():
        raise Conflict("This plan is assigned to health centers; deactivate it instead.", code="plan_in_use")
    db.session.delete(pl)
    db.session.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- department types
def list_department_types():
    types = db.session.execute(select(DepartmentType).order_by(DepartmentType.sort_order, DepartmentType.id)
                               ).scalars().all()
    used = dict(db.session.execute(select(HealthCenterModule.department_type_id, func.count()).where(
        HealthCenterModule.is_active.is_(True)).group_by(HealthCenterModule.department_type_id)).all())
    return {"items": [{**department_type_json(t), "center_count": used.get(t.id, 0)} for t in types]}


def _type_code(name):
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "custom"
    base = f"custom_{base}" if not base.startswith("custom_") else base
    code, n = base, 1
    while db.session.execute(select(DepartmentType.id).where(DepartmentType.code == code)).first():
        n += 1
        code = f"{base}_{n}"
    return code


def create_custom_type(body):
    """Custom department types always use the generic medical environment (spec §13, §32)."""
    data = validate(body, {"name_en": Str(required=True, max_len=100), "name_ar": Str(required=True, max_len=100),
                           "icon": Str(max_len=50, pattern=ICON_RE), "color": Str(pattern=COLOR_RE),
                           "sort_order": Int(min_value=0, max_value=100000)})
    t = DepartmentType(code=_type_code(data["name_en"]), name_en=data["name_en"], name_ar=data["name_ar"],
                       environment="generic", is_custom=True, icon=data.get("icon") or "stethoscope",
                       color=data.get("color"), sort_order=data.get("sort_order") or 1000, is_active=True)
    db.session.add(t)
    db.session.commit()
    return department_type_json(t)


def update_type(type_id, body):
    t = db.session.get(DepartmentType, type_id)
    if t is None:
        raise NotFound("Department type not found")
    data = validate(body, {"name_en": Str(max_len=100, nullable=False), "name_ar": Str(max_len=100, nullable=False),
                           "icon": Str(max_len=50, pattern=ICON_RE), "color": Str(pattern=COLOR_RE),
                           "sort_order": Int(min_value=0, max_value=100000, nullable=False),
                           "is_active": Bool(nullable=False)}, partial=True)
    for k in ("name_en", "name_ar"):
        if k in data and not data[k]:
            raise ValidationError("Invalid input", details={k: "is required"})
    for k, v in data.items():
        setattr(t, k, v)
    db.session.commit()
    return department_type_json(t)


# ---------------------------------------------------------------- users
def _center_names(ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return dict(db.session.execute(select(HealthCenter.id, HealthCenter.name).where(HealthCenter.id.in_(ids))).all())


def list_users():
    a = query_args({"center_id": Id(), "role": Enum(ROLES), "status": Enum(["active", "archived"]),
                    "q": Str(max_len=100)})
    stmt = select(User).order_by(User.health_center_id.nulls_first(), User.name, User.id)
    if a.get("center_id"):
        stmt = stmt.where(User.health_center_id == a["center_id"])
    if a.get("role"):
        stmt = stmt.where(User.role == a["role"])
    if a.get("status"):
        stmt = stmt.where(User.status == a["status"])
    if a.get("q"):
        like = f"%{a['q'].replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.username.ilike(like), User.email.ilike(like)))
    out = paginate(db.session, stmt, lambda u: u)
    names = _center_names([u.health_center_id for u in out["items"]])
    out["items"] = [user_json(u, names) for u in out["items"]]
    return out


def get_user(user_id):
    u = db.session.get(User, user_id)
    if u is None:
        raise NotFound("User not found")
    return u


def user_detail(u):
    return user_json(u, _center_names([u.health_center_id]))


def _audit_user(p, u, action, fields=None):
    from backend.app.modules.center.common import user_department_id
    audit.log_change(p, "user", action, "user", u.id, f"{u.name} ({u.username})", center_id=u.health_center_id,
                     department_id=user_department_id(u) if u.health_center_id else None, changed_fields=fields)


def create_superadmin(p, body):
    data = validate(body, {"username": Str(required=True, max_len=50), "name": Str(required=True, max_len=200),
                           "password": Str(required=True, strip=False, max_len=200), "email": Str(max_len=255)})
    u = accounts.create_user_record(center_id=None, username=data["username"], name=data["name"],
                                    role="superadmin", password=data["password"], email=data.get("email"),
                                    must_change_password=True)
    _audit_user(p, u, "create")
    db.session.commit()
    return u


def update_user(p, user_id, body):
    u = get_user(user_id)
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
    old_email, old_username = u.email, u.username
    accounts.apply_identity_change(u, username=data.get("username"), email=data.get("email") or None,
                                   reset_email_to_generated=bool(data.get("reset_email")))
    if u.username != old_username:
        changed.append("username")
    if u.email != old_email:
        changed.append("email")
    if changed:
        _audit_user(p, u, "edit", changed)
    db.session.commit()
    return u


def reset_password(p, user_id, body):
    from backend.app.auth.service import hash_password, revoke_user_sessions, validate_password
    from backend.app.core.timeutil import utcnow
    u = get_user(user_id)
    data = validate(body, {"password": Str(required=True, strip=False, max_len=200)})
    validate_password(data["password"], u.username)
    u.password_hash = hash_password(data["password"])
    u.password_changed_at = utcnow()
    u.must_change_password = True  # chosen by an administrator: the owner must set their own
    revoke_user_sessions(u.id, "password_reset")
    _audit_user(p, u, "edit", ["password"])
    db.session.commit()
    return u


def set_user_status(p, user_id, status):
    from backend.app.auth.service import revoke_user_sessions
    u = get_user(user_id)
    if u.id == p.user.id:
        raise Forbidden("You cannot change the status of your own account.")
    if u.status == status:
        return u
    if status == "archived":
        db.session.execute(update(Department).where(Department.head_user_id == u.id).values(head_user_id=None))
        revoke_user_sessions(u.id, "archived")
    else:
        _check_reactivation(u)
    u.status = status
    _audit_user(p, u, "edit", ["status"])
    db.session.commit()
    return u


def _check_reactivation(u):
    if not u.health_center_id:
        return
    from backend.app.modules.center.common import lock_center
    lock_center(u.health_center_id)
    key = accounts.role_limit_key(u.role)
    if key:
        accounts.check_limit(u.health_center_id, key)
    if u.role == "department_manager":
        other = db.session.execute(select(User.id).where(
            User.health_center_id == u.health_center_id, User.role == "department_manager",
            User.department_id == u.department_id, User.status == "active", User.id != u.id)).first()
        if other:
            raise Conflict("This department already has an active department manager.", code="department_has_manager")


# ---------------------------------------------------------------- audit
def list_audit():
    a = query_args({"category": Enum(AUDIT_CATEGORIES), "action": Str(max_len=40), "center_id": Id(),
                    "platform_only": Bool(), "date_from": Date(), "date_to": Date(), "q": Str(max_len=100)})
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    stmt = apply_audit_filters(stmt, a)
    if a.get("center_id"):
        stmt = stmt.where(AuditLog.health_center_id == a["center_id"])
    elif a.get("platform_only"):
        stmt = stmt.where(AuditLog.health_center_id.is_(None))
    out = paginate(db.session, stmt, lambda r: r, default_per_page=50)
    names = _center_names([r.health_center_id for r in out["items"]])
    out["items"] = [audit_json(r, names) for r in out["items"]]
    return out


def apply_audit_filters(stmt, a):
    """Shared by the center audit view."""
    if a.get("category"):
        stmt = stmt.where(AuditLog.category == a["category"])
    if a.get("action"):
        stmt = stmt.where(AuditLog.action == a["action"])
    if a.get("date_from"):
        stmt = stmt.where(AuditLog.created_at >= local_day_bounds(a["date_from"])[0])
    if a.get("date_to"):
        stmt = stmt.where(AuditLog.created_at < local_day_bounds(a["date_to"])[1])
    if a.get("q"):
        like = f"%{a['q'].replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(AuditLog.actor_name.ilike(like), AuditLog.target_label.ilike(like)))
    return stmt


# ---------------------------------------------------------------- platform settings / branding
BRANDING_KEY = "branding"
LOGO_KEY = "branding_logo"
LOGO_MAX_BYTES = 1024 * 1024
LOGO_MIMES = {"image/png", "image/jpeg", "image/webp"}
BRANDING_DEFAULTS = {"platform_name": "AeroCare", "primary_color": "#0f766e",
                     "secondary_color": "#0ea5e9", "login_message": None, "support_contact": None}


def _setting(key):
    row = db.session.get(PlatformSetting, key)
    return row.value if row else None


def _put_setting(key, value):
    row = db.session.get(PlatformSetting, key)
    if row is None:
        db.session.add(PlatformSetting(key=key, value=value))
    else:
        row.value = value


def branding():
    stored = _setting(BRANDING_KEY) or {}
    out = {k: stored.get(k, v) for k, v in BRANDING_DEFAULTS.items()}
    logo = _setting(LOGO_KEY)
    out["logo_url"] = f"/api/v1/platform/branding/logo?v={logo['sha256'][:12]}" if logo else None
    return out


def update_branding(body):
    data = validate(body, {"platform_name": Str(max_len=120, nullable=False), "primary_color": Str(pattern=COLOR_RE),
                           "secondary_color": Str(pattern=COLOR_RE), "login_message": Str(max_len=300),
                           "support_contact": Str(max_len=200)}, partial=True)
    if "platform_name" in data and not data["platform_name"]:
        raise ValidationError("Invalid input", details={"platform_name": "is required"})
    current = dict(_setting(BRANDING_KEY) or {})
    current.update(data)
    _put_setting(BRANDING_KEY, current)
    db.session.commit()
    return branding()


def set_logo(upload):
    """Platform logo (login page). Stored in platform_settings (small, PNG/JPEG/WebP only, sniffed)."""
    from backend.app.core.storage import validate_upload
    if upload is None:
        raise ValidationError("No file was uploaded.", code="no_files")
    data = upload.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise ValidationError("The logo must be 1 MB or smaller.", code="file_too_large")
    _, mime = validate_upload(upload.filename, data)
    if mime not in LOGO_MIMES:
        raise ValidationError("The logo must be a PNG, JPEG or WebP image.", code="file_type_not_allowed")
    _put_setting(LOGO_KEY, {"mime": mime, "sha256": hashlib.sha256(data).hexdigest(),
                            "data": base64.b64encode(data).decode("ascii")})
    db.session.commit()
    return branding()


def remove_logo():
    row = db.session.get(PlatformSetting, LOGO_KEY)
    if row is not None:
        db.session.delete(row)
        db.session.commit()
    return branding()


def logo_bytes():
    logo = _setting(LOGO_KEY)
    if not logo or logo.get("mime") not in LOGO_MIMES:
        raise NotFound("No logo")
    return base64.b64decode(logo["data"]), logo["mime"]
