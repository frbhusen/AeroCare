"""Laboratory API (/api/v1/lab). Routes are thin; logic lives in service.py / catalog.py."""
from flask import Blueprint, jsonify, request
from sqlalchemy import select

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.api import created, ok
from backend.app.core.validation import Bool, Enum, Id, Str, query_args, request_json
from backend.app.extensions import db
from backend.app.models import Clinic

from . import catalog, report, service, summary  # noqa: F401 (summary registers a provider)
from .models import PRIORITIES, RESULT_TYPES, STATUSES
from .routing import env_options, processing_clinics

bp = Blueprint("laboratory", __name__, url_prefix="/lab")


@bp.get("/meta")
@login_required
def meta():
    p = current_principal()
    catalog.require_read(p)
    req_clinics = sorted(p.clinic_ids) if p.has("lab.request") else []
    names = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        p.tenant(Clinic), Clinic.id.in_(req_clinics or [-1]))).all())
    return ok({
        "result_types": list(RESULT_TYPES), "priorities": list(PRIORITIES), "statuses": list(STATUSES),
        "flags": {"L": "low", "H": "high", "N": "normal", "A": "abnormal"},
        "laboratories": env_options(p.center_id, "laboratory"),
        "requesting_clinics": [{"id": c, "name": names.get(c), "department_id": p.clinic_department.get(c)}
                               for c in req_clinics],
        "processing_clinics": processing_clinics(p, "laboratory") if p.has("lab.process") else [],
        "can": {"request": p.has("lab.request"), "process": p.has("lab.process") and bool(
            processing_clinics(p, "laboratory") or p.center_wide), "manage_tests": catalog.can_manage_tests(p)},
        "categories": catalog.list_categories(include_inactive=False),
    })


# ---- catalog ------------------------------------------------------------------
@bp.get("/categories")
@login_required
def list_categories():
    return ok({"items": catalog.list_categories()})


@bp.post("/categories")
@login_required
def create_category():
    return created(catalog.create_category(request_json()))


@bp.patch("/categories/<int:cid>")
@login_required
def update_category(cid):
    return ok(catalog.update_category(cid, request_json()))


@bp.delete("/categories/<int:cid>")
@login_required
def delete_category(cid):
    return jsonify(catalog.delete_category(cid)), 202


@bp.get("/tests")
@login_required
def list_tests():
    a = query_args({"category_id": Id(), "active": Bool(), "q": Str(max_len=100)})
    return ok({"items": catalog.list_tests(a.get("category_id"), a.get("active"), a.get("q"))})


@bp.post("/tests")
@login_required
def create_test():
    return created(catalog.create_test(request_json()))


@bp.get("/tests/<int:tid>")
@login_required
def get_test(tid):
    return ok(catalog.get_test(tid))


@bp.patch("/tests/<int:tid>")
@login_required
def update_test(tid):
    return ok(catalog.update_test(tid, request_json()))


@bp.delete("/tests/<int:tid>")
@login_required
def delete_test(tid):
    return jsonify(catalog.delete_test(tid)), 202


# ---- requests -----------------------------------------------------------------
@bp.post("/requests")
@login_required
def create_request():
    return created(service.create_request(request_json()))


@bp.get("/requests")
@login_required
def list_requests():
    return ok(service.list_requested(_args()))


@bp.get("/queue")
@login_required
def queue():
    return ok(service.list_queue(_args()))


@bp.get("/patients/<int:patient_id>/requests")
@login_required
def patient_requests(patient_id):
    return ok(service.list_for_patient(patient_id, _args()))


@bp.get("/requests/<int:rid>")
@login_required
def get_request(rid):
    return ok(service.get_request(rid))


@bp.patch("/requests/<int:rid>")
@login_required
def update_request(rid):
    return ok(service.update_request(rid, request_json()))


@bp.post("/requests/<int:rid>/start")
@login_required
def start(rid):
    return ok(service.start(rid, request_json()))


@bp.put("/requests/<int:rid>/results")
@login_required
def results(rid):
    return ok(service.enter_results(rid, request_json()))


@bp.post("/requests/<int:rid>/finalize")
@login_required
def finalize(rid):
    return ok(service.finalize(rid, request_json()))


@bp.post("/requests/<int:rid>/cancel")
@login_required
def cancel(rid):
    return ok(service.cancel(rid, request_json()))


@bp.delete("/requests/<int:rid>")
@login_required
def delete_request(rid):
    return jsonify(service.delete_request(rid)), 202


@bp.get("/requests/<int:rid>/report")
@login_required
def get_report(rid):
    a = query_args({"format": Enum(["json", "pdf"], default="json"), "lang": Enum(["en", "ar"], default="en")})
    r, data = report.report_data(rid)
    if a["format"] == "pdf":
        from backend.app.services.documents import pdf_response
        return pdf_response(report.render_pdf(r, data, a["lang"]), f"lab-report-{r.id}.pdf")
    return ok(data)


def _args():
    return {k: v for k, v in request.args.items() if k not in ("page", "per_page")}

