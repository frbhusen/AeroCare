"""Patients, appointments, dental treatments and doctor / clinic / department activity reports.

Every query: tenant filter + live rows + the principal's clinic clause on the owning clinic column,
plus optional department/clinic/doctor filters (validated in common.parse_filters)."""
from sqlalchemy import and_, exists, func, literal, select

from backend.app.core.errors import Forbidden, NotFound
from backend.app.extensions import db
from backend.app.models import Patient, PatientClinicLink, Prescription, Visit
from backend.app.modules.appointments.models import STATUSES as APPT_STATUSES, Appointment
from backend.app.modules.dentistry.models import Treatment
from backend.app.modules.laboratory.models import LabRequest
from backend.app.modules.radiology.models import RadiologyStudy
from .common import (bounded, col, group_col, group_label, local_day, local_month, money_str, names, rate,
                     sum_totals, user_roles)


def _filters(f, dept_col=None, clinic_col=None, doctor_col=None):
    out = []
    if f.department_id and dept_col is not None:
        out.append(dept_col == f.department_id)
    if f.clinic_id and clinic_col is not None:
        out.append(clinic_col == f.clinic_id)
    if f.doctor_id and doctor_col is not None:
        out.append(doctor_col == f.doctor_id)
    return out


def _sort_rows(rows, group_by):
    if group_by in ("day", "month"):
        return sorted(rows, key=lambda r: str(r["group"]))
    return sorted(rows, key=lambda r: (r["key"] is None, str(r["group"] or "").lower()))


# ---- patients -------------------------------------------------------------------
def patients(p, f):
    L = PatientClinicLink
    base = [p.tenant(Patient), Patient.live(), Patient.created_at >= f.start, Patient.created_at < f.end]
    link_join = and_(L.patient_id == Patient.id, L.health_center_id == Patient.health_center_id)
    link_conds = [p.clinic_clause(L.clinic_id)] + _filters(f, L.department_id, L.clinic_id)
    if f.department_id or f.clinic_id:
        scope = exists(select(L.id).where(link_join, *link_conds))
    else:
        scope = p.patient_clause(Patient.id)
    g = f.group_by
    n = func.count(func.distinct(Patient.id))
    if g in ("clinic", "department"):
        gexpr = L.clinic_id if g == "clinic" else L.department_id
        stmt = (select(gexpr, n).select_from(Patient).join(L, link_join).where(*base, *link_conds)
                .group_by(gexpr))
    else:
        gexpr = {"day": local_day(Patient.created_at), "month": local_month(Patient.created_at),
                 "gender": func.coalesce(Patient.gender, "unknown")}[g]
        stmt = select(gexpr, n).where(*base, scope).group_by(gexpr)
    data, truncated = bounded(stmt.order_by(gexpr))
    lbl = group_label(p, g, [r[0] for r in data])
    rows = _sort_rows([{"key": k, "group": lbl(k), "new_patients": c} for k, c in data], g)
    total = db.session.execute(select(n).where(*base, scope)).scalar_one()
    return {"columns": [group_col(g), col("new_patients")], "rows": rows,
            "totals": {"new_patients": total}, "truncated": truncated,
            "notes": ["A patient linked to several clinics/departments is counted in each group; "
                      "the total counts each patient once."] if g in ("clinic", "department") else []}


# ---- appointments ---------------------------------------------------------------
def _appt_conds(p, f):
    A = Appointment
    return [p.tenant(A), A.live(), p.clinic_clause(A.clinic_id), A.starts_at >= f.start, A.starts_at < f.end,
            *_filters(f, A.department_id, A.clinic_id, A.doctor_id)]


def appointments(p, f):
    A = Appointment
    g = f.group_by
    gexpr = {"none": literal("all"), "clinic": A.clinic_id, "doctor": A.doctor_id, "department": A.department_id,
             "day": local_day(A.starts_at), "month": local_month(A.starts_at)}[g]
    cols = [func.count(A.id)] + [func.count(A.id).filter(A.status == s) for s in APPT_STATUSES]
    stmt = select(gexpr, *cols).where(*_appt_conds(p, f))
    if g != "none":
        stmt = stmt.group_by(gexpr).order_by(gexpr)
    data, truncated = bounded(stmt)
    lbl = group_label(p, g, [r[0] for r in data]) if g != "none" else (lambda k: "All")
    rows = []
    for r in data:
        row = {"key": r[0] if g != "none" else None, "group": lbl(r[0]), "total": r[1]}
        row.update({s: r[2 + i] for i, s in enumerate(APPT_STATUSES)})
        row["no_show_rate"] = rate(row["no_show"], row["total"] - row["cancelled"])
        rows.append(row)
    if g == "none" and not rows[0]["total"]:
        rows[0]["no_show_rate"] = None
    columns = [group_col(g), col("total")] + [col(s) for s in APPT_STATUSES] + [col("no_show_rate", "percent")]
    totals = sum_totals(columns, rows)
    totals["no_show_rate"] = rate(totals["no_show"], totals["total"] - totals["cancelled"])
    return {"columns": columns, "rows": _sort_rows(rows, g) if g != "none" else rows,
            "totals": None if g == "none" else totals, "truncated": truncated,
            "notes": ["No-show rate = no-shows / (appointments - cancelled)."]}


# ---- dental treatments ------------------------------------------------------------
_PLANNED = ("planned", "accepted", "scheduled")


def treatments(p, f):
    T = Treatment
    g = f.group_by
    gexpr = {"procedure": func.coalesce(T.procedure, "unspecified"), "status": T.status, "clinic": T.clinic_id,
             "doctor": T.doctor_user_id, "month": local_month(T.date, is_date=True)}[g]
    with_fees = p.has("billing.view")
    cols = [func.count(T.id), func.count(T.id).filter(T.status == "completed"),
            func.count(T.id).filter(T.status == "in-progress"), func.count(T.id).filter(T.status.in_(_PLANNED)),
            func.count(T.id).filter(T.status == "cancelled")]
    if with_fees:
        cols.append(func.coalesce(func.sum(T.fee).filter(T.status == "completed"), 0))
    stmt = (select(gexpr, *cols)
            .where(p.tenant(T), T.live(), p.clinic_clause(T.clinic_id), T.date >= f.date_from, T.date <= f.date_to,
                   *_filters(f, T.department_id, T.clinic_id, T.doctor_user_id))
            .group_by(gexpr).order_by(gexpr))
    data, truncated = bounded(stmt)
    lbl = group_label(p, g, [r[0] for r in data])
    keys = ("total", "completed", "in_progress", "planned", "cancelled")
    rows = []
    for r in data:
        row = {"key": r[0], "group": lbl(r[0]), **{k: r[1 + i] for i, k in enumerate(keys)}}
        if with_fees:
            row["fees_completed"] = money_str(r[6])
        rows.append(row)
    columns = [group_col(g)] + [col(k) for k in keys] + ([col("fees_completed", "money")] if with_fees else [])
    return {"columns": columns, "rows": _sort_rows(rows, g), "totals": sum_totals(columns, rows),
            "truncated": truncated,
            "notes": ["Dental treatments by treatment date. Planned includes accepted and scheduled items."]}


# ---- doctor activity -------------------------------------------------------------------
def _merge(target, data, keys):
    for r in data:
        if r[0] is None:
            continue
        row = target.setdefault(r[0], {})
        for i, k in enumerate(keys):
            row[k] = (row.get(k) or 0) + (r[1 + i] or 0)


ACTIVITY_KEYS = ("appointments", "completed_appointments", "no_shows", "visits", "patients_seen",
                 "completed_treatments", "prescriptions")


def doctor_activity(p, f):
    A, V, T, R = Appointment, Visit, Treatment, Prescription
    acc = {}
    _merge(acc, db.session.execute(
        select(A.doctor_id, func.count(A.id).filter(A.status != "cancelled"),
               func.count(A.id).filter(A.status == "completed"), func.count(A.id).filter(A.status == "no_show"))
        .where(*_appt_conds(p, f), A.doctor_id.is_not(None)).group_by(A.doctor_id)).all(),
        ("appointments", "completed_appointments", "no_shows"))
    _merge(acc, db.session.execute(
        select(V.author_user_id, func.count(V.id), func.count(func.distinct(V.patient_id)))
        .where(p.tenant(V), V.live(), p.clinic_clause(V.clinic_id), V.visit_at >= f.start, V.visit_at < f.end,
               *_filters(f, V.department_id, V.clinic_id, V.author_user_id)).group_by(V.author_user_id)).all(),
        ("visits", "patients_seen"))
    _merge(acc, db.session.execute(
        select(T.doctor_user_id, func.count(T.id))
        .where(p.tenant(T), T.live(), p.clinic_clause(T.clinic_id), T.status == "completed",
               T.date >= f.date_from, T.date <= f.date_to,
               *_filters(f, T.department_id, T.clinic_id, T.doctor_user_id)).group_by(T.doctor_user_id)).all(),
        ("completed_treatments",))
    _merge(acc, db.session.execute(
        select(R.author_user_id, func.count(R.id))
        .where(p.tenant(R), R.live(), p.clinic_clause(R.clinic_id), R.status != "cancelled",
               R.prescribed_at >= f.start, R.prescribed_at < f.end,
               *_filters(f, R.department_id, R.clinic_id, R.author_user_id)).group_by(R.author_user_id)).all(),
        ("prescriptions",))
    nm, roles = names(p, "doctor", acc), user_roles(p, acc)
    rows = [{"key": uid, "group": nm.get(uid) or f"#{uid}", "role": roles.get(uid),
             **{k: v.get(k, 0) for k in ACTIVITY_KEYS}} for uid, v in acc.items()]
    rows.sort(key=lambda r: r["group"].lower())
    truncated = len(rows) > 1000
    columns = [col("group", "text", "doctor"), col("role", "text")] + [col(k) for k in ACTIVITY_KEYS]
    return {"columns": columns, "rows": rows[:1000], "totals": sum_totals(columns, rows, skip=("group", "role")),
            "truncated": truncated,
            "notes": ["Appointments exclude cancelled ones. Visits and prescriptions are attributed to their "
                      "author; treatments to the assigned doctor."]}


# ---- clinic / department activity ------------------------------------------------------
def _activity(p, f, level):
    clinic = level == "clinic"
    restrict = None
    if not clinic and not p.center_wide:
        restrict = sorted(p.managed_department_ids)

    def dim(clinic_col, dept_col):
        return clinic_col if clinic else dept_col

    def scope(clinic_col, dept_col):
        out = [p.clinic_clause(clinic_col), *_filters(f, dept_col, clinic_col)]
        if restrict is not None:
            out.append(dept_col.in_(restrict or [-1]))
        return out

    A, V, T, R, L = Appointment, Visit, Treatment, Prescription, PatientClinicLink
    acc = {}
    d = dim(A.clinic_id, A.department_id)
    _merge(acc, db.session.execute(
        select(d, func.count(A.id).filter(A.status != "cancelled"), func.count(A.id).filter(A.status == "completed"),
               func.count(A.id).filter(A.status == "no_show"))
        .where(p.tenant(A), A.live(), A.starts_at >= f.start, A.starts_at < f.end,
               *scope(A.clinic_id, A.department_id)).group_by(d)).all(),
        ("appointments", "completed_appointments", "no_shows"))
    d = dim(V.clinic_id, V.department_id)
    _merge(acc, db.session.execute(
        select(d, func.count(V.id), func.count(func.distinct(V.patient_id)))
        .where(p.tenant(V), V.live(), V.visit_at >= f.start, V.visit_at < f.end, *scope(V.clinic_id, V.department_id))
        .group_by(d)).all(), ("visits", "patients_seen"))
    d = dim(L.clinic_id, L.department_id)
    _merge(acc, db.session.execute(
        select(d, func.count(func.distinct(L.patient_id)))
        .where(p.tenant(L), L.created_at >= f.start, L.created_at < f.end, *scope(L.clinic_id, L.department_id))
        .group_by(d)).all(), ("new_patient_links",))
    d = dim(T.clinic_id, T.department_id)
    _merge(acc, db.session.execute(
        select(d, func.count(T.id))
        .where(p.tenant(T), T.live(), T.status == "completed", T.date >= f.date_from, T.date <= f.date_to,
               *scope(T.clinic_id, T.department_id)).group_by(d)).all(), ("completed_treatments",))
    d = dim(R.clinic_id, R.department_id)
    _merge(acc, db.session.execute(
        select(d, func.count(R.id))
        .where(p.tenant(R), R.live(), R.status != "cancelled", R.prescribed_at >= f.start, R.prescribed_at < f.end,
               *scope(R.clinic_id, R.department_id)).group_by(d)).all(), ("prescriptions",))
    for model, key in ((LabRequest, "lab_requests"), (RadiologyStudy, "radiology_requests")):
        d = dim(model.requesting_clinic_id, model.requesting_department_id)
        _merge(acc, db.session.execute(
            select(d, func.count(model.id))
            .where(p.tenant(model), model.live(), model.status != "cancelled", model.requested_at >= f.start,
                   model.requested_at < f.end, *scope(model.requesting_clinic_id, model.requesting_department_id))
            .group_by(d)).all(), (key,))

    keys = ["appointments", "completed_appointments", "no_shows", "visits", "patients_seen", "new_patient_links",
            "completed_treatments", "prescriptions", "lab_requests", "radiology_requests"]
    money_keys = []
    if p.has("billing.view"):
        from backend.app.modules.billing.summary import summary
        args = {"group_by": level, "department_id": f.department_id, "clinic_id": f.clinic_id}
        res = summary(p, args, f.start, f.end)
        for r in res["rows"]:
            if r["key"] is None or (restrict is not None and r["key"] not in restrict):
                continue
            row = acc.setdefault(r["key"], {})
            row["revenue"], row["payments_received"] = r["revenue"], r["payments_received"]
        money_keys = ["revenue", "payments_received"]

    # include in-scope units with no activity
    if clinic:
        base = [c for c, dep in p.clinic_department.items()
                if (not f.department_id or dep == f.department_id) and (not f.clinic_id or c == f.clinic_id)]
    else:
        base = [dep for dep in (p.managed_department_ids if restrict is not None else p.department_env)
                if not f.department_id or dep == f.department_id]
        if f.clinic_id:
            base = [p.clinic_department.get(f.clinic_id)]
    for k in base:
        if k is not None:
            acc.setdefault(k, {})
    nm = names(p, level, acc)
    rows = []
    for k, v in acc.items():
        row = {"key": k, "group": nm.get(k) or f"#{k}", **{m: v.get(m, 0) for m in keys}}
        for m in money_keys:
            row[m] = v.get(m) or "0.00"
        rows.append(row)
    rows.sort(key=lambda r: r["group"].lower())
    columns = [group_col(level)] + [col(k) for k in keys] + [col(k, "money") for k in money_keys]
    return {"columns": columns, "rows": rows[:1000], "totals": sum_totals(columns, rows),
            "truncated": len(rows) > 1000,
            "notes": ["New patients = patients first linked to the unit in the period. Lab/radiology = requests "
                      "made by the unit. Revenue = invoices issued in the period (needs billing.view)."]}


def clinic_activity(p, f):
    return _activity(p, f, "clinic")


def department_activity(p, f):
    if not p.managed_department_ids:
        raise Forbidden("Department-level access is required for this report.", code="department_scope_required")
    if f.department_id and not p.can_department(f.department_id):
        raise NotFound("Department not found")
    if f.clinic_id and not p.can_department(p.clinic_department.get(f.clinic_id)):
        raise NotFound("Clinic not found")
    return _activity(p, f, "department")
