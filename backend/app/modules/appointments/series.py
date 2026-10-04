"""Recurring appointments (spec §49): creation of a series and "this and future" edits.
Every occurrence is a normal Appointment row (individually manageable)."""
from datetime import timedelta

from sqlalchemy import or_, select, text

from backend.app.core.errors import Conflict, NotFound
from backend.app.core.timeutil import to_local
from backend.app.extensions import db
from backend.app.models import Clinic
from backend.app.services.clinical import link_patient_to_clinic
from . import service as svc
from .models import FREE_STATUSES, Appointment, AppointmentSeries
from .recurrence import expand, local_dt


def _conflict_error(intervals, conflicts):
    dates = sorted({to_local(intervals[i][0]).date().isoformat() for i in conflicts})
    return Conflict(f"{len(dates)} of the requested dates conflict with existing appointments.",
                    code="appointment_conflict", details={"conflicting_dates": dates})


def create_recurring(p, data):
    p.require("appointments.create")
    clinic, doctor_id = svc.resolve_place(p, data.get("clinic_id"), data.get("doctor_id"), "doctor_id" in data)
    p.require("appointments.create", clinic_id=clinic.id)
    patient = svc.center_patient(p, data["patient_id"])
    start = svc.normalize_dt(data["starts_at"])
    end = svc.compute_end(start, data.get("ends_at"), data.get("duration_minutes"),
                          svc.clinic_default_duration(clinic))
    duration = int((end - start).total_seconds() // 60)
    rule = data["rule"]
    local_start = to_local(start)
    dates = expand(local_start.date(), rule["freq"], rule.get("interval") or 1, rule.get("weekdays"),
                   rule.get("count"), rule.get("until"))
    t = local_start.time()
    intervals = []
    for d in dates:
        s = local_dt(d, t)
        intervals.append((s, s + timedelta(minutes=duration)))
    conflicts = svc.find_conflicts(p, intervals, doctor_id, clinic.id)
    if conflicts:
        raise _conflict_error(intervals, conflicts)

    link_patient_to_clinic(p.center_id, patient.id, clinic.id, clinic.department_id)
    series = AppointmentSeries(
        health_center_id=p.center_id, department_id=clinic.department_id, clinic_id=clinic.id, doctor_id=doctor_id,
        patient_id=patient.id, freq=rule["freq"], repeat_interval=rule.get("interval") or 1,
        weekdays=sorted(set(rule["weekdays"])) if rule.get("weekdays") else None, count=rule.get("count"),
        until=rule.get("until"), starts_on=dates[0], start_time=t.replace(tzinfo=None), duration_minutes=duration,
        location=data.get("location") or clinic.location, appointment_type=data.get("appointment_type"),
        reason=data.get("reason"), notes=data.get("notes"), created_by=p.user.id)
    db.session.add(series)
    db.session.flush()
    items = [svc.new_appointment(p, clinic=clinic, doctor_id=doctor_id, patient=patient, starts_at=s, ends_at=e,
                                 data=data, series=series, series_index=i)
             for i, (s, e) in enumerate(intervals)]
    db.session.flush()
    svc.notify(p, items[0], "appointment_created", f"New recurring appointments ({len(items)})")
    db.session.commit()
    return series, items


def serialize_series(s):
    return {"id": s.id, "version": s.version, "freq": s.freq, "interval": s.repeat_interval,
            "weekdays": s.weekdays, "count": s.count, "until": s.until.isoformat() if s.until else None,
            "starts_on": s.starts_on.isoformat(), "start_time": s.start_time.strftime("%H:%M"),
            "duration_minutes": s.duration_minutes, "clinic_id": s.clinic_id, "doctor_id": s.doctor_id,
            "patient_id": s.patient_id, "location": s.location, "appointment_type": s.appointment_type,
            "reason": s.reason, "notes": s.notes}


def get_series(p, series_id):
    s = db.session.execute(select(AppointmentSeries).where(
        AppointmentSeries.id == series_id, p.tenant(AppointmentSeries),
        p.clinic_clause(AppointmentSeries.clinic_id))).scalar_one_or_none()
    if s is None:
        raise NotFound("Series not found")
    p.require("appointments.view", clinic_id=s.clinic_id)
    return s


def update_this_and_future(p, a, data):
    """Apply the edit to `a` and every later live *scheduled* occurrence of its series that is
    in the principal's scope, and update the series template. Time edits move each occurrence
    by the same number of calendar days and set the new local wall-clock time/duration.
    All-or-nothing: any conflict rejects the whole edit with the conflicting dates."""
    series = db.session.execute(select(AppointmentSeries).where(
        AppointmentSeries.id == a.series_id, p.tenant(AppointmentSeries)).with_for_update()).scalar_one()
    rows = db.session.execute(
        svc.scoped_query(p).where(Appointment.series_id == a.series_id,
                                  or_(Appointment.id == a.id,
                                      (Appointment.starts_at > a.starts_at) & (Appointment.status == "scheduled")))
        .order_by(Appointment.starts_at).with_for_update()).scalars().all()
    resolved = svc.plan_edit(p, a, data)
    old_clinic_location = db.session.execute(select(Clinic.location).where(Clinic.id == a.clinic_id)).scalar()

    old_local = to_local(a.starts_at)
    new_local = to_local(svc.normalize_dt(data["starts_at"])) if data.get("starts_at") else old_local
    day_shift = new_local.date() - old_local.date()
    time_changed = bool(data.get("starts_at") or data.get("ends_at") or data.get("duration_minutes"))
    if data.get("ends_at") or data.get("duration_minutes"):
        new_end = svc.compute_end(new_local, data.get("ends_at"), data.get("duration_minutes"))
        duration = int((new_end - new_local).total_seconds() // 60)
    else:
        duration = int((a.ends_at - a.starts_at).total_seconds() // 60)
    new_time = new_local.time().replace(tzinfo=None)

    planned = []
    for r in rows:
        if time_changed:
            d = to_local(r.starts_at).date() + day_shift
            s = local_dt(d, new_time)
            planned.append((s, s + timedelta(minutes=duration)))
        else:
            planned.append((r.starts_at, r.ends_at))
    clinic_id = resolved["clinic"].id if "clinic" in resolved else a.clinic_id
    doctor_id = resolved.get("doctor_id", a.doctor_id)
    occupying = [i for i, r in enumerate(rows) if r.status not in FREE_STATUSES]
    check = [planned[i] for i in occupying]
    conflicts = svc.find_conflicts(p, check, doctor_id, clinic_id, exclude_ids=[r.id for r in rows])
    if conflicts:
        raise _conflict_error(check, conflicts)

    # Rows may swap slots among themselves; the DB constraints are re-checked at commit.
    db.session.execute(text("SET CONSTRAINTS ex_appointments_doctor, ex_appointments_clinic DEFERRED"))
    for r, (s, e) in zip(rows, planned):
        svc.apply_fields(r, data, resolved, old_clinic_location)
        r.starts_at, r.ends_at = s, e
    if "clinic" in resolved or "patient" in resolved:
        link_patient_to_clinic(p.center_id, a.patient_id, a.clinic_id, a.department_id)

    # Series template follows the edit.
    if "clinic" in resolved:
        series.clinic_id, series.department_id = resolved["clinic"].id, resolved["clinic"].department_id
    if "doctor_id" in resolved:
        series.doctor_id = resolved["doctor_id"]
    if "patient" in resolved:
        series.patient_id = resolved["patient"].id
    for k in ("location", "appointment_type", "reason", "notes"):
        if k in data:
            setattr(series, k, data[k])
    if "clinic" in resolved and "location" not in data:
        series.location = a.location
    if time_changed:
        series.start_time, series.duration_minutes = new_time, duration
    db.session.commit()
    return a


def cancel_series(p, series_id, from_appointment_id=None):
    """Cancel every *scheduled* occurrence of a series (or, with from_appointment_id, that occurrence
    and all later ones). Arrived/in-progress/completed/no-show occurrences are history and kept.
    Occurrences outside the principal's scope are untouched. Returns the cancelled rows."""
    from backend.app.core.timeutil import utcnow
    s = get_series(p, series_id)
    p.require("appointments.edit", clinic_id=s.clinic_id)
    stmt = svc.scoped_query(p).where(Appointment.series_id == s.id, Appointment.status == "scheduled")
    if from_appointment_id:
        start = db.session.execute(svc.scoped_query(p).where(
            Appointment.id == from_appointment_id, Appointment.series_id == s.id)).scalar_one_or_none()
        if start is None:
            raise NotFound("Appointment not found in this series")
        stmt = stmt.where(Appointment.starts_at >= start.starts_at)
    rows = db.session.execute(stmt.order_by(Appointment.starts_at).with_for_update()).scalars().all()
    now = utcnow()
    for r in rows:
        r.status = "cancelled"
        r.status_changed_at = now
    db.session.flush()
    if rows:
        svc.notify(p, rows[0], "appointment_cancelled", f"{len(rows)} appointments of a series cancelled")
    db.session.commit()
    return rows
