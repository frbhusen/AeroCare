"""Document templates with inheritance + one-call branded PDF rendering (owned by billing).

    from backend.app.services import documents
    tpl = documents.get_template(center_id, department_id, "lab_report")   # dept -> center -> defaults
    pdf = documents.render(center_id, department_id, "lab_report", "Laboratory report", sections, lang="ar",
                           subtitle="LAB-000123")
    return documents.pdf_response(pdf, "lab-report-123.pdf")              # Flask response (inline)

`sections` follow services/pdf.py. Callers must have authorized access to the underlying record
first; these helpers only read branding (center, department, template, logo) in the current tenant.
"""
from flask import Response
from sqlalchemy import select

from backend.app.extensions import db

TEMPLATE_KINDS = ("prescription", "invoice", "receipt", "lab_report", "radiology_report", "visit_summary",
                  "patient_summary", "appointment_slip")
TEMPLATE_FIELDS = ("title", "header_text", "footer_text", "show_logo", "accent_color", "extra")

_BASE = {"title": None, "header_text": None, "footer_text": None, "show_logo": True, "accent_color": None,
         "extra": {}}
TEMPLATE_DEFAULTS = {k: dict(_BASE) for k in TEMPLATE_KINDS}


def merge_template(*layers):
    """Later layers override earlier ones for non-null values; `extra` dicts are merged."""
    out = dict(_BASE)
    out["extra"] = {}
    for layer in layers:
        if not layer:
            continue
        for f in TEMPLATE_FIELDS:
            v = layer.get(f) if isinstance(layer, dict) else getattr(layer, f, None)
            if f == "extra":
                out["extra"].update(v or {})
            elif v is not None and v != "":
                out[f] = v
    return out


def get_template(center_id, department_id, kind):
    """Effective template dict for (center, department, kind) with a `sources` list describing
    which layers applied ('default', 'center', 'department')."""
    from backend.app.modules.billing.models import DocumentTemplate
    if kind not in TEMPLATE_KINDS:
        raise ValueError(f"unknown template kind {kind}")
    rows = db.session.execute(select(DocumentTemplate).where(
        DocumentTemplate.health_center_id == center_id, DocumentTemplate.kind == kind, DocumentTemplate.live(),
        (DocumentTemplate.department_id.is_(None)) | (DocumentTemplate.department_id == department_id)
        if department_id else DocumentTemplate.department_id.is_(None))).scalars().all()
    center_t = next((r for r in rows if r.department_id is None), None)
    dept_t = next((r for r in rows if r.department_id is not None), None)
    tpl = merge_template(TEMPLATE_DEFAULTS[kind], center_t, dept_t)
    tpl["sources"] = ["default"] + (["center"] if center_t else []) + (["department"] if dept_t else [])
    return tpl


def load_logo(center):
    """Center logo bytes (or None) from storage; ignores missing/deleted files."""
    from backend.app.core.storage import get_storage
    from backend.app.models import StoredFile
    if not center or not center.logo_file_id:
        return None
    f = db.session.get(StoredFile, center.logo_file_id)
    if f is None or f.health_center_id != center.id or f.pending_delete_until is not None \
            or not f.mime_type.startswith("image/"):
        return None
    try:
        return get_storage().read(f.storage_key)
    except Exception:
        return None


def render(center_id, department_id, kind, title, sections, lang="en", subtitle=None, page_size="A4"):
    """Load branding for the current tenant and render a PDF (bytes)."""
    from backend.app.models import Department, HealthCenter
    from .pdf import render_document
    center = db.session.get(HealthCenter, center_id)
    dept = None
    if department_id:
        dept = db.session.execute(select(Department).where(Department.id == department_id,
                                                           Department.health_center_id == center_id)
                                  ).scalar_one_or_none()
    tpl = get_template(center_id, department_id if dept else None, kind)
    return render_document(center=center, department=dept, kind=kind, title=title or tpl.get("title") or "",
                           sections=sections, lang="ar" if lang == "ar" else "en", template=tpl,
                           logo_bytes=load_logo(center) if tpl.get("show_logo", True) else None,
                           subtitle=subtitle, page_size=page_size)


def pdf_response(data, filename, inline=True):
    safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._-") or "document.pdf"
    disp = "inline" if inline else "attachment"
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{safe}"', "Cache-Control": "no-store"})
