"""/prescriptions — shared prescriptions (create/list/get/edit while pending/cancel/delete+undo)."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import request_json
from backend.app.models.clinical import PRESCRIPTION_STATUSES
from backend.app.modules.patients.helpers import accessible_clinics
from backend.app.modules.patients.summary import register_summary_provider

from . import service

register_summary_provider("prescriptions", service.summary_section, order=40)

bp = Blueprint("prescriptions", __name__, url_prefix="/prescriptions")


@bp.get("/meta")
@login_required
def meta():
    p = current_principal()
    p.require("medical_records.view")
    return jsonify({"statuses": list(PRESCRIPTION_STATUSES),
                    "clinics": accessible_clinics(p) if p.has("medical_records.create") else [],
                    "permissions": {k: p.has(k) for k in ("medical_records.create", "medical_records.edit",
                                                          "medical_records.delete")}})


@bp.get("")
@login_required
def list_prescriptions():
    return jsonify(service.list_rx(current_principal(), request.args.to_dict()))


@bp.post("")
@login_required
def create():
    return jsonify(service.rx_json(service.create(current_principal(), request_json()))), 201


@bp.get("/<int:rx_id>")
@login_required
def get(rx_id):
    return jsonify(service.rx_json(service.get_rx(current_principal(), rx_id)))


@bp.put("/<int:rx_id>")
@login_required
def update(rx_id):
    return jsonify(service.rx_json(service.update(current_principal(), rx_id, request_json())))


@bp.post("/<int:rx_id>/cancel")
@login_required
def cancel(rx_id):
    return jsonify(service.rx_json(service.cancel(current_principal(), rx_id, request_json())))


@bp.delete("/<int:rx_id>")
@login_required
def delete(rx_id):
    return jsonify(service.delete(current_principal(), rx_id)), 202


@bp.get("/<int:rx_id>/pdf")
@login_required
def pdf(rx_id):
    from backend.app.services import documents
    from .printing import prescription_pdf
    rx = service.get_rx(current_principal(), rx_id)
    lang = "ar" if request.args.get("lang") == "ar" else "en"
    return documents.pdf_response(prescription_pdf(rx, lang), f"prescription-{rx.id}.pdf")
