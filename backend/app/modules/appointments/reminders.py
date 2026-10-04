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


def day_reminders(p, day, lang="en", clinic_id=None, doctor_id=None):
    """Scheduled appointments of one local day (default: tomorrow) in the principal's scope, each with
    its prepared WhatsApp link — staff click through the list and send manually (spec §77)."""
    from backend.app.core.timeutil import local_day_bounds
    from . import service as svc
    from .models import Appointment
    start, end = local_day_bounds(day)
    stmt = svc.scoped_query(p).where(Appointment.starts_at >= start, Appointment.starts_at < end,
                                     Appointment.status == "scheduled")
    if clinic_id:
        p.require(clinic_id=clinic_id)
        stmt = stmt.where(Appointment.clinic_id == clinic_id)
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    rows = db.session.execute(stmt.order_by(Appointment.starts_at).limit(500)).scalars().all()
    out = []
    for a, item in zip(rows, svc.serialize_many(rows)):
        try:
            link = whatsapp_link(p, a, lang)
        except ValidationError:
            link = None
        out.append({**item, "whatsapp": link, "reminder_sent_at": a.reminder_sent_at.isoformat() if a.reminder_sent_at else None,
                    "reminder_sent_by": a.reminder_sent_by})
    return {"date": day.isoformat(), "items": out, "with_phone": sum(1 for x in out if x["whatsapp"]),
            "sent": sum(1 for x in out if x["reminder_sent_at"])}


def mark_reminded(p, a):
    from backend.app.core.timeutil import utcnow
    p.require("appointments.view", clinic_id=a.clinic_id)
    a.reminder_sent_at = utcnow()
    a.reminder_sent_by = p.user.name
    db.session.commit()
    return {"id": a.id, "reminder_sent_at": a.reminder_sent_at.isoformat(), "reminder_sent_by": a.reminder_sent_by}
