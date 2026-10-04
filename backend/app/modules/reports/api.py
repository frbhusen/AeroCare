"""/api/v1/reports — report catalog, JSON reports and Excel/PDF exports (thin routes)."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.errors import ValidationError
from backend.app.services.documents import pdf_response
from . import export, service

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.get("")
@login_required(perm="reports.view")
def catalog():
    return jsonify(service.catalog(current_principal()))


@bp.get("/<key>")
@login_required(perm="reports.view")
def run_report(key):
    return jsonify(service.run(current_principal(), key, request.args))


@bp.get("/<key>/export")
@login_required(perm="reports.view")
def export_report(key):
    fmt = (request.args.get("format") or "xlsx").lower()
    if fmt not in ("xlsx", "pdf"):
        raise ValidationError("Invalid input", details={"format": "must be one of: xlsx, pdf"})
    lang = "ar" if request.args.get("lang") == "ar" else "en"
    p = current_principal()
    rep = service.run(p, key, request.args, export=True)
    if fmt == "pdf":
        return pdf_response(export.to_pdf(p, rep, lang), export.filename(rep, "pdf"), inline=False)
    return export.xlsx_response(export.to_xlsx(p, rep, lang), export.filename(rep, "xlsx"))
