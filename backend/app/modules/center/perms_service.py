"""Permission customization (role overrides per center + per-user grants/revokes) and the
center audit-log view."""
from sqlalchemy import select

from backend.app.core.api import paginate
from backend.app.core.errors import Forbidden, ValidationError
from backend.app.core.validation import Date, Enum, Field, Id, Str, Text, query_args, validate
from backend.app.extensions import db
from backend.app.authz.permissions import CATALOG, ROLE_DEFAULTS, ROLE_FORBIDDEN
from backend.app.authz.principal import effective_permissions
from backend.app.models import AuditLog, RolePermission, User, UserPermission
from backend.app.models.ops import AUDIT_CATEGORIES
from backend.app.services import audit, notifications

from . import staff_service as staff
from .common import is_center_level

EDITABLE_ROLES = ("department_manager", "doctor", "receptionist")


def _role_overrides(center_id, role):
    return dict(db.session.execute(select(RolePermission.permission, RolePermission.allowed).where(
        RolePermission.health_center_id == center_id, RolePermission.role == role)).all())


def _role_effective(center_id, role):
    perms = set(ROLE_DEFAULTS.get(role, set()))
    for perm, allowed in _role_overrides(center_id, role).items():
        (perms.add if allowed else perms.discard)(perm)
    return perms - ROLE_FORBIDDEN.get(role, set())


def catalog(p):
    p.require("permissions.manage")
    roles = {}
    for role in ("center_manager",) + EDITABLE_ROLES:
        roles[role] = {"defaults": sorted(ROLE_DEFAULTS.get(role, set())),
                       "forbidden": sorted(ROLE_FORBIDDEN.get(role, set())),
                       "overrides": _role_overrides(p.center_id, role),
                       "effective": sorted(_role_effective(p.center_id, role)),
                       "editable": role in EDITABLE_ROLES and is_center_level(p)}
    return {"permissions": [{"code": c, "label": label, "group": c.split(".")[0]} for c, label in CATALOG.items()],
            "roles": roles}


class _ChangesField(Field):
    """{"perm.code": true | false | null}  (null removes the override)."""

    def run(self, v):
        if not isinstance(v, dict) or not v or len(v) > len(CATALOG):
            raise ValueError("must be a non-empty object {permission: true|false|null}")
        for k, val in v.items():
            if val not in (True, False, None):
                raise ValueError(f"{k}: must be true, false or null")
        return v


def _parse_changes(body, role):
    data = validate(body, {"changes": _ChangesField(required=True), "note": Text(max_len=500)})
    bad = [k for k in data["changes"] if k not in CATALOG]
    if bad:
        raise ValidationError("Unknown permissions", details={"changes": bad})
    forbidden = [k for k, v in data["changes"].items() if v and k in ROLE_FORBIDDEN.get(role, set())]
    if forbidden:
        raise ValidationError("These permissions can never be granted to this role.", code="permission_forbidden",
                              details={"changes": forbidden})
    return data


def set_role_permissions(p, role, body):
    p.require_center_manager()
    p.require("permissions.manage")
    if role not in EDITABLE_ROLES:
        raise ValidationError("This role's permissions cannot be customized.", code="role_not_editable")
    data = _parse_changes(body, role)
    rows = {r.permission: r for r in db.session.execute(select(RolePermission).where(
        RolePermission.health_center_id == p.center_id, RolePermission.role == role)).scalars()}
    defaults = ROLE_DEFAULTS.get(role, set())
    for perm, allowed in data["changes"].items():
        row = rows.get(perm)
        if allowed is None or allowed == (perm in defaults):
            if row is not None:
                db.session.delete(row)
        elif row is None:
            db.session.add(RolePermission(health_center_id=p.center_id, role=role, permission=perm, allowed=allowed))
        else:
            row.allowed = allowed
    db.session.flush()
    users = db.session.execute(select(User.id).where(User.health_center_id == p.center_id, User.role == role,
                                                     User.status == "active")).scalars().all()
    notifications.notify(p.center_id, "permission_changed", "Your permissions were updated", user_ids=users,
                         exclude_user_id=p.user.id)
    db.session.commit()
    return catalog(p)["roles"][role]


def user_permissions(p, user_id):
    p.require("permissions.manage")
    u = staff.get_staff(p, user_id)
    if not staff.can_manage(p, u):
        raise Forbidden("You cannot manage this account's permissions.")
    rows = db.session.execute(select(UserPermission).where(UserPermission.user_id == u.id,
                                                           UserPermission.health_center_id == p.center_id)
                              .order_by(UserPermission.permission)).scalars().all()
    return {"user_id": u.id, "role": u.role, "role_permissions": sorted(_role_effective(p.center_id, u.role)),
            "forbidden": sorted(ROLE_FORBIDDEN.get(u.role, set())),
            "overrides": [{"permission": r.permission, "allowed": r.allowed, "note": r.note,
                           "granted_by": r.granted_by} for r in rows],
            "effective": sorted(effective_permissions(u, p.center_id))}


def set_user_permissions(p, user_id, body):
    p.require("permissions.manage")
    u = staff.get_staff(p, user_id)
    if not staff.can_manage(p, u):
        raise Forbidden("You cannot manage this account's permissions.")
    data = _parse_changes(body, u.role)
    if not is_center_level(p):
        beyond = [k for k, v in data["changes"].items() if v and not p.has(k)]
        if beyond:
            raise Forbidden("You cannot grant permissions you do not have.", details={"changes": beyond})
    rows = {r.permission: r for r in db.session.execute(select(UserPermission).where(
        UserPermission.user_id == u.id, UserPermission.health_center_id == p.center_id)).scalars()}
    for perm, allowed in data["changes"].items():
        row = rows.get(perm)
        if allowed is None:
            if row is not None:
                db.session.delete(row)
        elif row is None:
            db.session.add(UserPermission(health_center_id=p.center_id, user_id=u.id, permission=perm,
                                          allowed=allowed, granted_by=p.user.id, note=data.get("note")))
        else:
            row.allowed, row.granted_by, row.note = allowed, p.user.id, data.get("note")
    db.session.flush()
    notifications.notify(p.center_id, "permission_changed", "Your permissions were updated", user_ids=[u.id])
    staff._audit(p, u, "edit", ["permissions"])
    db.session.commit()
    return user_permissions(p, u.id)


# ---------------------------------------------------------------- audit view
def list_audit(p):
    """Center manager: whole center. Department manager: entries of their own department."""
    from backend.app.modules.admin.platform_service import apply_audit_filters
    p.require("audit.view")
    a = query_args({"category": Enum(AUDIT_CATEGORIES), "action": Str(max_len=40), "department_id": Id(),
                    "date_from": Date(), "date_to": Date(), "q": Str(max_len=100)})
    stmt = select(AuditLog).where(AuditLog.health_center_id == p.center_id)
    if not is_center_level(p):
        stmt = stmt.where(AuditLog.department_id.in_(sorted(p.managed_department_ids) or [-1]))
    if a.get("department_id"):
        stmt = stmt.where(AuditLog.department_id == a["department_id"])
    stmt = apply_audit_filters(stmt, a).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    from backend.app.modules.admin.serializers import audit_json
    return paginate(db.session, stmt, audit_json, default_per_page=50)
