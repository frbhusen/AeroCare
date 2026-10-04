"""Report registry, permission gate, catalog and the uniform report envelope.

Permission chain for every report (spec §105 — reports never bypass normal permissions):
  reports.view (+ reports.export for exports) -> the report's data permissions (e.g. billing.view)
  -> scope (department / clinic / doctor filters must be inside the principal's scope, else 404)
  -> every query is tenant + clinic/department scoped.
"""
from sqlalchemy import or_, select

from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, local_today, utcnow
from backend.app.extensions import db
from . import clinical, financial, operations
from .common import DEFAULT_SPAN_DAYS, MAX_ROWS, label, parse_filters

_ORG = ["date_from", "date_to", "department_id", "clinic_id"]

# key -> spec. `perms_all`: every permission required; `perms_any`: at least one required.
REPORTS = {
    "patients": {"fn": clinical.patients, "perms_all": ["patients.view"], "filters": _ORG,
                 "groups": ["clinic", "department", "day", "month", "gender"], "default_group": "clinic",
                 "title": ("New patients", "المرضى الجدد")},
    "appointments": {"fn": clinical.appointments, "perms_all": ["appointments.view"],
                     "filters": _ORG + ["doctor_id"],
                     "groups": ["none", "clinic", "doctor", "department", "day", "month"],
                     "default_group": "clinic", "title": ("Appointments", "المواعيد")},
    "doctor_activity": {"fn": clinical.doctor_activity, "perms_all": ["appointments.view", "medical_records.view"],
                        "filters": _ORG + ["doctor_id"], "title": ("Doctor activity", "نشاط الأطباء")},
    "clinic_activity": {"fn": clinical.clinic_activity, "perms_all": ["appointments.view", "medical_records.view"],
                        "filters": _ORG, "title": ("Clinic activity", "نشاط العيادات")},
    "department_activity": {"fn": clinical.department_activity,
                            "perms_all": ["appointments.view", "medical_records.view"], "filters": _ORG,
                            "department_level": True, "title": ("Department activity", "نشاط الأقسام")},
    "revenue": {"fn": financial.revenue, "perms_all": ["billing.view"], "filters": _ORG + ["doctor_id"],
                "groups": ["none", "department", "clinic", "doctor"], "default_group": "clinic",
                "title": ("Revenue and payments", "الإيرادات والمدفوعات")},
    "outstanding": {"fn": financial.outstanding, "perms_all": ["billing.view"],
                    "filters": ["department_id", "clinic_id", "doctor_id"],
                    "title": ("Outstanding balances", "الأرصدة المستحقة")},
    "services": {"fn": financial.services, "perms_all": ["billing.view"], "filters": _ORG + ["doctor_id"],
                 "groups": ["service", "kind"], "default_group": "service",
                 "title": ("Services billed", "الخدمات المفوترة")},
    "treatments": {"fn": clinical.treatments, "perms_all": ["medical_records.view"], "filters": _ORG + ["doctor_id"],
                   "groups": ["procedure", "status", "clinic", "doctor", "month"], "default_group": "procedure",
                   "environment": "dentistry", "title": ("Dental treatments", "معالجات الأسنان")},
    "inventory": {"fn": operations.inventory, "perms_all": ["inventory.view"],
                  "filters": _ORG + ["location_id", "days"], "views": ["stock", "low_stock", "expiry", "movements"],
                  "title": ("Inventory", "المخزون")},
    "laboratory": {"fn": operations.laboratory, "perms_any": ["lab.request", "lab.process", "medical_records.view"],
                   "filters": _ORG + ["doctor_id"], "groups": ["test", "status", "clinic", "day", "month"],
                   "default_group": "test", "title": ("Laboratory", "المخبر")},
    "radiology": {"fn": operations.radiology,
                  "perms_any": ["radiology.request", "radiology.process", "medical_records.view"],
                  "filters": _ORG + ["doctor_id"], "groups": ["exam_type", "status", "clinic", "day", "month"],
                  "default_group": "exam_type", "title": ("Radiology", "الأشعة")},
}


def get_spec(key):
    spec = REPORTS.get(key)
    if spec is None:
        raise NotFound("Report not found")
    return spec


def _missing(p, spec):
    """First missing permission (or None)."""
    for perm in spec.get("perms_all", []):
        if not p.has(perm):
            return perm
    anyp = spec.get("perms_any")
    if anyp and not any(p.has(x) for x in anyp):
        return anyp[0]
    return None


def require_report(p, key, export=False):
    spec = get_spec(key)
    for perm in ["reports.view"] + (["reports.export"] if export else []):
        p.require(perm)
    miss = _missing(p, spec)
    if miss:
        raise Forbidden("You do not have permission to run this report.", details={"permission": miss})
    if spec.get("department_level") and not p.managed_department_ids:
        raise Forbidden("Department-level access is required for this report.", code="department_scope_required")
    return spec


def run(p, key, args, export=False):
    spec = require_report(p, key, export)
    f = parse_filters(p, spec, args)
    out = spec["fn"](p, f)
    title_en, title_ar = spec["title"]
    columns = out["columns"]
    wanted = args.get("columns")
    if wanted:
        columns = select_columns(columns, wanted)
    return {"report": key, "title": title_en, "title_ar": title_ar, "generated_at": iso(utcnow()),
            "filters": f.to_json(), "filter_labels": f.labels, "columns": columns, "rows": out["rows"],
            "totals": out.get("totals"), "meta": out.get("meta") or {}, "notes": out.get("notes") or [],
            "truncated": bool(out.get("truncated")), "row_limit": MAX_ROWS}


def select_columns(columns, wanted):
    """`wanted`: comma-separated column keys (order respected). Unknown keys -> 422."""
    keys = [k.strip() for k in str(wanted).split(",") if k.strip()]
    by_key = {c["key"]: c for c in columns}
    unknown = [k for k in keys if k not in by_key]
    if unknown or not keys:
        raise ValidationError("Invalid input", details={
            "columns": ("unknown columns: " + ", ".join(unknown)) if unknown else "at least one column is required"})
    return [by_key[k] for k in dict.fromkeys(keys)]


# ---- catalog -----------------------------------------------------------------------------
def catalog(p):
    """Reports the principal may run, their filters/groupings, and the filter choices in scope."""
    p.require("reports.view")
    from backend.app.models import Clinic, Department, User
    envs = set(p.department_env.values())
    can_export = p.has("reports.export")
    reports = []
    for key, spec in REPORTS.items():
        if _missing(p, spec) or (spec.get("department_level") and not p.managed_department_ids):
            continue
        if spec.get("environment") and spec["environment"] not in envs:
            continue
        reports.append({"key": key, "title": spec["title"][0], "title_ar": spec["title"][1],
                        "filters": spec["filters"], "group_by": spec.get("groups") or [],
                        "default_group": spec.get("default_group"), "views": spec.get("views") or [],
                        "group_labels": {g: [label(g), label(g, "ar")] for g in spec.get("groups") or []},
                        "can_export": can_export})
    depts = db.session.execute(select(Department.id, Department.name).where(
        p.tenant(Department), Department.id.in_(sorted(p.visible_department_ids) or [-1]))
        .order_by(Department.name)).all()
    clinics = db.session.execute(select(Clinic.id, Clinic.name, Clinic.department_id).where(
        p.tenant(Clinic), Clinic.id.in_(sorted(p.clinic_ids) or [-1])).order_by(Clinic.name)).all()
    doc_q = select(User.id, User.name, User.role, User.clinic_id, User.department_id).where(
        User.health_center_id == p.center_id, User.status == "active",
        User.role.in_(("doctor", "department_manager")))
    if not p.center_wide:
        doc_q = doc_q.where(or_(User.clinic_id.in_(sorted(p.clinic_ids) or [-1]),
                                User.department_id.in_(sorted(p.visible_department_ids) or [-1])))
    doctors = db.session.execute(doc_q.order_by(User.name).limit(MAX_ROWS)).all()
    today = local_today()
    from datetime import timedelta
    return {
        "reports": reports, "formats": ["xlsx", "pdf"] if can_export else [],
        "default_range": {"date_from": (today - timedelta(days=DEFAULT_SPAN_DAYS - 1)).isoformat(),
                          "date_to": today.isoformat()},
        "departments": [{"id": i, "name": n, "environment": p.department_env.get(i)} for i, n in depts],
        "clinics": [{"id": i, "name": n, "department_id": d} for i, n, d in clinics],
        "doctors": [{"id": i, "name": n, "role": r, "clinic_id": c, "department_id": d}
                    for i, n, r, c, d in doctors],
        "row_limit": MAX_ROWS,
    }
