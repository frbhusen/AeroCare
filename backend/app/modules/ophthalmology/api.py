"""/api/v1/ophthalmology — structured eye examinations (ophthalmology clinics only)."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import Id, query_args, request_json

from . import printing, service

bp = Blueprint("ophthalmology", __name__, url_prefix="/ophthalmology")


@bp.get("/meta")
@login_required
def meta():
    return jsonify(service.meta(current_principal()))


@bp.get("/patients/<int:patient_id>/exams")
@login_required
def list_exams(patient_id):
    args = query_args({"clinic_id": Id()})
    return jsonify(service.list_patient_exams(current_principal(), patient_id, args.get("clinic_id")))


@bp.get("/exams")
@login_required
def list_department_exams():
    return jsonify(service.list_department_exams(current_principal(), dict(request.args)))


@bp.get("/exams/<int:exam_id>/glasses.pdf")
@login_required
def glasses_pdf(exam_id):
    lang = request.args.get("lang") if request.args.get("lang") in ("ar", "en") else "en"
    return printing.glasses_pdf(current_principal(), exam_id, lang)


@bp.post("/exams")
@login_required
def create_exam():
    return jsonify(service.create(current_principal(), request_json())), 201


@bp.get("/exams/<int:exam_id>")
@login_required
def get_exam(exam_id):
    return jsonify(service.get(current_principal(), exam_id))


@bp.patch("/exams/<int:exam_id>")
@login_required
def update_exam(exam_id):
    return jsonify(service.update(current_principal(), exam_id, request_json()))


@bp.delete("/exams/<int:exam_id>")
@login_required
def delete_exam(exam_id):
    return jsonify(service.delete(current_principal(), exam_id)), 202
