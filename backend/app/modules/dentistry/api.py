"""Dentistry API (/api/v1/dentistry). Thin routes; logic in service.py / records.py / xrays.py."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import Enum, Id, Int, query_args, request_json

from . import constants as C
from . import records, service, timeline, xrays

bp = Blueprint("dentistry", __name__, url_prefix="/dentistry")


def _clinic_arg():
    return query_args({"clinic_id": Id()}).get("clinic_id")


@bp.get("/meta")
@login_required
def meta():
    return jsonify(service.meta(current_principal()))


@bp.get("/doctors")
@login_required
def doctors():
    return jsonify(service.clinic_doctors(current_principal(), _clinic_arg()))


# ---- odontogram
@bp.get("/patients/<int:patient_id>/odontogram")
@login_required
def odontogram(patient_id):
    a = query_args({"clinic_id": Id(), "mode": Enum(C.TOOTH_MODES)})
    return jsonify(service.get_chart(current_principal(), patient_id, a.get("clinic_id"), a.get("mode")))


@bp.put("/patients/<int:patient_id>/odontogram/<string:mode>/<int:tooth_number>")
@login_required
def update_tooth(patient_id, mode, tooth_number):
    data, created = service.update_tooth(current_principal(), patient_id, mode, tooth_number, request_json())
    return jsonify(data), 201 if created else 200


@bp.post("/patients/<int:patient_id>/odontogram/bulk")
@login_required
def bulk_teeth(patient_id):
    return jsonify(service.bulk_update(current_principal(), patient_id, request_json()))


@bp.get("/patients/<int:patient_id>/odontogram/history")
@login_required
def odontogram_history(patient_id):
    a = query_args({"clinic_id": Id(), "mode": Enum(C.TOOTH_MODES), "tooth_number": Int(min_value=1, max_value=32)})
    return jsonify(service.tooth_history(current_principal(), patient_id, a.get("clinic_id"), a.get("mode"),
                                         a.get("tooth_number")))


# ---- timeline
@bp.get("/patients/<int:patient_id>/timeline")
@login_required
def patient_timeline(patient_id):
    return jsonify(timeline.patient_timeline(current_principal(), patient_id, _clinic_arg()))


@bp.get("/patients/<int:patient_id>/summary")
@login_required
def patient_summary(patient_id):
    p = current_principal()
    patient = service.visible_patient(p, patient_id)
    return jsonify(service.dental_summary(p, patient) or {"section": "dentistry", "available": False})


# ---- treatments
@bp.get("/treatments")
@login_required
def list_treatments():
    return jsonify(records.list_treatments(current_principal()))


@bp.post("/treatments")
@login_required
def create_treatment():
    return jsonify(records.create_treatment(current_principal(), request_json())), 201


@bp.get("/treatments/<int:tid>")
@login_required
def get_treatment(tid):
    return jsonify(records.get_treatment(current_principal(), tid))


@bp.patch("/treatments/<int:tid>")
@login_required
def update_treatment(tid):
    return jsonify(records.update_treatment(current_principal(), tid, request_json()))


@bp.delete("/treatments/<int:tid>")
@login_required
def delete_treatment(tid):
    return jsonify(records.delete_treatment(current_principal(), tid)), 202


# ---- treatment plans
@bp.get("/treatment-plans")
@login_required
def list_plans():
    return jsonify(records.list_plans(current_principal()))


@bp.post("/treatment-plans")
@login_required
def create_plan():
    return jsonify(records.create_plan(current_principal(), request_json())), 201


@bp.get("/treatment-plans/<int:pid>")
@login_required
def get_plan(pid):
    return jsonify(records.get_plan(current_principal(), pid))


@bp.patch("/treatment-plans/<int:pid>")
@login_required
def update_plan(pid):
    return jsonify(records.update_plan(current_principal(), pid, request_json()))


@bp.delete("/treatment-plans/<int:pid>")
@login_required
def delete_plan(pid):
    return jsonify(records.delete_plan(current_principal(), pid)), 202


@bp.post("/treatment-plans/<int:pid>/convert")
@login_required
def convert_plan(pid):
    return jsonify(records.convert_plan(current_principal(), pid, request_json())), 201


# ---- x-rays
@bp.get("/patients/<int:patient_id>/xrays")
@login_required
def list_xrays(patient_id):
    return jsonify(xrays.list_xrays(current_principal(), patient_id, dict(request.args)))


@bp.post("/patients/<int:patient_id>/xrays")
@login_required
def upload_xray(patient_id):
    return jsonify(xrays.upload(current_principal(), patient_id, request.form,
                                request.files.getlist("file"))), 201


@bp.get("/xrays/<int:xid>")
@login_required
def get_xray(xid):
    return jsonify(xrays.get_xray(current_principal(), xid))


@bp.patch("/xrays/<int:xid>")
@login_required
def update_xray(xid):
    return jsonify(xrays.update_xray(current_principal(), xid, request_json()))


@bp.delete("/xrays/<int:xid>")
@login_required
def delete_xray(xid):
    return jsonify(xrays.delete_xray(current_principal(), xid)), 202


@bp.get("/xrays/<int:xid>/verify")
@login_required
def verify_xray(xid):
    return jsonify(xrays.verify_xray(current_principal(), xid))
