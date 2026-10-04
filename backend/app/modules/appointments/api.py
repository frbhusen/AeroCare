"""/api/v1/appointments — thin routes; logic in service.py / series.py / reminders.py."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.api import paginate
from backend.app.core.errors import ValidationError
from backend.app.core.timeutil import local_day_bounds, local_today
from backend.app.core.validation import (Date, DateTime, Enum, Id, Int, List, Obj, Str, Text, query_args,
                                         request_json, validate)
from backend.app.extensions import db
from . import reminders, series, service
from .models import APPOINTMENT_TYPES, STATUSES
from .recurrence import MAX_OCCURRENCES

bp = Blueprint("appointments", __name__, url_prefix="/appointments")

MAX_RANGE_DAYS = 92

COMMON = {
    "patient_id": Id(),
    "clinic_id": Id(),
    "doctor_id": Id(),
    "starts_at": DateTime(),
    "ends_at": DateTime(),
    "duration_minutes": Int(min_value=1, max_value=service.MAX_DURATION_MINUTES),
    "location": Str(max_len=200),
    "appointment_type": Str(max_len=40),
    "reason": Str(max_len=300),
    "notes": Text(max_len=5000),
}

FILTERS = {"from": Date(), "to": Date(), "clinic_id": Id(), "department_id": Id(), "doctor_id": Id(),
           "patient_id": Id(), "series_id": Id(), "status": Str(max_len=200)}


def _filters():
    f = query_args(FILTERS)
    start_day = f.get("from") or local_today()
    end_day = f.get("to") or start_day
    if end_day < start_day:
        raise ValidationError("Invalid date range", details={"to": "is before from"})
    if (end_day - start_day).days > MAX_RANGE_DAYS:
        raise ValidationError(f"Date range is limited to {MAX_RANGE_DAYS} days.", details={"to": "range too long"})
    f["start"], _ = local_day_bounds(start_day)
    _, f["end"] = local_day_bounds(end_day)
    if f.get("status"):
        statuses = [s.strip() for s in f["status"].split(",") if s.strip()]
        bad = [s for s in statuses if s not in STATUSES]
        if bad:
            raise ValidationError("Invalid status filter", details={"status": f"unknown: {', '.join(bad)}"})
        f["statuses"] = statuses
    return f


@bp.get("")
@login_required(perm="appointments.view")
def list_appointments():
    p = current_principal()
    f = _filters()
    if f.get("patient_id") and not request.args.get("from"):
        # Patient history view: no default date window.
        f.pop("start"), f.pop("end")
    out = paginate(db.session, service.list_statement(p, f), lambda a: a, default_per_page=50)
    out["items"] = service.serialize_many(out["items"])
    return jsonify(out)


@bp.get("/meta")
@login_required(perm="appointments.view")
def meta():
    p = current_principal()
    return jsonify({
        "statuses": list(STATUSES), "transitions": {k: list(v) for k, v in service.TRANSITIONS.items()},
        "appointment_types": list(APPOINTMENT_TYPES), "clinics": service.clinics_in_scope(p),
        "is_doctor": p.role == "doctor", "own_clinic_id": p.user.clinic_id if p.role == "doctor" else None,
        "own_doctor_id": p.user.id if p.role == "doctor" else None,
        "can": {k: p.has(f"appointments.{k}") for k in ("view", "create", "edit", "delete")},
        "max_occurrences": MAX_OCCURRENCES, "default_duration_minutes": service.DEFAULT_DURATION,
        "week_starts_on": "saturday",
    })


@bp.get("/doctors")
@login_required(perm="appointments.view")
def doctors():
    f = query_args({"clinic_id": Id(required=True)})
    return jsonify({"items": service.doctors_for_clinic(current_principal(), f["clinic_id"])})


@bp.get("/schedule")
@login_required(perm="appointments.view")
def schedule():
    f = query_args({"date": Date(), "view": Enum(["day", "week"]), "clinic_id": Id(), "department_id": Id(),
                    "doctor_id": Id(), "status": Str(max_len=200)})
    filters = {k: f[k] for k in ("clinic_id", "department_id", "doctor_id") if f.get(k)}
    if f.get("status"):
        filters["statuses"] = [s for s in f["status"].split(",") if s in STATUSES]
    return jsonify(service.schedule(current_principal(), f.get("date") or local_today(), f.get("view") or "day",
                                    filters))


@bp.get("/<int:appointment_id>")
@login_required(perm="appointments.view")
def get_appointment(appointment_id):
    return jsonify(service.serialize(service.get_appointment(current_principal(), appointment_id)))


@bp.post("")
@login_required(perm="appointments.create")
def create():
    schema = dict(COMMON, patient_id=Id(required=True), starts_at=DateTime(required=True))
    a = service.create(current_principal(), validate(request_json(), schema))
    return jsonify(service.serialize(a)), 201


@bp.post("/walk-in")
@login_required(perm="appointments.create")
def walk_in():
    schema = {k: COMMON[k] for k in ("clinic_id", "doctor_id", "duration_minutes", "appointment_type", "reason",
                                     "notes", "location")}
    schema["patient_id"] = Id(required=True)
    a = service.walk_in(current_principal(), validate(request_json(), schema))
    return jsonify(service.serialize(a)), 201


RULE = {"freq": Enum(["daily", "weekly", "monthly"], required=True), "interval": Int(min_value=1, max_value=52),
        "weekdays": List(Int(min_value=1, max_value=7), max_items=7), "count": Int(min_value=1, max_value=500),
        "until": Date()}


@bp.post("/recurring")
@login_required(perm="appointments.create")
def create_recurring():
    schema = dict(COMMON, patient_id=Id(required=True), starts_at=DateTime(required=True),
                  rule=Obj(RULE, required=True))
    s, items = series.create_recurring(current_principal(), validate(request_json(), schema))
    return jsonify({"series": series.serialize_series(s), "items": service.serialize_many(items)}), 201


@bp.get("/series/<int:series_id>")
@login_required(perm="appointments.view")
def get_series(series_id):
    p = current_principal()
    s = series.get_series(p, series_id)
    f = {"series_id": s.id}
    rows = db.session.execute(service.list_statement(p, f).limit(500)).scalars().all()
    return jsonify({"series": series.serialize_series(s), "items": service.serialize_many(rows)})


@bp.post("/series/<int:series_id>/cancel")
@login_required
def cancel_series(series_id):
    data = validate(request_json(), {"from_appointment_id": Id()})
    rows = series.cancel_series(current_principal(), series_id, data.get("from_appointment_id"))
    return jsonify({"cancelled": len(rows), "items": service.serialize_many(rows)})


@bp.put("/<int:appointment_id>")
@login_required(perm="appointments.edit")
def update(appointment_id):
    p = current_principal()
    schema = dict(COMMON, version=Int(required=True), mode=Enum(["this", "this_and_future"]))
    data = validate(request_json(), schema, partial=True)
    if "version" not in data:
        raise ValidationError("version is required for updates", details={"version": "is required"})
    a = service.get_appointment(p, appointment_id, perm="appointments.edit", for_update=True)
    a = service.update(p, a, data)
    return jsonify(service.serialize(a))


@bp.post("/<int:appointment_id>/status")
@login_required(perm="appointments.edit")
def change_status(appointment_id):
    p = current_principal()
    data = validate(request_json(), {"status": Enum(STATUSES, required=True), "version": Int(required=True)})
    a = service.get_appointment(p, appointment_id, perm="appointments.edit", for_update=True)
    return jsonify(service.serialize(service.change_status(p, a, data)))


@bp.delete("/<int:appointment_id>")
@login_required(perm="appointments.delete")
def delete(appointment_id):
    p = current_principal()
    a = service.get_appointment(p, appointment_id, perm="appointments.delete")
    return jsonify(service.delete(p, a)), 202


@bp.get("/reminders")
@login_required(perm="appointments.view")
def day_reminders():
    from datetime import timedelta
    f = query_args({"date": Date(), "lang": Enum(["ar", "en"]), "clinic_id": Id(), "doctor_id": Id()})
    day = f.get("date") or (local_today() + timedelta(days=1))
    return jsonify(reminders.day_reminders(current_principal(), day, f.get("lang") or "en", f.get("clinic_id"),
                                           f.get("doctor_id")))


@bp.post("/<int:appointment_id>/reminded")
@login_required(perm="appointments.view")
def mark_reminded(appointment_id):
    p = current_principal()
    return jsonify(reminders.mark_reminded(p, service.get_appointment(p, appointment_id)))


@bp.get("/<int:appointment_id>/whatsapp")
@login_required(perm="appointments.view")
def whatsapp(appointment_id):
    p = current_principal()
    lang = query_args({"lang": Enum(["ar", "en"])}).get("lang") or "en"
    a = service.get_appointment(p, appointment_id)
    return jsonify(reminders.whatsapp_link(p, a, lang))

