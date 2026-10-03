"""/api/v1/auth — login, logout, current identity, password change, superadmin support mode."""
from flask import Blueprint, g, jsonify
from sqlalchemy import select

from backend.app.auth import service as auth
from backend.app.authz.decorators import authenticated, public, superadmin_required
from backend.app.authz.principal import current_principal
from backend.app.core import tenancy
from backend.app.core.errors import NotFound, Unauthorized
from backend.app.core.timeutil import iso
from backend.app.core.validation import Id, Str, request_json, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Department, HealthCenter, User

bp = Blueprint("auth", __name__, url_prefix="/auth")


def user_json(u):
    return {"id": u.id, "username": u.username, "name": u.name, "email": u.email, "role": u.role,
            "status": u.status, "clinic_id": u.clinic_id, "department_id": u.department_id,
            "health_center_id": u.health_center_id}


def center_json(c):
    return {"id": c.id, "name": c.name, "status": c.status, "currency": c.currency,
            "primary_color": c.primary_color, "secondary_color": c.secondary_color,
            "logo_url": f"/api/v1/branding/logo" if c.logo_file_id else None,
            "trial_ends_at": iso(c.trial_ends_at), "subscription_ends_at": iso(c.subscription_ends_at)}


def me_payload():
    p = current_principal()
    out = {"user": user_json(p.user), "principal": p.to_json(), "csrf_token": g.csrf_token,
           "portal": "superadmin" if (p.is_superadmin and not p.support_mode) else
           ("center" if (p.center_wide or p.role == "center_manager") else "department")}
    if p.center_id:
        c = db.session.get(HealthCenter, p.center_id)
        out["center"] = center_json(c)
        depts = db.session.execute(select(Department).where(
            Department.health_center_id == p.center_id, Department.id.in_(sorted(p.visible_department_ids) or [-1]))
            .order_by(Department.name)).scalars().all()
        clinics = db.session.execute(select(Clinic).where(
            Clinic.health_center_id == p.center_id, Clinic.id.in_(sorted(p.clinic_ids) or [-1]))
            .order_by(Clinic.name)).scalars().all()
        out["departments"] = [{
            "id": d.id, "name": d.name, "environment": d.environment, "type_code": d.department_type.code,
            "name_en": d.department_type.name_en, "name_ar": d.department_type.name_ar,
            "color": d.color or d.department_type.color, "icon": d.department_type.icon,
            "managed": d.id in p.managed_department_ids} for d in depts]
        out["clinics"] = [{"id": c.id, "name": c.name, "department_id": c.department_id, "location": c.location}
                          for c in clinics]
    return out


@bp.post("/login")
@public
def login():
    data = validate(request_json(), {"email": Str(required=True, max_len=255), "password": Str(required=True,
                                                                                               max_len=200, strip=False)})
    user = auth.authenticate(data["email"], data["password"])
    token, sess = auth.create_session(user)
    auth.load_request_principal(token=token)  # principal for the response, from the new session
    resp = jsonify(me_payload())
    auth.set_session_cookie(resp, token)
    return resp


@bp.post("/logout")
@public
def logout():
    p = getattr(g, "principal", None)
    if p is not None and p.session is not None:
        auth.revoke_session(p.session, "logout")
    resp = jsonify({"ok": True})
    auth.clear_session_cookie(resp)
    return resp


@bp.get("/me")
@authenticated
def me():
    return jsonify(me_payload())


@bp.post("/change-password")
@authenticated
def change_password():
    data = validate(request_json(), {"current_password": Str(required=True, strip=False, max_len=200),
                                     "new_password": Str(required=True, strip=False, max_len=200)})
    p = current_principal()
    auth.validate_password(data["new_password"])
    with tenancy.scoped("auth"):
        user = db.session.get(User, p.user.id)
        if not auth.verify_password(user.password_hash, data["current_password"]):
            raise Unauthorized("Current password is incorrect.", code="invalid_credentials")
        user.password_hash = auth.hash_password(data["new_password"])
        from backend.app.core.timeutil import utcnow
        user.password_changed_at = utcnow()
        db.session.commit()
    return jsonify({"ok": True})


@bp.post("/support/enter")
@superadmin_required
def support_enter():
    """Superadmin enters a center's support view (read-only for medical data)."""
    data = validate(request_json(), {"center_id": Id(required=True)})
    p = current_principal()
    center = db.session.get(HealthCenter, data["center_id"])
    if center is None:
        raise NotFound("Health center not found")
    with tenancy.scoped("auth"):
        p.session.acting_center_id = center.id
        db.session.add(p.session)
        db.session.commit()
    return jsonify({"ok": True, "center_id": center.id})


@bp.post("/support/exit")
@superadmin_required
def support_exit():
    p = current_principal()
    with tenancy.scoped("auth"):
        p.session.acting_center_id = None
        db.session.add(p.session)
        db.session.commit()
    return jsonify({"ok": True})
