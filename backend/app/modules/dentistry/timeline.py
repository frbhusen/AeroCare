"""Dental timeline for one patient: visits, treatments, plan items, X-rays and prescriptions in the
principal's accessible dental clinics (or one clinic), plus appointments (appointments.view). Newest first."""
from sqlalchemy import select

from backend.app.core.timeutil import iso, to_local
from backend.app.extensions import db
from backend.app.models import Prescription, StoredFile, Visit

from . import constants as C
from .models import Treatment, TreatmentPlan, XRay
from .service import clinic_filter, clinic_names, dental_clinic_ids, visible_patient

LIMIT = 500


def _tooth(o):
    return f"#{C.tooth_label(o.tooth_mode, o.tooth_number)}" if o.tooth_number else None


def _local(dt):
    d = to_local(dt)
    return (d.date().isoformat(), d.strftime("%H:%M")) if d else ("", "")


def patient_timeline(p, patient_id, clinic_id=None):
    p.require("medical_records.view")
    patient = visible_patient(p, patient_id)

    def scoped(model):
        return select(model).where(p.tenant(model), model.live(), model.patient_id == patient.id,
                                   clinic_filter(p, model.clinic_id, clinic_id))

    events = []
    for v in db.session.execute(scoped(Visit).order_by(Visit.visit_at.desc()).limit(LIMIT)).scalars():
        d, t = _local(v.visit_at)
        events.append({"type": "visit", "id": v.id, "date": d, "time": t, "title": v.title or v.visit_type,
                       "description": v.notes, "status": v.status, "visit_type": v.visit_type})
        events[-1].update(clinic_id=v.clinic_id, author_name=v.author_name)
    for tr in db.session.execute(scoped(Treatment).order_by(Treatment.date.desc()).limit(LIMIT)).scalars():
        events.append({"type": "treatment", "id": tr.id, "date": iso(tr.date), "time": "",
                       "title": tr.procedure or tr.description or "Treatment", "description": tr.description,
                       "status": tr.status, "tooth": _tooth(tr), "fee": f"{tr.fee:.2f}", "visit_id": tr.visit_id,
                       "clinic_id": tr.clinic_id, "author_name": tr.doctor_name or tr.author_name})
    for pl in db.session.execute(scoped(TreatmentPlan).order_by(TreatmentPlan.id.desc()).limit(LIMIT)).scalars():
        d, t = _local(pl.updated_at or pl.created_at)
        events.append({"type": "treatment-plan", "id": pl.id, "date": d, "time": t,
                       "title": pl.procedure or "Treatment plan", "description": pl.diagnosis, "status": pl.status,
                       "priority": pl.priority, "tooth": _tooth(pl), "clinic_id": pl.clinic_id,
                       "author_name": pl.doctor_name or pl.author_name})
    xq = (scoped(XRay).join(StoredFile, (StoredFile.id == XRay.file_id)
                            & (StoredFile.health_center_id == XRay.health_center_id))
          .where(StoredFile.live()).order_by(XRay.date.desc()).limit(LIMIT))
    for x in db.session.execute(xq).scalars():
        events.append({"type": "xray", "id": x.id, "date": iso(x.date),
                       "time": x.time.strftime("%H:%M") if x.time else "", "title": x.filename,
                       "description": x.type, "status": "", "tooth": x.tooth_tag, "file_id": x.file_id,
                       "image_url": f"/api/v1/files/{x.file_id}/content", "visit_id": x.visit_id,
                       "clinic_id": x.clinic_id, "author_name": x.author_name})
    for rx in db.session.execute(scoped(Prescription).order_by(Prescription.prescribed_at.desc()).limit(LIMIT)
                                 ).scalars():
        d, t = _local(rx.prescribed_at)
        events.append({"type": "prescription", "id": rx.id, "date": d, "time": t, "title": "Prescription",
                       "description": rx.notes, "status": rx.status, "visit_id": rx.visit_id,
                       "clinic_id": rx.clinic_id, "author_name": rx.author_name})
    try:
        from backend.app.modules.appointments.models import Appointment
    except ImportError:  # pragma: no cover - appointments module absent
        Appointment = None
    if Appointment is not None and p.has("appointments.view"):
        for ap in db.session.execute(scoped(Appointment).order_by(Appointment.starts_at.desc()).limit(LIMIT)
                                     ).scalars():
            d, t = _local(ap.starts_at)
            events.append({"type": "appointment", "id": ap.id, "date": d, "time": t,
                           "title": ap.appointment_type or ap.reason or "Appointment", "description": ap.reason,
                           "status": ap.status, "clinic_id": ap.clinic_id, "author_name": ap.author_name,
                           "is_walk_in": ap.is_walk_in})
    events.sort(key=lambda e: (e["date"] or "", e["time"] or "", e["id"]), reverse=True)
    names = clinic_names(p, {e["clinic_id"] for e in events} or set(dental_clinic_ids(p)))
    for e in events:
        e["clinic_name"] = names.get(e["clinic_id"])
    return {"patient_id": patient.id, "clinic_id": clinic_id, "events": events}
