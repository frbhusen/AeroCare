"""Appointment business logic (spec §44-50, §73, §76).

Scope: an appointment is owned by its clinic. Lists use `p.clinic_clause(Appointment.clinic_id)`;
single loads go through `get_appointment` (out of scope -> 404).
Double-booking: friendly pre-check here (`find_conflicts`), authoritative exclusion constraints in
the database (models.py) so simultaneous requests can never both succeed.
"""
from datetime import timedelta

from sqlalchemy import and_, or_, select

from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.timeutil import iso, to_local, utcnow
from backend.app.extensions import db
from backend.app.models import Clinic, Department, Patient, User
from backend.app.services import deletion, notifications
from backend.app.services.clinical import get_clinic, link_patient_to_clinic
from .models import FREE_STATUSES, Appointment

DEFAULT_DURATION = 15
MAX_DURATION_MINUTES = 24 * 60
DOCTOR_ROLES = ("doctor", "department_manager")

# Allowed status changes (spec §47 statuses, exact codes).
TRANSITIONS = {
    "scheduled": ("arrived", "in_progress", "completed", "cancelled", "no_show"),
    "arrived": ("scheduled", "in_progress", "completed", "cancelled", "no_show"),
    "in_progress": ("arrived", "completed", "cancelled"),
    "completed": ("in_progress",),
    "cancelled": ("scheduled",),
    "no_show": ("scheduled", "arrived"),
}

deletion.register("appointment", Appointment)


# ---------------------------------------------------------------- loading / scope
def scoped_query(p):
    return select(Appointment).where(p.tenant(Appointment), Appointment.live(),
                                     p.clinic_clause(Appointment.clinic_id))


def get_appointment(p, appointment_id, perm="appointments.view", for_update=False):
    stmt = scoped_query(p).where(Appointment.id == appointment_id)
    if for_update:
        stmt = stmt.with_for_update()
    a = db.session.execute(stmt).scalar_one_or_none()
    if a is None or not p.can_clinic(a.clinic_id):
        raise NotFound("Appointment not found")
    if perm:
        p.require(perm, clinic_id=a.clinic_id)
    return a


def center_patient(p, patient_id):
    """The patient must exist (live) in this center. Visibility to the clinic is granted by
    the clinic link created when the appointment is booked."""
    pt = db.session.execute(select(Patient).where(Patient.id == patient_id, p.tenant(Patient), Patient.live())
                            ).scalar_one_or_none()
    if pt is None:
        raise NotFound("Patient not found")
    return pt


def validate_doctor(p, doctor_id, clinic_id):
    u = db.session.execute(select(User).where(
        User.id == doctor_id, User.health_center_id == p.center_id, User.status == "active",
        User.role.in_(DOCTOR_ROLES), User.clinic_id == clinic_id)).scalar_one_or_none()
    if u is None:
        raise ValidationError("The selected doctor does not work in this clinic.",
                              details={"doctor_id": "is not a doctor of this clinic"})
    return u


def resolve_place(p, clinic_id=None, doctor_id=None, doctor_given=False):
    """(clinic, doctor_id). A doctor creator is auto-assigned with their clinic (spec §45)."""
    if p.role == "doctor":
        if not p.user.clinic_id or not p.can_clinic(p.user.clinic_id):
            raise NotFound("Clinic not found")
        return get_clinic(p, p.user.clinic_id), p.user.id
    if not clinic_id:
        raise ValidationError("Clinic is required.", details={"clinic_id": "is required"})
    clinic = get_clinic(p, clinic_id)
    if doctor_given and doctor_id:
        validate_doctor(p, doctor_id, clinic.id)
    return clinic, (doctor_id if doctor_given else None)


def clinic_default_duration(clinic):
    """Minutes. Clinic settings override department settings (spec §93/§94)."""
    for settings in ((clinic.settings or {}), (getattr(clinic.department, "settings", None) or {})):
        v = settings.get("appointment_duration_minutes")
        if isinstance(v, int) and 0 < v <= MAX_DURATION_MINUTES:
            return v
    return DEFAULT_DURATION


# ---------------------------------------------------------------- times / conflicts
def normalize_dt(dt):
    return dt.replace(second=0, microsecond=0) if dt else dt


def compute_end(start, ends_at=None, duration_minutes=None, fallback_minutes=None):
    if ends_at is None:
        minutes = duration_minutes or fallback_minutes
        if not minutes:
            raise ValidationError("End time or duration is required.", details={"ends_at": "is required"})
        ends_at = start + timedelta(minutes=minutes)
    ends_at = normalize_dt(ends_at)
    if ends_at <= start:
        raise ValidationError("The end time must be after the start time.", details={"ends_at": "must be after start"})
    if ends_at - start > timedelta(minutes=MAX_DURATION_MINUTES):
        raise ValidationError("An appointment cannot be longer than 24 hours.", details={"ends_at": "too long"})
    return ends_at


def find_conflicts(p, intervals, doctor_id, clinic_id, exclude_ids=()):
    """intervals: list of (start, end). Returns {index: [conflict dicts]} for intervals that
    overlap a live slot-occupying appointment of the same doctor or clinic (or each other).
    Conflict details never include patient data (the other appointment may be out of scope)."""
    if not intervals:
        return {}
    lo = min(s for s, _ in intervals)
    hi = max(e for _, e in intervals)
    who = [Appointment.clinic_id == clinic_id]
    if doctor_id:
        who.append(Appointment.doctor_id == doctor_id)
    stmt = select(Appointment.id, Appointment.doctor_id, Appointment.clinic_id, Appointment.starts_at,
                  Appointment.ends_at).where(
        p.tenant(Appointment), Appointment.live(), Appointment.status.notin_(FREE_STATUSES), or_(*who),
        Appointment.starts_at < hi, Appointment.ends_at > lo)
    if exclude_ids:
        stmt = stmt.where(Appointment.id.notin_(list(exclude_ids)))
    rows = db.session.execute(stmt).all()
    out = {}
    for i, (s, e) in enumerate(intervals):
        hits = []
        for r in rows:
            if r.starts_at < e and r.ends_at > s:
                kind = "doctor" if doctor_id and r.doctor_id == doctor_id else "clinic"
                hits.append({"appointment_id": r.id if p.can_clinic(r.clinic_id) else None, "kind": kind,
                             "starts_at": iso(r.starts_at), "ends_at": iso(r.ends_at)})
        for j, (s2, e2) in enumerate(intervals):
            if j != i and s2 < e and e2 > s:
                hits.append({"appointment_id": None, "kind": "series", "starts_at": iso(s2), "ends_at": iso(e2)})
        if hits:
            out[i] = hits
    return out


def raise_if_conflicts(p, start, end, doctor_id, clinic_id, exclude_ids=()):
    c = find_conflicts(p, [(start, end)], doctor_id, clinic_id, exclude_ids)
    if c:
        kinds = {h["kind"] for h in c[0]}
        who = "doctor" if "doctor" in kinds else "clinic"
        raise Conflict(f"The {who} already has an appointment at that time.", code="appointment_conflict",
                       details={"conflicts": c[0]})


# ---------------------------------------------------------------- serialization
def _hhmm(dt):
    return to_local(dt).strftime("%H:%M")


def serialize_many(rows):
    rows = list(rows)
    if not rows:
        return []
    pids = {r.patient_id for r in rows}
    cids = {r.clinic_id for r in rows}
    dids = {r.department_id for r in rows}
    uids = {r.doctor_id for r in rows if r.doctor_id}
    patients = {i: (n, c, ph) for i, n, c, ph in db.session.execute(
        select(Patient.id, Patient.full_name, Patient.code, Patient.phone).where(Patient.id.in_(pids)))}
    clinics = {i: n for i, n in db.session.execute(select(Clinic.id, Clinic.name).where(Clinic.id.in_(cids)))}
    depts = {i: n for i, n in db.session.execute(select(Department.id, Department.name)
                                                  .where(Department.id.in_(dids)))}
    doctors = {i: n for i, n in db.session.execute(select(User.id, User.name).where(User.id.in_(uids)))} \
        if uids else {}
    out = []
    for a in rows:
        pt = patients.get(a.patient_id)
        local_start = to_local(a.starts_at)
        out.append({
            "id": a.id, "version": a.version, "status": a.status,
            "starts_at": iso(a.starts_at), "ends_at": iso(a.ends_at),
            "local_date": local_start.date().isoformat(), "start_time": _hhmm(a.starts_at),
            "end_time": _hhmm(a.ends_at),
            "duration_minutes": int((a.ends_at - a.starts_at).total_seconds() // 60),
            "patient": {"id": a.patient_id, "name": pt[0] if pt else None,
                        "code": f"PAT-{pt[1]:06d}" if pt else None, "phone": pt[2] if pt else None},
            "clinic": {"id": a.clinic_id, "name": clinics.get(a.clinic_id)},
            "department": {"id": a.department_id, "name": depts.get(a.department_id)},
            "doctor": {"id": a.doctor_id, "name": doctors.get(a.doctor_id)} if a.doctor_id else None,
            "location": a.location, "appointment_type": a.appointment_type, "reason": a.reason, "notes": a.notes,
            "is_walk_in": a.is_walk_in, "series_id": a.series_id, "series_index": a.series_index,
            "created_by": {"id": a.author_user_id, "name": a.author_name, "role": a.author_role},
            "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
            "status_changed_at": iso(a.status_changed_at),
        })
    return out


def serialize(a):
    return serialize_many([a])[0]


def label(a):
    return f"Appointment {to_local(a.starts_at).strftime('%m/%d/%Y %H:%M')}"


# ---------------------------------------------------------------- notifications
def notify(p, a, type_, title):
    notifications.notify(p.center_id, type_, title, body=f"{to_local(a.starts_at).strftime('%m/%d %H:%M')}",
                         link=f"/appointments/{a.id}", clinic_id=a.clinic_id, department_id=a.department_id,
                         user_ids=[a.doctor_id] if a.doctor_id else None, exclude_user_id=p.user.id)


# ---------------------------------------------------------------- create / edit
def new_appointment(p, *, clinic, doctor_id, patient, starts_at, ends_at, data, status="scheduled",
                    is_walk_in=False, series=None, series_index=None):
    a = Appointment(health_center_id=p.center_id, department_id=clinic.department_id, clinic_id=clinic.id,
                    doctor_id=doctor_id, patient_id=patient.id, starts_at=starts_at, ends_at=ends_at,
                    location=data.get("location") or clinic.location, appointment_type=data.get("appointment_type"),
                    reason=data.get("reason"), notes=data.get("notes"), status=status, is_walk_in=is_walk_in,
                    series_id=series.id if series else None, series_index=series_index)
    if status != "scheduled":
        a.status_changed_at = utcnow()
    a.set_author(p.user)
    db.session.add(a)
    return a


def create(p, data):
    p.require("appointments.create")
    clinic, doctor_id = resolve_place(p, data.get("clinic_id"), data.get("doctor_id"), "doctor_id" in data)
    p.require("appointments.create", clinic_id=clinic.id)
    patient = center_patient(p, data["patient_id"])
    start = normalize_dt(data["starts_at"])
    end = compute_end(start, data.get("ends_at"), data.get("duration_minutes"), clinic_default_duration(clinic))
    raise_if_conflicts(p, start, end, doctor_id, clinic.id)
    link_patient_to_clinic(p.center_id, patient.id, clinic.id, clinic.department_id)
    a = new_appointment(p, clinic=clinic, doctor_id=doctor_id, patient=patient, starts_at=start, ends_at=end,
                        data=data)
    db.session.flush()
    notify(p, a, "appointment_created", "New appointment")
    db.session.commit()
    return a


def walk_in(p, data):
    p.require("appointments.create")
    clinic, doctor_id = resolve_place(p, data.get("clinic_id"), data.get("doctor_id"), "doctor_id" in data)
    p.require("appointments.create", clinic_id=clinic.id)
    patient = center_patient(p, data["patient_id"])
    start = normalize_dt(utcnow())
    end = compute_end(start, None, data.get("duration_minutes"), clinic_default_duration(clinic))
    raise_if_conflicts(p, start, end, doctor_id, clinic.id)
    link_patient_to_clinic(p.center_id, patient.id, clinic.id, clinic.department_id)
    a = new_appointment(p, clinic=clinic, doctor_id=doctor_id, patient=patient, starts_at=start, ends_at=end,
                        data=data, status="arrived", is_walk_in=True)
    db.session.flush()
    notify(p, a, "patient_arrived", "Patient arrived (walk-in)")
    db.session.commit()
    return a


def plan_edit(p, a, data):
    """Resolve the target clinic/doctor/patient for an edit (shared by single and series edits).
    Returns dict of resolved values (only keys that change)."""
    out = {}
    clinic = None
    if "clinic_id" in data and data["clinic_id"] != a.clinic_id:
        if p.role == "doctor" or not data["clinic_id"]:
            raise ValidationError("The clinic cannot be changed.", details={"clinic_id": "cannot be changed"})
        clinic = get_clinic(p, data["clinic_id"])
        p.require("appointments.edit", clinic_id=clinic.id)
        out["clinic"] = clinic
    target_clinic_id = clinic.id if clinic else a.clinic_id
    if "doctor_id" in data and data["doctor_id"] != a.doctor_id:
        if p.role == "doctor":
            raise ValidationError("The doctor cannot be changed.", details={"doctor_id": "cannot be changed"})
        if data["doctor_id"]:
            validate_doctor(p, data["doctor_id"], target_clinic_id)
        out["doctor_id"] = data["doctor_id"]
    elif clinic and a.doctor_id:
        # Clinic changed but doctor kept: the doctor must work in the new clinic.
        validate_doctor(p, a.doctor_id, target_clinic_id)
    if "patient_id" in data and data["patient_id"] != a.patient_id:
        if not data["patient_id"]:
            raise ValidationError("Patient is required.", details={"patient_id": "is required"})
        out["patient"] = center_patient(p, data["patient_id"])
    return out


def apply_fields(a, data, resolved, old_clinic_location):
    clinic = resolved.get("clinic")
    if clinic:
        a.clinic_id, a.department_id = clinic.id, clinic.department_id
        if "location" not in data and (a.location or None) == (old_clinic_location or None):
            a.location = clinic.location
    if "doctor_id" in resolved:
        a.doctor_id = resolved["doctor_id"]
    if "patient" in resolved:
        a.patient_id = resolved["patient"].id
    for k in ("location", "appointment_type", "reason", "notes"):
        if k in data:
            setattr(a, k, data[k])


def update(p, a, data):
    p.require("appointments.edit", clinic_id=a.clinic_id)
    check_version(a, data.get("version"))
    if data.get("mode") == "this_and_future" and a.series_id:
        from .series import update_this_and_future
        return update_this_and_future(p, a, data)
    resolved = plan_edit(p, a, data)
    old_clinic_location = db.session.execute(select(Clinic.location).where(Clinic.id == a.clinic_id)).scalar()
    start = normalize_dt(data["starts_at"]) if data.get("starts_at") else a.starts_at
    if data.get("ends_at") or data.get("duration_minutes"):
        end = compute_end(start, data.get("ends_at"), data.get("duration_minutes"))
    else:
        end = compute_end(start, None, int((a.ends_at - a.starts_at).total_seconds() // 60))
    clinic_id = resolved["clinic"].id if "clinic" in resolved else a.clinic_id
    doctor_id = resolved.get("doctor_id", a.doctor_id)
    if a.status not in FREE_STATUSES:
        raise_if_conflicts(p, start, end, doctor_id, clinic_id, exclude_ids=[a.id])
    apply_fields(a, data, resolved, old_clinic_location)
    a.starts_at, a.ends_at = start, end
    if "clinic" in resolved or "patient" in resolved:
        link_patient_to_clinic(p.center_id, a.patient_id, a.clinic_id, a.department_id)
    db.session.commit()
    return a


def change_status(p, a, data):
    p.require("appointments.edit", clinic_id=a.clinic_id)
    check_version(a, data.get("version"))
    new = data["status"]
    if new == a.status:
        return a
    if new not in TRANSITIONS.get(a.status, ()):
        raise ValidationError(f"Cannot change status from {a.status} to {new}.", code="invalid_transition",
                              details={"status": f"not allowed from {a.status}",
                                       "allowed": list(TRANSITIONS.get(a.status, ()))})
    if a.status in FREE_STATUSES and new not in FREE_STATUSES:
        raise_if_conflicts(p, a.starts_at, a.ends_at, a.doctor_id, a.clinic_id, exclude_ids=[a.id])
    a.status = new
    a.status_changed_at = utcnow()
    db.session.flush()
    if new == "cancelled":
        notify(p, a, "appointment_cancelled", "Appointment cancelled")
    elif new == "arrived":
        notify(p, a, "patient_arrived", "Patient arrived")
    db.session.commit()
    return a


def delete(p, a):
    p.require("appointments.delete", clinic_id=a.clinic_id)
    return deletion.stage(p, a, "appointment", label(a))


# ---------------------------------------------------------------- reads
def list_statement(p, f):
    stmt = scoped_query(p)
    if f.get("start"):
        stmt = stmt.where(Appointment.ends_at > f["start"])
    if f.get("end"):
        stmt = stmt.where(Appointment.starts_at < f["end"])
    for key, col in (("clinic_id", Appointment.clinic_id), ("department_id", Appointment.department_id),
                     ("doctor_id", Appointment.doctor_id), ("patient_id", Appointment.patient_id),
                     ("series_id", Appointment.series_id)):
        if f.get(key):
            stmt = stmt.where(col == f[key])
    if f.get("statuses"):
        stmt = stmt.where(Appointment.status.in_(f["statuses"]))
    return stmt.order_by(Appointment.starts_at, Appointment.id)


def doctors_for_clinic(p, clinic_id):
    p.require("appointments.view")
    clinic = get_clinic(p, clinic_id)
    rows = db.session.execute(select(User).where(
        User.health_center_id == p.center_id, User.status == "active", User.role.in_(DOCTOR_ROLES),
        User.clinic_id == clinic.id).order_by(User.name)).scalars().all()
    return [{"id": u.id, "name": u.name, "role": u.role, "specialty_title": u.specialty_title} for u in rows]


def clinics_in_scope(p):
    if not p.clinic_ids:
        return []
    rows = db.session.execute(select(Clinic, Department.name, Department.settings)
                              .join(Department, and_(Department.id == Clinic.department_id,
                                                     Department.health_center_id == Clinic.health_center_id))
                              .where(p.tenant(Clinic), Clinic.id.in_(sorted(p.clinic_ids)))
                              .order_by(Department.name, Clinic.name)).all()
    return [{"id": c.id, "name": c.name, "location": c.location, "department_id": c.department_id,
             "department_name": dname, "default_duration_minutes": clinic_default_duration(c)}
            for c, dname, _ in rows]


def schedule(p, day, view="day", filters=None):
    """Day or week (Saturday-start, the local working week) grouped by local date."""
    from backend.app.core.timeutil import local_day_bounds
    if view == "week":
        first = day - timedelta(days=(day.weekday() - 5) % 7)  # Saturday on or before `day`
        days = [first + timedelta(days=i) for i in range(7)]
    else:
        days = [day]
    start, _ = local_day_bounds(days[0])
    _, end = local_day_bounds(days[-1])
    f = dict(filters or {}, start=start, end=end)
    rows = db.session.execute(list_statement(p, f).limit(2000)).scalars().all()
    items = serialize_many(rows)
    by_day = {d.isoformat(): [] for d in days}
    for it in items:
        by_day.setdefault(it["local_date"], []).append(it)
    return {"view": view, "start_date": days[0].isoformat(), "end_date": days[-1].isoformat(),
            "days": [{"date": d, "items": by_day[d]} for d in sorted(by_day) if d in {x.isoformat() for x in days}]}
