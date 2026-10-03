"""/api/v1/dermatology — dermatology visits, photos, body-region catalog.
Laser Hair Removal routes (/dermatology/laser/...) live in laser_api.py on the same blueprint."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import Id, query_args, request_json

from . import service
from .regions import catalog

bp = Blueprint("dermatology", __name__, url_prefix="/dermatology")


def uploads_from_request():
    return request.files.getlist("files") + request.files.getlist("file")


@bp.get("/meta")
@login_required
def meta():
    return jsonify(service.meta())


@bp.get("/body-regions")
@login_required
def body_regions():
    return jsonify(catalog())


@bp.get("/patients/<int:patient_id>/visits")
@login_required
def list_visits(patient_id):
    args = query_args({"clinic_id": Id()})
    return jsonify(service.list_patient_visits(current_principal(), patient_id, args.get("clinic_id")))


@bp.post("/visits")
@login_required
def create_visit():
    return jsonify(service.create(current_principal(), request_json())), 201


@bp.get("/visits/<int:record_id>")
@login_required
def get_visit(record_id):
    return jsonify(service.get(current_principal(), record_id))


@bp.patch("/visits/<int:record_id>")
@login_required
def update_visit(record_id):
    return jsonify(service.update(current_principal(), record_id, request_json()))


@bp.delete("/visits/<int:record_id>")
@login_required
def delete_visit(record_id):
    return jsonify(service.delete(current_principal(), record_id)), 202


@bp.get("/visits/<int:record_id>/photos")
@login_required
def list_photos(record_id):
    return jsonify(service.list_photos(current_principal(), record_id))


@bp.post("/visits/<int:record_id>/photos")
@login_required
def upload_photos(record_id):
    out = service.upload_photos(current_principal(), record_id, uploads_from_request(),
                                category=request.form.get("category") or "photo",
                                description=request.form.get("description") or None)
    return jsonify(out), 201


from . import laser_api  # noqa: E402,F401  (registers /dermatology/laser routes on bp)
