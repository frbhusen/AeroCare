"""WhatsApp reminder links (spec §77). No WhatsApp API: we only build a wa.me link with a
prepared message; staff send it manually."""
import re
from urllib.parse import quote

from sqlalchemy import select

from backend.app.core.errors import ValidationError
from backend.app.core.timeutil import to_local
from backend.app.extensions import db
from backend.app.models import Clinic, HealthCenter, Patient

TEMPLATES = {
    "en": ("Hello {patient},\nYour appointment at {center} is scheduled for:\n{date} at {time}.\n"
           "Clinic: {clinic}{location}"),
    "ar": ("مرحباً {patient}،\nموعدك في {center} محدد في:\n{date} الساعة {time}.\n"
           "العيادة: {clinic}{location}"),
}


def normalize_phone(raw):
    """International digits for wa.me. Syrian local numbers (09xxxxxxxx) -> 9639xxxxxxxx."""
    s = (raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if digits.startswith("00"):
        digits = digits[2:]
    elif s.startswith("+"):
        pass
    elif len(digits) == 10 and digits.startswith("09"):
        digits = "963" + digits[1:]
    elif len(digits) == 9 and digits.startswith("9"):
        digits = "963" + digits
    if not 8 <= len(digits) <= 15:
        return None
    return digits


def whatsapp_link(p, a, lang="en"):
    lang = lang if lang in TEMPLATES else "en"
    patient = db.session.execute(select(Patient).where(Patient.id == a.patient_id, p.tenant(Patient))).scalar_one()
    phone = normalize_phone(patient.phone)
    if not phone:
        raise ValidationError("The patient has no valid phone number.", code="no_phone",
                              details={"phone": "missing or invalid"})
    center = db.session.execute(select(HealthCenter.name).where(HealthCenter.id == p.center_id)).scalar_one()
    clinic = db.session.execute(select(Clinic.name).where(Clinic.id == a.clinic_id)).scalar_one()
    local = to_local(a.starts_at)
    location = a.location
    message = TEMPLATES[lang].format(
        patient=patient.full_name, center=center, date=local.strftime("%m/%d/%Y"), time=local.strftime("%H:%M"),
        clinic=clinic, location=f" ({location})" if location else "")
    return {"url": f"https://wa.me/{phone}?text={quote(message, safe='')}", "message": message, "phone": phone,
            "lang": lang}
