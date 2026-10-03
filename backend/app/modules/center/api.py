"""/api/v1/center — health center management (see docs/modules/center.md).
Routes stay thin; authorization + scope checks are in the services."""
from flask import Blueprint, jsonify, request, send_file

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal as cp
from backend.app.core.validation import request_json

from . import export, org_service as org, perms_service as perms, settings_service as settings, \
    staff_service as staff

bp = Blueprint("center", __name__, url_prefix="/center")


# ---------------------------------------------------------------- settings
@bp.get("/settings")
@login_required
def settings_get():
    return jsonify(settings.get_settings(cp()))


@bp.patch("/settings")
@login_required
def settings_update():
    return jsonify(settings.update_settings(cp(), request_json()))


@bp.post("/settings/logo")
@login_required
def settings_logo():
    return jsonify(settings.upload_logo(cp(), request.files.get("file")))


@bp.delete("/settings/logo")
@login_required
def settings_logo_delete():
    return jsonify(settings.remove_logo(cp()))


@bp.get("/storage")
@login_required
def storage():
    return jsonify(settings.storage(cp()))


@bp.get("/limits")
@login_required
def limits():
    return jsonify(settings.limits(cp()))


# ---------------------------------------------------------------- departments
@bp.get("/departments")
@login_required
def departments():
    return jsonify(org.list_departments(cp()))


@bp.get("/departments/meta")
@login_required
def departments_meta():
    return jsonify(org.department_meta(cp()))


@bp.post("/departments")
@login_required
def department_create():
    return jsonify(org.create_department(cp(), request_json())), 201


@bp.get("/departments/<int:dept_id>")
@login_required
def department_get(dept_id):
    p = cp()
    p.require("settings.view")
    return jsonify(org.department_detail(p, org.get_department(p, dept_id)))


@bp.patch("/departments/<int:dept_id>")
@login_required
def department_update(dept_id):
    return jsonify(org.update_department(cp(), dept_id, request_json()))


@bp.put("/departments/<int:dept_id>/head")
@login_required
def department_head(dept_id):
    return jsonify(org.set_head(cp(), dept_id, request_json()))


@bp.delete("/departments/<int:dept_id>")
@login_required
def department_delete(dept_id):
    return jsonify(org.delete_department(cp(), dept_id)), 202


# ---------------------------------------------------------------- clinics
@bp.get("/clinics")
@login_required
def clinics():
    return jsonify(org.list_clinics(cp(), request.args))


@bp.post("/clinics")
@login_required
def clinic_create():
    return jsonify(org.create_clinic(cp(), request_json())), 201


@bp.get("/clinics/<int:clinic_id>")
@login_required
def clinic_get(clinic_id):
    p = cp()
    p.require("settings.view")
    return jsonify(org.clinic_detail(p, org.get_clinic(p, clinic_id)))


@bp.patch("/clinics/<int:clinic_id>")
@login_required
def clinic_update(clinic_id):
    return jsonify(org.update_clinic(cp(), clinic_id, request_json()))


@bp.delete("/clinics/<int:clinic_id>")
@login_required
def clinic_delete(clinic_id):
    return jsonify(org.delete_clinic(cp(), clinic_id)), 202


# ---------------------------------------------------------------- staff
@bp.get("/staff")
@login_required
def staff_list():
    return jsonify(staff.list_staff(cp()))


@bp.get("/staff/meta")
@login_required
def staff_meta():
    return jsonify(staff.meta(cp()))


@bp.post("/staff")
@login_required
def staff_create():
    p = cp()
    return jsonify(staff.detail(p, staff.create_staff(p, request_json()))), 201


@bp.get("/staff/<int:user_id>")
@login_required
def staff_get(user_id):
    p = cp()
    return jsonify(staff.detail(p, staff.get_staff(p, user_id)))


@bp.patch("/staff/<int:user_id>")
@login_required
def staff_update(user_id):
    p = cp()
    return jsonify(staff.detail(p, staff.update_staff(p, user_id, request_json())))


@bp.post("/staff/<int:user_id>/reassign")
@login_required
def staff_reassign(user_id):
    p = cp()
    return jsonify(staff.detail(p, staff.reassign_doctor(p, user_id, request_json())))


@bp.put("/staff/<int:user_id>/scopes")
@login_required
def staff_scopes(user_id):
    p = cp()
    return jsonify(staff.detail(p, staff.set_scopes(p, user_id, request_json())))


@bp.post("/staff/<int:user_id>/archive")
@login_required
def staff_archive(user_id):
    p = cp()
    return jsonify(staff.detail(p, staff.archive_staff(p, user_id)))


@bp.post("/staff/<int:user_id>/reactivate")
@login_required
def staff_reactivate(user_id):
    p = cp()
    return jsonify(staff.detail(p, staff.reactivate_staff(p, user_id)))


@bp.post("/staff/<int:user_id>/password")
@login_required
def staff_password(user_id):
    staff.reset_password(cp(), user_id, request_json())
    return jsonify({"ok": True})


@bp.delete("/staff/<int:user_id>")
@login_required
def staff_delete(user_id):
    return jsonify(staff.delete_staff(cp(), user_id))


# ---------------------------------------------------------------- permissions
@bp.get("/permissions")
@login_required
def permissions_catalog():
    return jsonify(perms.catalog(cp()))


@bp.put("/permissions/roles/<role>")
@login_required
def permissions_role(role):
    return jsonify(perms.set_role_permissions(cp(), role, request_json()))


@bp.get("/staff/<int:user_id>/permissions")
@login_required
def permissions_user(user_id):
    return jsonify(perms.user_permissions(cp(), user_id))


@bp.put("/staff/<int:user_id>/permissions")
@login_required
def permissions_user_set(user_id):
    return jsonify(perms.set_user_permissions(cp(), user_id, request_json()))


# ---------------------------------------------------------------- audit / export
@bp.get("/audit")
@login_required
def audit_logs():
    return jsonify(perms.list_audit(cp()))


@bp.get("/backup/export")
@login_required
def backup_export():
    fh, name = export.build_export(cp())
    return send_file(fh, mimetype="application/zip", as_attachment=True, download_name=name, max_age=0)
