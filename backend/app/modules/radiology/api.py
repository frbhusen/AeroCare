"""Radiology API (/api/v1/radiology). Thin routes over service.py / workflow.py."""
from flask import Blueprint, jsonify, request
from sqlalchemy import select

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.api import created, ok
from backend.app.core.errors import Forbidden
from backend.app.core.validation import Enum, query_args, request_json
from backend.app.extensions import db
from backend.app.models import Clinic

from backend.app.modules.laboratory.routing import env_options, processing_clinics
from . import report, service, summary, workflow  # noqa: F401
from .models import EXAM_TYPES, PRIORITIES, STATUSES

bp = Blueprint("radiology", __name__, url_prefix="/radiology")


@bp.get("/meta")
@login_required
def meta():
    p = current_principal()
    if not any(p.has(x) for x in ("radiology.request", "radiology.process", "medical_records.view")):
        raise Forbidden("You do not have access to radiology.", details={"permission": "radiology.request"})
    req_clinics = sorted(p.clinic_ids) if p.has("radiology.request") else []
    names = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        p.tenant(Clinic), Clinic.id.in_(req_clinics or [-1]))).all())
    proc = processing_clinics(p, "radiology") if p.has("radiology.process") else []
    return ok({
        "exam_types": list(EXAM_TYPES), "priorities": list(PRIORITIES), "statuses": list(STATUSES),
        "radiology_departments": env_options(p.center_id, "radiology"),
        "requesting_clinics": [{"id": c, "name": names.get(c), "department_id": p.clinic_department.get(c)}
                               for c in req_clinics],
        "processing_clinics": proc,
        "can": {"request": p.has("radiology.request"), "process": bool(proc)},
    })


@bp.post("/studies")
@login_required
def create_study():
    return created(service.create_study(request_json()))


@bp.get("/studies")
@login_required
def list_studies():
    return ok(service.list_requested(_args()))


@bp.get("/worklist")
@login_required
def worklist():
    return ok(service.list_worklist(_args()))


@bp.get("/patients/<int:patient_id>/studies")
@login_required
def patient_studies(patient_id):
    return ok(service.list_for_patient(patient_id, _args()))


@bp.get("/studies/<int:sid>")
@login_required
def get_study(sid):
    return ok(service.get_study(sid))


@bp.patch("/studies/<int:sid>")
@login_required
def update_study(sid):
    return ok(service.update_study(sid, request_json()))


@bp.delete("/studies/<int:sid>")
@login_required
def delete_study(sid):
    return jsonify(service.delete_study(sid)), 202


@bp.post("/studies/<int:sid>/schedule")
@login_required
def schedule(sid):
    return ok(workflow.schedule(sid, request_json()))


@bp.post("/studies/<int:sid>/start")
@login_required
def start(sid):
    return ok(workflow.start(sid, request_json()))


@bp.post("/studies/<int:sid>/images")
@login_required
def upload_images(sid):
    return created(workflow.upload_images(sid, request.files.getlist("files"), request.form.get("description")))


@bp.put("/studies/<int:sid>/report")
@login_required
def write_report(sid):
    return ok(workflow.write_report(sid, request_json()))


@bp.post("/studies/<int:sid>/finalize")
@login_required
def finalize(sid):
    return ok(workflow.finalize(sid, request_json()))


@bp.post("/studies/<int:sid>/cancel")
@login_required
def cancel(sid):
    return ok(workflow.cancel(sid, request_json()))


@bp.get("/studies/<int:sid>/report")
@login_required
def get_report(sid):
    a = query_args({"format": Enum(["json", "pdf"], default="json"), "lang": Enum(["en", "ar"], default="en")})
    s, data = report.report_data(sid)
    if a["format"] == "pdf":
        from backend.app.services.documents import pdf_response
        return pdf_response(report.render_pdf(s, data, a["lang"]), f"radiology-report-{s.id}.pdf")
    return ok(data)


@bp.get("/studies/<int:sid>/shares")
@login_required
def list_shares(sid):
    return ok(workflow.list_shares(sid))


@bp.post("/studies/<int:sid>/shares")
@login_required
def add_share(sid):
    return created(workflow.add_share(sid, request_json()))


@bp.delete("/studies/<int:sid>/shares/<int:share_id>")
@login_required
def remove_share(sid, share_id):
    return ok(workflow.remove_share(sid, share_id))


def _args():
    return {k: v for k, v in request.args.items() if k not in ("page", "per_page")}
