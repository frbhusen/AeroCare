"""/generic — generic medical environment (visit + GenericVisitRecord)."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import request_json
from backend.app.models.clinical import VISIT_TYPES
from backend.app.modules.patients.helpers import accessible_clinics
from backend.app.modules.patients.summary import register_summary_provider
from backend.app.modules.patients.visits import visit_json

from . import service

register_summary_provider("generic", service.summary_section, order=100)

bp = Blueprint("generic", __name__, url_prefix="/generic")


def _out(v, rec):
    out = visit_json(v)
    out["record"] = service.record_json(rec)
    return out


@bp.get("/meta")
@login_required
def meta():
    p = current_principal()
    p.require("medical_records.view")
    clinics = [c for c, d in p.clinic_department.items() if p.department_env.get(d) == service.ENV]
    return jsonify({
        "vitals": [{"key": k, "min": lo, "max": hi, "unit": u, "decimals": dec}
                   for k, (lo, hi, u, dec) in service.VITALS.items()],
        "text_fields": list(service.TEXT_FIELDS), "visit_types": list(VISIT_TYPES),
        "clinics": accessible_clinics(p, clinics),
        "permissions": {k: p.has(k) for k in ("medical_records.create", "medical_records.edit",
                                              "medical_records.delete", "files.upload")},
    })


@bp.post("/visits")
@login_required
def create():
    v, rec = service.create(current_principal(), request_json())
    return jsonify(_out(v, rec)), 201


@bp.get("/visits/<int:visit_id>")
@login_required
def get(visit_id):
    return jsonify(_out(*service.get(current_principal(), visit_id)))


@bp.put("/visits/<int:visit_id>/record")
@login_required
def save_record(visit_id):
    return jsonify(_out(*service.save_record(current_principal(), visit_id, request_json())))


@bp.get("/patients/<int:patient_id>/visits")
@login_required
def patient_visits(patient_id):
    return jsonify(service.list_for_patient(current_principal(), patient_id, request.args.to_dict()))
