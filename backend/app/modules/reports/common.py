"""Shared report plumbing: filter parsing + scope validation, column definitions, labels,
SQL helpers and the uniform report envelope.

Every report function receives (p, f: Filters) and returns a dict with `columns`, `rows` and
optionally `totals` / `meta`. Scope is enforced inside each query with the principal's tenant
filter + clinic/department clauses; filters may only NARROW the principal's scope (an
out-of-scope department/clinic/doctor filter is a 404, never a widening).
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import local_day_bounds, local_today
from backend.app.core.validation import Date, Id, Int, Str, validate
from backend.app.extensions import db

MAX_ROWS = 1000          # hard bound on rows returned / exported per report
MAX_SPAN_DAYS = 1830     # ~5 years
DEFAULT_SPAN_DAYS = 30
LOCAL_TZ = "Asia/Damascus"

# column / title labels: key -> (en, ar)
LABELS = {
    # groups
    "group": ("Group", "المجموعة"), "clinic": ("Clinic", "العيادة"), "department": ("Department", "القسم"),
    "doctor": ("Doctor", "الطبيب"), "day": ("Day", "اليوم"), "month": ("Month", "الشهر"),
    "gender": ("Gender", "الجنس"), "status": ("Status", "الحالة"), "none": ("All", "الكل"),
    "service": ("Service", "الخدمة"), "kind": ("Type", "النوع"), "procedure": ("Procedure", "الإجراء"),
    "test": ("Test", "التحليل"), "exam_type": ("Exam type", "نوع الفحص"), "patient": ("Patient", "المريض"),
    "item": ("Item", "المادة"), "location": ("Location", "الموقع"), "cashier": ("Cashier", "أمين الصندوق"),
    "payment_count": ("Payments", "الدفعات"), "payments_cash": ("Payments cash", "نقد الدفعات"),
    "sale_count": ("Pharmacy sales", "مبيعات الصيدلية"), "sales_cash": ("Sales cash", "نقد المبيعات"),
    "total_cash": ("Total cash", "إجمالي النقد"), "voided_count": ("Voided payments", "دفعات ملغاة"),
    # metrics
    "new_patients": ("New patients", "مرضى جدد"), "total": ("Total", "الإجمالي"),
    "scheduled": ("Scheduled", "مجدول"), "arrived": ("Arrived", "حضر"), "in_progress": ("In progress", "قيد التنفيذ"),
    "completed": ("Completed", "مكتمل"), "cancelled": ("Cancelled", "ملغى"), "no_show": ("No-show", "لم يحضر"),
    "no_show_rate": ("No-show rate %", "نسبة عدم الحضور %"), "requested": ("Requested", "مطلوب"),
    "reported": ("Reported", "تم التقرير"), "finalized": ("Finalized", "نهائي"), "urgent": ("Urgent", "عاجل"),
    "planned": ("Planned", "مخطط"), "role": ("Role", "الدور"),
    "appointments": ("Appointments", "المواعيد"), "completed_appointments": ("Completed appointments", "مواعيد مكتملة"),
    "no_shows": ("No-shows", "حالات عدم الحضور"), "visits": ("Visits", "الزيارات"),
    "patients_seen": ("Patients seen", "مرضى تمت معاينتهم"), "completed_treatments": ("Completed treatments",
                                                                                       "معالجات مكتملة"),
    "prescriptions": ("Prescriptions", "الوصفات"), "lab_requests": ("Lab requests", "طلبات المخبر"),
    "radiology_requests": ("Radiology requests", "طلبات الأشعة"), "new_patient_links": ("New patients", "مرضى جدد"),
    "revenue": ("Revenue", "الإيرادات"), "payments_received": ("Payments received", "المدفوعات المستلمة"),
    "invoice_count": ("Invoices", "الفواتير"), "subtotal": ("Subtotal", "المجموع الفرعي"),
    "discounts": ("Discounts", "الخصومات"), "payment_count": ("Payments", "الدفعات"),
    "outstanding_in_period": ("Outstanding (period)", "المتبقي (الفترة)"),
    "open_invoice_count": ("Open invoices", "فواتير مفتوحة"), "outstanding_total": ("Outstanding (now)",
                                                                                   "المتبقي (حالياً)"),
    "patient_code": ("Code", "الرمز"), "balance": ("Balance", "الرصيد"), "oldest_issued": ("Oldest invoice",
                                                                                            "أقدم فاتورة"),
    "lines": ("Lines", "البنود"), "quantity": ("Quantity", "الكمية"), "gross": ("Gross", "الإجمالي قبل الخصم"),
    "net": ("Net", "الصافي"), "fees_completed": ("Fees (completed)", "الأجور (المكتملة)"),
    "test_code": ("Code", "الرمز"), "ordered": ("Ordered", "مطلوبة"), "resulted": ("Resulted", "بنتائج"),
    "abnormal": ("Abnormal", "غير طبيعي"), "abnormal_rate": ("Abnormal %", "غير طبيعي %"),
    "avg_turnaround_hours": ("Avg turnaround (h)", "متوسط زمن الإنجاز (ساعة)"),
    "category": ("Category", "الفئة"), "unit": ("Unit", "الوحدة"), "usable_quantity": ("Usable", "صالح"),
    "expired_quantity": ("Expired", "منتهي الصلاحية"), "nearest_expiry": ("Nearest expiry", "أقرب انتهاء"),
    "low": ("Low stock", "مخزون منخفض"), "threshold": ("Threshold", "الحد الأدنى"),
    "lot_code": ("Lot", "الدفعة"), "expiry_date": ("Expiry", "تاريخ الانتهاء"), "days_left": ("Days left",
                                                                                              "الأيام المتبقية"),
    "received": ("Received", "مستلم"), "used": ("Used", "مستخدم"), "dispensed": ("Dispensed", "مصروف"),
    "sold": ("Sold", "مباع"), "transferred_in": ("Transferred in", "منقول إليه"),
    "transferred_out": ("Transferred out", "منقول منه"), "adjusted": ("Adjusted", "تعديل"),
    "written_off": ("Written off", "إتلاف"), "net_change": ("Net change", "صافي التغير"),
    "movements": ("Movements", "الحركات"),
}


def label(key, lang="en"):
    en, ar = LABELS.get(key, (key.replace("_", " ").capitalize(), None))
    return (ar or en) if lang == "ar" else en


def col(key, type_="int", label_key=None):
    """Column definition. type: text | int | number | money | percent | date | bool."""
    lk = label_key or key
    return {"key": key, "label": label(lk), "label_ar": label(lk, "ar"), "type": type_}


def group_col(group_by):
    return col("group", "text", label_key=group_by if group_by in LABELS else "group")


@dataclass
class Filters:
    date_from: date
    date_to: date
    start: object  # UTC datetime, inclusive
    end: object    # UTC datetime, exclusive
    department_id: int | None = None
    clinic_id: int | None = None
    doctor_id: int | None = None
    group_by: str | None = None
    view: str | None = None
    location_id: int | None = None
    days: int | None = None
    labels: dict = field(default_factory=dict)  # human names of applied filters

    def to_json(self):
        out = {"date_from": self.date_from.isoformat(), "date_to": self.date_to.isoformat()}
        for k in ("department_id", "clinic_id", "doctor_id", "group_by", "view", "location_id", "days"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out


QUERY_SCHEMA = {"date_from": Date(), "date_to": Date(), "department_id": Id(), "clinic_id": Id(), "doctor_id": Id(),
                "group_by": Str(max_len=30), "view": Str(max_len=30), "location_id": Id(),
                "days": Int(min_value=0, max_value=3650)}


def parse_filters(p, spec, args):
    """Validate query args against a report spec and the principal's scope."""
    d = validate({k: v for k, v in args.items() if k in QUERY_SCHEMA}, QUERY_SCHEMA)
    allowed = set(spec["filters"])
    today = local_today()
    date_to = d.get("date_to") or today
    date_from = d.get("date_from") or (date_to - timedelta(days=DEFAULT_SPAN_DAYS - 1))
    if date_from > date_to:
        raise ValidationError("Invalid input", details={"date_from": "must be on or before date_to"})
    if (date_to - date_from).days > MAX_SPAN_DAYS:
        raise ValidationError("Invalid input", details={"date_to": f"range may not exceed {MAX_SPAN_DAYS} days"})
    f = Filters(date_from=date_from, date_to=date_to, start=local_day_bounds(date_from)[0],
                end=local_day_bounds(date_to)[1])

    groups = spec.get("groups") or []
    if groups:
        g = d.get("group_by") or spec["default_group"]
        if g not in groups:
            raise ValidationError("Invalid input", details={"group_by": "must be one of: " + ", ".join(groups)})
        f.group_by = g
    views = spec.get("views") or []
    if views:
        v = d.get("view") or views[0]
        if v not in views:
            raise ValidationError("Invalid input", details={"view": "must be one of: " + ", ".join(views)})
        f.view = v
    if "days" in allowed:
        f.days = 30 if d.get("days") is None else d["days"]

    from backend.app.models import Clinic, Department, User
    if "department_id" in allowed and d.get("department_id"):
        dep = d["department_id"]
        if not p.sees_department(dep):
            raise NotFound("Department not found")
        f.department_id = dep
        f.labels["department"] = db.session.execute(select(Department.name).where(
            Department.id == dep, p.tenant(Department))).scalar_one_or_none()
    if "clinic_id" in allowed and d.get("clinic_id"):
        cid = d["clinic_id"]
        if not p.can_clinic(cid):
            raise NotFound("Clinic not found")
        if f.department_id and p.clinic_department.get(cid) != f.department_id:
            raise ValidationError("Invalid input", details={"clinic_id": "does not belong to department_id"})
        f.clinic_id = cid
        f.labels["clinic"] = db.session.execute(select(Clinic.name).where(
            Clinic.id == cid, p.tenant(Clinic))).scalar_one_or_none()
    if "doctor_id" in allowed and d.get("doctor_id"):
        u = db.session.execute(select(User).where(User.id == d["doctor_id"], User.health_center_id == p.center_id)
                               ).scalar_one_or_none()
        if u is None or not (p.center_wide or p.can_clinic(u.clinic_id) or p.sees_department(u.department_id)):
            raise NotFound("Doctor not found")
        f.doctor_id = u.id
        f.labels["doctor"] = u.name
    if "location_id" in allowed and d.get("location_id"):
        f.location_id = d["location_id"]  # validated by the inventory report (visible locations only)
    return f


# ---- SQL helpers ---------------------------------------------------------------
def local_day(col_, is_date=False):
    src = col_ if is_date else func.timezone(LOCAL_TZ, col_)
    return func.to_char(src, "YYYY-MM-DD")


def local_month(col_, is_date=False):
    src = col_ if is_date else func.timezone(LOCAL_TZ, col_)
    return func.to_char(src, "YYYY-MM")


def bounded(stmt):
    """Execute with MAX_ROWS + 1 to detect truncation. Returns (rows, truncated)."""
    rows = db.session.execute(stmt.limit(MAX_ROWS + 1)).all()
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


def names(p, kind, ids):
    """id -> name for clinics / departments / users of the principal's center."""
    ids = [i for i in set(ids) if i is not None]
    if not ids:
        return {}
    from backend.app.models import Clinic, Department, User
    model = {"clinic": Clinic, "department": Department, "doctor": User}[kind]
    return dict(db.session.execute(select(model.id, model.name).where(
        model.id.in_(ids), model.health_center_id == p.center_id)).all())


def user_roles(p, ids):
    ids = [i for i in set(ids) if i is not None]
    if not ids:
        return {}
    from backend.app.models import User
    return dict(db.session.execute(select(User.id, User.role).where(
        User.id.in_(ids), User.health_center_id == p.center_id)).all())


def money_str(v):
    return str(Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def num_str(v, places="0.01"):
    if v is None:
        return None
    return str(Decimal(v).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def qty_str(v):
    if v is None:
        return None
    d = Decimal(v).normalize()
    return format(d if d != 0 else Decimal(0), "f")


def rate(part, whole):
    if not whole:
        return None
    return num_str(Decimal(part) * 100 / Decimal(whole), "0.1")


def hours(seconds):
    return None if seconds is None else num_str(Decimal(seconds) / Decimal(3600), "0.1")


def group_label(p, group_by, keys):
    """Resolve display names for grouped keys (clinic/department/doctor ids); other groups use the key."""
    if group_by in ("clinic", "department", "doctor"):
        nm = names(p, group_by, keys)
        return lambda k: nm.get(k) if k is not None else "Unassigned"
    return lambda k: k if k is not None else "Unassigned"


def sum_totals(columns, rows, skip=("group",)):
    """Totals row: sums of int/money/number columns (rates/averages are left blank)."""
    out = {}
    for c in columns:
        k = c["key"]
        if k in skip:
            continue
        if c["type"] == "int":
            out[k] = sum(int(r.get(k) or 0) for r in rows)
        elif c["type"] == "money":
            out[k] = money_str(sum((Decimal(r.get(k) or 0) for r in rows), Decimal(0)))
        elif c["type"] == "number":
            out[k] = qty_str(sum((Decimal(r.get(k) or 0) for r in rows), Decimal(0)))
    return out
