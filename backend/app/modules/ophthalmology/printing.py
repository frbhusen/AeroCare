"""Glasses (spectacle) prescription PDF for an eye examination, via the shared document engine."""
from sqlalchemy import select

from backend.app.core.errors import ValidationError
from backend.app.extensions import db
from backend.app.models import Patient
from backend.app.modules.dermatology import visitkit
from backend.app.services import clinical, documents
from backend.app.services.pdf import format_dt

from .models import OphthalmologyExam
from .schemas import LENS_TYPES

L = {
    "title": {"en": "Glasses prescription", "ar": "وصفة نظارات"},
    "patient": {"en": "Patient", "ar": "المريض"},
    "code": {"en": "Patient code", "ar": "رمز المريض"},
    "dob": {"en": "Date of birth", "ar": "تاريخ الميلاد"},
    "date": {"en": "Date", "ar": "التاريخ"},
    "doctor": {"en": "Doctor", "ar": "الطبيب"},
    "clinic": {"en": "Clinic", "ar": "العيادة"},
    "eye": {"en": "Eye", "ar": "العين"},
    "od": {"en": "Right (OD)", "ar": "اليمنى (OD)"},
    "os": {"en": "Left (OS)", "ar": "اليسرى (OS)"},
    "sph": {"en": "SPH", "ar": "SPH"},
    "cyl": {"en": "CYL", "ar": "CYL"},
    "axis": {"en": "AXIS", "ar": "AXIS"},
    "add": {"en": "ADD", "ar": "ADD"},
    "pd": {"en": "PD (mm)", "ar": "المسافة بين الحدقتين (مم)"},
    "lens_type": {"en": "Lens type", "ar": "نوع العدسة"},
    "notes": {"en": "Notes", "ar": "ملاحظات"},
    "single_vision": {"en": "Single vision", "ar": "رؤية أحادية"},
    "bifocal": {"en": "Bifocal", "ar": "ثنائية البؤرة"},
    "progressive": {"en": "Progressive", "ar": "متعددة البؤر"},
    "reading": {"en": "Reading", "ar": "للقراءة"},
    "contact_lens": {"en": "Contact lens", "ar": "عدسات لاصقة"},
    "other": {"en": "Other", "ar": "أخرى"},
}


def _l(key, lang):
    return L[key][lang]


def _num(v, signed=True):
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:+.2f}" if signed else (str(int(f)) if f == int(f) else f"{f:g}")


def glasses_pdf(p, exam_id, lang="en"):
    e, visit, clinic_name = visitkit.get_record(p, OphthalmologyExam, exam_id, label="Eye examination")
    g = e.glasses or {}
    right, left = g.get("right") or {}, g.get("left") or {}
    if not right and not left:
        raise ValidationError("This examination has no glasses prescription.", code="no_glasses_prescription")
    pt = db.session.execute(select(Patient).where(Patient.id == e.patient_id, p.tenant(Patient))).scalar_one()
    sections = [
        {"type": "key_values", "columns": 2, "items": [
            [_l("patient", lang), pt.full_name], [_l("code", lang), clinical.format_patient_code(pt.code)],
            [_l("dob", lang), pt.date_of_birth.isoformat() if pt.date_of_birth else "—"],
            [_l("date", lang), format_dt(visit.visit_at, with_time=False)],
            [_l("doctor", lang), e.author_name or "—"], [_l("clinic", lang), clinic_name or "—"]]},
        {"type": "table", "columns": [_l(k, lang) for k in ("eye", "sph", "cyl", "axis", "add")],
         "widths": [2, 1, 1, 1, 1], "align": ["start", "center", "center", "center", "center"],
         "rows": [[_l(k, lang), _num(r.get("sphere")), _num(r.get("cylinder")), _num(r.get("axis"), signed=False),
                   _num(r.get("add"))] for k, r in (("od", right), ("os", left))]},
    ]
    extra = []
    if g.get("pd_mm") is not None:
        extra.append([_l("pd", lang), _num(g["pd_mm"], signed=False)])
    if g.get("lens_type") in LENS_TYPES:
        extra.append([_l("lens_type", lang), _l(g["lens_type"], lang)])
    if extra:
        sections.append({"type": "key_values", "columns": 2, "items": extra})
    if g.get("notes"):
        sections += [{"type": "heading", "text": _l("notes", lang)}, {"type": "paragraph", "text": g["notes"]}]
    sections += [{"type": "spacer", "height": 10}, {"type": "signature", "labels": [_l("doctor", lang)]}]
    pdf = documents.render(p.center_id, e.department_id, "prescription", _l("title", lang), sections, lang=lang,
                           subtitle=clinical.format_patient_code(pt.code), page_size="A5")
    return documents.pdf_response(pdf, f"glasses-prescription-{e.id}.pdf")
