"""Superadmin portal API. Routes are absolute (`/admin/...`) because this blueprint also serves
the public login-page branding under `/platform/branding`. Everything except the branding
endpoints requires `@superadmin_required` (platform DB mode, no center context)."""
from flask import Blueprint, current_app, jsonify, request, send_file

from backend.app.authz.decorators import public, superadmin_required
from backend.app.authz.principal import current_principal
from backend.app.core.errors import ApiError, NotFound
from backend.app.core.validation import request_json
from backend.app.services import backup as backup_service

from . import platform_service as ps
from . import service as cs

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------- public branding (login page)
@bp.get("/platform/branding")
@public
def platform_branding():
    return jsonify(ps.branding())


@bp.get("/platform/branding/logo")
@public
def platform_logo():
    data, mime = ps.logo_bytes()
    resp = current_app.response_class(data, mimetype=mime)
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


# ---------------------------------------------------------------- dashboard / storage
@bp.get("/admin/dashboard")
@superadmin_required
def dashboard():
    return jsonify(cs.dashboard())


@bp.get("/admin/storage")
@superadmin_required
def storage():
    return jsonify(cs.storage_overview())


@bp.get("/admin/meta")
@superadmin_required
def meta():
    """Choices for portal forms."""
    from backend.app.models.ops import AUDIT_CATEGORIES
    from backend.app.models.platform import ENVIRONMENTS
    from backend.app.models.users import ROLES
    return jsonify({"plans": ps.list_plans()["items"], "department_types": ps.list_department_types()["items"],
                    "roles": list(ROLES), "center_statuses": ["trial", "active", "expired", "suspended"],
                    "status_actions": list(cs.STATUS_ACTIONS), "audit_categories": list(AUDIT_CATEGORIES),
                    "environments": list(ENVIRONMENTS)})


# ---------------------------------------------------------------- health centers
@bp.get("/admin/centers")
@superadmin_required
def list_centers():
    return jsonify(cs.list_centers(request.args))


@bp.post("/admin/centers")
@superadmin_required
def create_center():
    return jsonify(cs.create_center_with_manager(current_principal(), request_json())), 201


@bp.get("/admin/centers/<int:center_id>")
@superadmin_required
def get_center(center_id):
    return jsonify(cs.center_detail(cs.get_center(center_id)))


@bp.patch("/admin/centers/<int:center_id>")
@superadmin_required
def update_center(center_id):
    return jsonify(cs.update_center(center_id, request_json()))


@bp.post("/admin/centers/<int:center_id>/status")
@superadmin_required
def center_status(center_id):
    return jsonify(cs.change_status(center_id, request_json()))


@bp.put("/admin/centers/<int:center_id>/plan")
@superadmin_required
def center_plan(center_id):
    return jsonify(cs.assign_plan(center_id, request_json()))


@bp.put("/admin/centers/<int:center_id>/limits")
@superadmin_required
def center_limits(center_id):
    return jsonify(cs.update_limits(center_id, request_json()))


@bp.put("/admin/centers/<int:center_id>/modules")
@superadmin_required
def center_modules(center_id):
    return jsonify(cs.update_modules(center_id, request_json()))


@bp.post("/admin/centers/<int:center_id>/managers")
@superadmin_required
def center_manager_create(center_id):
    u = cs.create_manager(current_principal(), center_id, request_json())
    return jsonify(ps.user_detail(u)), 201


@bp.delete("/admin/centers/<int:center_id>")
@superadmin_required
def center_delete(center_id):
    return jsonify(cs.delete_center_permanently(center_id, request_json()))


# ---------------------------------------------------------------- plans
@bp.get("/admin/plans")
@superadmin_required
def plans():
    return jsonify(ps.list_plans())


@bp.post("/admin/plans")
@superadmin_required
def plan_create():
    return jsonify(ps.create_plan(request_json())), 201


@bp.patch("/admin/plans/<int:plan_id>")
@superadmin_required
def plan_update(plan_id):
    return jsonify(ps.update_plan(plan_id, request_json()))


@bp.delete("/admin/plans/<int:plan_id>")
@superadmin_required
def plan_delete(plan_id):
    return jsonify(ps.delete_plan(plan_id))


# ---------------------------------------------------------------- department types
@bp.get("/admin/department-types")
@superadmin_required
def department_types():
    return jsonify(ps.list_department_types())


@bp.post("/admin/department-types")
@superadmin_required
def department_type_create():
    return jsonify(ps.create_custom_type(request_json())), 201


@bp.patch("/admin/department-types/<int:type_id>")
@superadmin_required
def department_type_update(type_id):
    return jsonify(ps.update_type(type_id, request_json()))


# ---------------------------------------------------------------- users
@bp.get("/admin/users")
@superadmin_required
def users():
    return jsonify(ps.list_users())


@bp.get("/admin/users/<int:user_id>")
@superadmin_required
def user_get(user_id):
    return jsonify(ps.user_detail(ps.get_user(user_id)))


@bp.patch("/admin/users/<int:user_id>")
@superadmin_required
def user_update(user_id):
    return jsonify(ps.user_detail(ps.update_user(current_principal(), user_id, request_json())))


@bp.post("/admin/users/<int:user_id>/password")
@superadmin_required
def user_password(user_id):
    ps.reset_password(current_principal(), user_id, request_json())
    return jsonify({"ok": True})


@bp.post("/admin/users/<int:user_id>/archive")
@superadmin_required
def user_archive(user_id):
    return jsonify(ps.user_detail(ps.set_user_status(current_principal(), user_id, "archived")))


@bp.post("/admin/users/<int:user_id>/reactivate")
@superadmin_required
def user_reactivate(user_id):
    return jsonify(ps.user_detail(ps.set_user_status(current_principal(), user_id, "active")))


@bp.post("/admin/superadmins")
@superadmin_required
def superadmin_create():
    return jsonify(ps.user_detail(ps.create_superadmin(current_principal(), request_json()))), 201


# ---------------------------------------------------------------- audit
@bp.get("/admin/audit")
@superadmin_required
def audit_logs():
    return jsonify(ps.list_audit())


# ---------------------------------------------------------------- platform settings
@bp.get("/admin/settings")
@superadmin_required
def settings_get():
    return jsonify(ps.branding())


@bp.put("/admin/settings")
@superadmin_required
def settings_put():
    return jsonify(ps.update_branding(request_json()))


@bp.post("/admin/settings/logo")
@superadmin_required
def settings_logo():
    return jsonify(ps.set_logo(request.files.get("file")))


@bp.delete("/admin/settings/logo")
@superadmin_required
def settings_logo_delete():
    return jsonify(ps.remove_logo())


# ---------------------------------------------------------------- full backups
@bp.get("/admin/backups")
@superadmin_required
def backups():
    return jsonify({"items": backup_service.list_backups(current_app)})


@bp.post("/admin/backups")
@superadmin_required
def backup_create():
    try:
        path = backup_service.create_full_backup(current_app)
    except backup_service.BackupError as e:
        raise ApiError(str(e), code="backup_failed", status=500)
    item = next((b for b in backup_service.list_backups(current_app) if b["name"] == path.name), {"name": path.name})
    return jsonify(item), 201


@bp.get("/admin/backups/<name>/<filename>")
@superadmin_required
def backup_download(name, filename):
    path = backup_service.backup_file_path(current_app, name, filename)
    if path is None:
        raise NotFound("Backup file not found")
    mime = "application/json" if filename.endswith(".json") else "application/octet-stream"
    return send_file(path, mimetype=mime, as_attachment=True, download_name=f"{name}-{filename}")
