"""Routes: /patients/* and /visits/*  (blueprint without a prefix so both groups share it)."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import request_json
from backend.app.models.clinical import BLOOD_TYPES, GENDERS
from backend.app.models.clinical import VISIT_TYPES
from backend.app.services.clinical import get_patient, get_visit

from . import service, summary_core, visits  # noqa: F401  (summary_core registers core sections)
from .helpers import accessible_clinics
from .summary import build_summary

bp = Blueprint("patients", __name__)


# ------------------------------------------------------------------ patients
@bp.get("/patients/meta")
@login_required
def patients_meta():
    p = current_principal()
    p.require("patients.view")
    return jsonify({
        "genders": list(GENDERS), "blood_types": list(BLOOD_TYPES), "visit_types": list(VISIT_TYPES),
        "visit_statuses": list(visits.VISIT_STATUSES),
        "clinics": accessible_clinics(p),
        "permissions": {k: p.has(k) for k in (
            "patients.create", "patients.edit", "patients.delete", "patients.delete_with_history",
            "medical_records.view", "medical_records.create", "medical_records.edit", "medical_records.delete",
            "files.view", "files.upload", "billing.view")},
    })


@bp.get("/patients")
@login_required
def list_patients():
    return jsonify(service.list_patients(current_principal(), request.args.to_dict()))


@bp.get("/patients/lookup")
@login_required
def lookup():
    return jsonify(service.lookup(current_principal(), request.args.to_dict()))


@bp.post("/patients")
@login_required
def create_patient():
    p = current_principal()
    pt = service.create_patient(p, request_json())
    return jsonify(service.patient_detail(p, pt)), 201


@bp.get("/patients/<int:patient_id>")
@login_required
def get_patient_route(patient_id):
    p = current_principal()
    return jsonify(service.patient_detail(p, get_patient(p, patient_id)))


@bp.patch("/patients/<int:patient_id>")
@login_required
def update_patient(patient_id):
    p = current_principal()
    return jsonify(service.patient_detail(p, service.update_patient(p, patient_id, request_json())))


@bp.post("/patients/<int:patient_id>/link")
@login_required
def link_patient(patient_id):
    p = current_principal()
    return jsonify(service.patient_detail(p, service.link_to_clinic(p, patient_id, request_json())))


@bp.delete("/patients/<int:patient_id>")
@login_required
def delete_patient(patient_id):
    return jsonify(service.delete_patient(current_principal(), patient_id)), 202


@bp.get("/patients/<int:patient_id>/departments")
@login_required
def patient_departments(patient_id):
    p = current_principal()
    return jsonify({"items": service.departments_indicator(p, get_patient(p, patient_id))})


@bp.get("/patients/<int:patient_id>/visits")
@login_required
def patient_visits(patient_id):
    return jsonify(visits.list_visits(current_principal(), request.args.to_dict(), patient_id=patient_id))


@bp.get("/patients/<int:patient_id>/summary")
@login_required
def patient_summary(patient_id):
    p = current_principal()
    return jsonify(build_summary(p, get_patient(p, patient_id)))


# ------------------------------------------------------------------ visits
@bp.get("/visits")
@login_required
def list_visits():
    return jsonify(visits.list_visits(current_principal(), request.args.to_dict()))


@bp.post("/visits")
@login_required
def create_visit():
    p = current_principal()
    return jsonify(visits.visit_json(visits.create(p, request_json()))), 201


@bp.get("/visits/<int:visit_id>")
@login_required
def get_visit_route(visit_id):
    return jsonify(visits.visit_json(get_visit(current_principal(), visit_id)))


@bp.patch("/visits/<int:visit_id>")
@login_required
def update_visit(visit_id):
    return jsonify(visits.visit_json(visits.update(current_principal(), visit_id, request_json())))


@bp.post("/visits/<int:visit_id>/complete")
@login_required
def complete_visit(visit_id):
    return jsonify(visits.visit_json(visits.set_status(current_principal(), visit_id, request_json(), "completed")))


@bp.post("/visits/<int:visit_id>/reopen")
@login_required
def reopen_visit(visit_id):
    return jsonify(visits.visit_json(visits.set_status(current_principal(), visit_id, request_json(), "open")))


@bp.delete("/visits/<int:visit_id>")
@login_required
def delete_visit(visit_id):
    return jsonify(visits.delete(current_principal(), visit_id)), 202
