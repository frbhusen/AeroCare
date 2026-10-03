"""Radiology report: JSON payload and branded PDF (services.documents, kind 'radiology_report')."""
from backend.app.authz.principal import current_principal
from backend.app.core.errors import Conflict
from backend.app.core.timeutil import to_local

from .service import load, study_json

L = {
    "title": {"en": "Radiology Report", "ar": "تقرير الأشعة"},
    "patient": {"en": "Patient", "ar": "المريض"}, "code": {"en": "Patient code", "ar": "رمز المريض"},
    "gender": {"en": "Gender", "ar": "الجنس"}, "dob": {"en": "Date of birth", "ar": "تاريخ الميلاد"},
    "exam": {"en": "Exam", "ar": "الفحص"}, "region": {"en": "Body region", "ar": "المنطقة"},
    "requested_by": {"en": "Requested by", "ar": "طلب من قبل"},
    "requesting_clinic": {"en": "Requesting clinic", "ar": "العيادة الطالبة"},
    "performed_at": {"en": "Performed at", "ar": "تاريخ الإجراء"},
    "question": {"en": "Clinical question", "ar": "السؤال السريري"},
    "findings": {"en": "Findings", "ar": "الموجودات"}, "impression": {"en": "Impression", "ar": "الانطباع"},
    "radiologist": {"en": "Radiologist", "ar": "أخصائي الأشعة"},
}
EXAM_LABELS = {"x_ray": "X-Ray", "ct": "CT", "mri": "MRI", "ultrasound": "Ultrasound", "other": "Other"}


def _t(k, lang):
    return L[k].get(lang) or L[k]["en"]


def report_payload(p, s, level):
    data = study_json(p, s, level)
    data.pop("can", None)
    return data


def report_data(sid):
    p = current_principal()
    s, level = load(p, sid)
    if not (s.status == "finalized" or (level == "radiology" and s.status == "reported")):
        raise Conflict("The radiology report is available once it is finalized.", code="not_finalized")
    return s, report_payload(p, s, level)


def _dt(v):
    return to_local(v).strftime("%Y-%m-%d %H:%M") if v else ""


def sections(s, data, lang):
    pt = data["patient"] or {}
    rep = data.get("report") or {}
    rad = (rep.get("radiologist") or {}).get("name") or ""
    out = [{"type": "key_values", "columns": 2, "items": [
        [_t("patient", lang), pt.get("full_name", "")], [_t("code", lang), pt.get("code", "")],
        [_t("gender", lang), pt.get("gender") or ""], [_t("dob", lang), pt.get("date_of_birth") or ""],
        [_t("exam", lang), EXAM_LABELS.get(s.exam_type, s.exam_type)], [_t("region", lang), s.body_region or ""],
        [_t("requesting_clinic", lang), data["requesting_clinic"]["name"] or ""],
        [_t("requested_by", lang), data["requested_by"]["name"] or ""],
        [_t("performed_at", lang), _dt(s.performed_at)], [_t("radiologist", lang), rad]]}]
    if s.clinical_question:
        out += [{"type": "heading", "text": _t("question", lang)}, {"type": "paragraph", "text": s.clinical_question}]
    out += [{"type": "heading", "text": _t("findings", lang)}, {"type": "paragraph", "text": rep.get("findings") or "-"},
            {"type": "heading", "text": _t("impression", lang)},
            {"type": "paragraph", "text": rep.get("impression") or "-"},
            {"type": "signature", "labels": [_t("radiologist", lang)]}]
    return out


def render_pdf(s, data, lang="en"):
    from backend.app.services import documents
    return documents.render(s.health_center_id, s.radiology_department_id, "radiology_report", _t("title", lang),
                            sections(s, data, lang), lang=lang, subtitle=f"RAD-{s.id:06d}")
