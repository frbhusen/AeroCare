"""Lab report: structured JSON (always) and branded PDF via services.documents / services.pdf.

On finalization a PDF copy is stored as a center-wide `lab_report` file (owner_type
'lab_request') so it shows in the patient's file viewer for every authorized staff member
(spec §71/§104). Generating it is best-effort: failure (e.g. quota) never undoes finalization;
the on-demand PDF endpoint keeps working.
"""
import io
import logging

from werkzeug.datastructures import FileStorage

from backend.app.authz.principal import current_principal
from backend.app.core.errors import Conflict
from backend.app.core.timeutil import to_local
from backend.app.extensions import db

log = logging.getLogger("hc.laboratory")

L = {
    "title": {"en": "Laboratory Report", "ar": "تقرير المختبر"},
    "patient": {"en": "Patient", "ar": "المريض"}, "code": {"en": "Patient code", "ar": "رمز المريض"},
    "gender": {"en": "Gender", "ar": "الجنس"}, "dob": {"en": "Date of birth", "ar": "تاريخ الميلاد"},
    "requested_by": {"en": "Requested by", "ar": "طلب من قبل"},
    "requesting_clinic": {"en": "Requesting clinic", "ar": "العيادة الطالبة"},
    "requested_at": {"en": "Requested at", "ar": "تاريخ الطلب"},
    "finalized_by": {"en": "Finalized by", "ar": "اعتمد من قبل"},
    "finalized_at": {"en": "Finalized at", "ar": "تاريخ الاعتماد"},
    "test": {"en": "Test", "ar": "الفحص"}, "result": {"en": "Result", "ar": "النتيجة"},
    "unit": {"en": "Unit", "ar": "الوحدة"}, "range": {"en": "Reference range", "ar": "المجال المرجعي"},
    "flag": {"en": "Flag", "ar": "العلامة"}, "notes": {"en": "Notes", "ar": "ملاحظات"},
    "results": {"en": "Results", "ar": "النتائج"}, "signature": {"en": "Laboratory", "ar": "المختبر"},
    "clinical_notes": {"en": "Clinical notes", "ar": "ملاحظات سريرية"},
}


def _t(k, lang):
    return L[k].get(lang) or L[k]["en"]


def _dt(s):
    return to_local(s).strftime("%Y-%m-%d %H:%M") if s else ""


def ref_range(i):
    lo, hi = i.get("ref_low"), i.get("ref_high")
    if lo is not None and hi is not None:
        return f"{lo} - {hi}"
    if lo is not None:
        return f">= {lo}"
    if hi is not None:
        return f"<= {hi}"
    return i.get("ref_text") or ""


def report_data(rid):
    """Structured report (only for finalized requests the principal can read)."""
    from .service import _load, request_json
    p = current_principal()
    r, level = _load(p, rid)
    if r.status != "completed":
        raise Conflict("The lab report is available once results are finalized.", code="not_finalized")
    data = request_json(p, r, level)
    for i in data["items"]:
        i["reference_range"] = ref_range(i)
    data.pop("can", None)
    return r, data


def sections(data, lang):
    pt = data["patient"]
    kv = [[_t("patient", lang), pt.get("full_name", "")], [_t("code", lang), pt.get("code", "")],
          [_t("gender", lang), pt.get("gender") or ""], [_t("dob", lang), pt.get("date_of_birth") or ""],
          [_t("requesting_clinic", lang), data["requesting_clinic"]["name"] or ""],
          [_t("requested_by", lang), data["requested_by"]["name"] or ""],
          [_t("requested_at", lang), _dt(_parse(data["requested_at"]))],
          [_t("finalized_at", lang), _dt(_parse(data["finalized_at"]))]]
    rows = [[i["test_name"], i.get("result_value") or "", i.get("unit") or "", i["reference_range"],
             i.get("abnormal_flag") if i.get("abnormal_flag") in ("L", "H", "A") else ""] for i in data["items"]]
    out = [{"type": "key_values", "items": kv, "columns": 2},
           {"type": "heading", "text": _t("results", lang)},
           {"type": "table", "columns": [_t(k, lang) for k in ("test", "result", "unit", "range", "flag")],
            "rows": rows, "widths": [3, 2, 1, 2, 1], "align": ["start", "center", "center", "center", "center"]}]
    comments = [f"{i['test_name']}: {i['comment']}" for i in data["items"] if i.get("comment")]
    if data.get("result_notes") or comments:
        out.append({"type": "heading", "text": _t("notes", lang)})
        out.append({"type": "paragraph", "text": "\n".join(([data["result_notes"]] if data.get("result_notes")
                                                             else []) + comments)})
    fb = data.get("finalized_by") or {}
    out.append({"type": "note", "text": f"{_t('finalized_by', lang)}: {fb.get('name') or ''}"})
    out.append({"type": "signature", "labels": [_t("signature", lang)]})
    return out


def _parse(s):
    from datetime import datetime
    return datetime.fromisoformat(s) if s else None


def render_pdf(r, data, lang="en"):
    from backend.app.services import documents
    return documents.render(r.health_center_id, r.lab_department_id, "lab_report", _t("title", lang),
                            sections(data, lang), lang=lang, subtitle=f"LAB-{r.id:06d}")


def attach_pdf(p, r):
    """Store the finalized report as a center-wide file. Caller has committed finalization."""
    from backend.app.services.files import store_upload
    from .service import request_json
    try:
        data = request_json(p, r, "lab")
        for i in data["items"]:
            i["reference_range"] = ref_range(i)
        pdf = render_pdf(r, data, "en")
        up = FileStorage(stream=io.BytesIO(pdf), filename=f"lab-report-{r.id}.pdf")
        f = store_upload(p, [up], clinic_id=r.lab_clinic_id, department_id=r.lab_department_id,
                         patient_id=r.patient_id, category="lab_report", owner_type="lab_request", owner_id=r.id,
                         center_wide=True, commit=False)[0]
        r.report_file_id = f.id
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.exception("lab report PDF generation failed for request %s", r.id)
