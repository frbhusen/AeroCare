"""/api/v1/dermatology/laser — Laser Hair Removal sessions (dermatology clinics only)."""
from flask import jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import Id, query_args, request_json

from . import laser_service as svc
from .api import bp, uploads_from_request
from .regions import catalog


@bp.get("/laser/meta")
@login_required
def laser_meta():
    return jsonify(svc.meta(current_principal()))


@bp.get("/laser/body-regions")
@login_required
def laser_body_regions():
    return jsonify(catalog())


@bp.get("/laser/patients/<int:patient_id>/sessions")
@login_required
def laser_list(patient_id):
    args = query_args({"clinic_id": Id()})
    return jsonify(svc.list_sessions(current_principal(), patient_id, args.get("clinic_id")))


@bp.get("/laser/patients/<int:patient_id>/history")
@login_required
def laser_history(patient_id):
    args = query_args({"clinic_id": Id()})
    return jsonify(svc.history(current_principal(), patient_id, args.get("clinic_id")))


@bp.get("/laser/patients/<int:patient_id>/next-number")
@login_required
def laser_next_number(patient_id):
    args = query_args({"clinic_id": Id(required=True)})
    return jsonify(svc.next_number(current_principal(), patient_id, args["clinic_id"]))


@bp.get("/laser/sessions")
@login_required
def laser_list_department():
    return jsonify(svc.list_department(current_principal(), dict(request.args)))


@bp.post("/laser/sessions")
@login_required
def laser_create():
    return jsonify(svc.create(current_principal(), request_json())), 201


@bp.get("/laser/sessions/<int:session_id>")
@login_required
def laser_get(session_id):
    return jsonify(svc.get(current_principal(), session_id))


@bp.patch("/laser/sessions/<int:session_id>")
@login_required
def laser_update(session_id):
    return jsonify(svc.update(current_principal(), session_id, request_json()))


@bp.delete("/laser/sessions/<int:session_id>")
@login_required
def laser_delete(session_id):
    return jsonify(svc.delete(current_principal(), session_id)), 202


@bp.get("/laser/sessions/<int:session_id>/photos")
@login_required
def laser_photos(session_id):
    return jsonify(svc.list_photos(current_principal(), session_id))


@bp.post("/laser/sessions/<int:session_id>/photos")
@login_required
def laser_upload(session_id):
    out = svc.upload_photos(current_principal(), session_id, uploads_from_request(),
                            category=request.form.get("category") or "photo",
                            description=request.form.get("description") or None)
    return jsonify(out), 201
