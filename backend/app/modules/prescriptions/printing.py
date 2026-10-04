"""Prescription PDF (branded via services.documents, template kind "prescription")."""
from sqlalchemy import select

from backend.app.extensions import db
from backend.app.models import Clinic, Patient, PrescriptionItem
from backend.app.services import documents
from backend.app.services.pdf import format_dt

L = {
    "title": {"en": "Prescription", "ar": "وصفة طبية"},
    "patient": {"en": "Patient", "ar": "المريض"},
    "code": {"en": "Patient ID", "ar": "رقم المريض"},
    "dob": {"en": "Date of birth", "ar": "تاريخ الميلاد"},
    "gender": {"en": "Gender", "ar": "الجنس"},
    "male": {"en": "Male", "ar": "ذكر"},
    "female": {"en": "Female", "ar": "أنثى"},
    "doctor": {"en": "Doctor", "ar": "الطبيب"},
    "clinic": {"en": "Clinic", "ar": "العيادة"},
    "date": {"en": "Date", "ar": "التاريخ"},
    "status": {"en": "Status", "ar": "الحالة"},
    "allergies": {"en": "Allergies", "ar": "الحساسية"},
    "medication": {"en": "Medication", "ar": "الدواء"},
    "dose": {"en": "Dose", "ar": "الجرعة"},
    "frequency": {"en": "Frequency", "ar": "التكرار"},
    "duration": {"en": "Duration", "ar": "المدة"},
    "quantity": {"en": "Qty", "ar": "الكمية"},
    "instructions": {"en": "Instructions", "ar": "التعليمات"},
    "notes": {"en": "Notes", "ar": "ملاحظات"},
    "cancelled": {"en": "CANCELLED", "ar": "ملغاة"},
    "pending": {"en": "Pending", "ar": "قيد الانتظار"},
    "partially_dispensed": {"en": "Partially dispensed", "ar": "صُرفت جزئياً"},
    "dispensed": {"en": "Dispensed", "ar": "صُرفت"},
}


def _t(key, lang):
    e = L.get(key, {})
    return e.get(lang) or e.get("en") or key


def _qty(q):
    if q is None:
        return ""
    s = f"{q:f}".rstrip("0").rstrip(".")
    return s


def prescription_pdf(rx, lang="en"):
    pt = db.session.get(Patient, rx.patient_id)
    clinic = db.session.get(Clinic, rx.clinic_id)
    items = db.session.execute(select(PrescriptionItem).where(PrescriptionItem.prescription_id == rx.id)
                               .order_by(PrescriptionItem.sort_order, PrescriptionItem.id)).scalars().all()
    kv = [[_t("patient", lang), pt.full_name], [_t("code", lang), pt.display_code],
          [_t("doctor", lang), rx.author_name or ""], [_t("clinic", lang), clinic.name if clinic else ""],
          [_t("date", lang), format_dt(rx.prescribed_at)], [_t("status", lang), _t(rx.status, lang)]]
    if pt.date_of_birth:
        kv.append([_t("dob", lang), pt.date_of_birth.isoformat()])
    if pt.gender:
        kv.append([_t("gender", lang), _t(pt.gender, lang)])
    sections = [{"type": "key_values", "items": kv, "columns": 2}]
    if pt.allergies:
        sections.append({"type": "note", "text": f"{_t('allergies', lang)}: {pt.allergies}"})
    rows = []
    for n, i in enumerate(items, 1):
        name = i.medication_name + (f"\n{i.instructions}" if i.instructions else "")
        rows.append([str(n), name, i.dose or "", i.frequency or "", i.duration or "", _qty(i.quantity)])
    sections.append({"type": "table",
                     "columns": ["#", _t("medication", lang), _t("dose", lang), _t("frequency", lang),
                                 _t("duration", lang), _t("quantity", lang)],
                     "rows": rows, "widths": [0.5, 4, 1.6, 1.6, 1.4, 0.9],
                     "align": ["center", "start", "start", "start", "start", "end"]})
    if rx.notes:
        sections.append({"type": "heading", "text": _t("notes", lang)})
        sections.append({"type": "paragraph", "text": rx.notes})
    sections.append({"type": "signature", "labels": [_t("doctor", lang)]})
    title = _t("title", lang)
    if rx.status == "cancelled":
        title = f"{title} — {_t('cancelled', lang)}"
    return documents.render(rx.health_center_id, rx.department_id, "prescription", title, sections, lang=lang,
                            subtitle=f"RX-{rx.id:06d}", page_size="A5")
