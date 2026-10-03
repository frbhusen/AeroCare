"""Financial summary totals (revenue, payments received, outstanding) by center / department /
clinic / doctor in a date range, always within the principal's clinic scope (spec §51, §61)."""
from sqlalchemy import func, select

from backend.app.extensions import db
from backend.app.models import Clinic, Department
from .models import Invoice, Payment
from .pricing import money

GROUPS = ("none", "department", "clinic", "doctor")
_BILLED = ("issued", "partially_paid", "paid")


def _scope(p, args):
    conds = [p.tenant(Invoice), Invoice.live(), p.clinic_clause(Invoice.clinic_id)]
    for key, col in (("clinic_id", Invoice.clinic_id), ("department_id", Invoice.department_id),
                     ("doctor_user_id", Invoice.doctor_user_id)):
        if args.get(key):
            conds.append(col == args[key])
    return conds


def _group_col(group):
    return {"department": Invoice.department_id, "clinic": Invoice.clinic_id,
            "doctor": Invoice.doctor_user_id}.get(group)


def summary(p, args, start=None, end=None):
    """start/end: UTC datetimes [start, end) or None (open)."""
    p.require("billing.view")
    group = args.get("group_by") or "none"
    gcol = _group_col(group)
    scope = _scope(p, args)

    inv_conds = scope + [Invoice.status.in_(_BILLED)]
    if start is not None:
        inv_conds.append(Invoice.issued_at >= start)
    if end is not None:
        inv_conds.append(Invoice.issued_at < end)
    inv_cols = [func.count(Invoice.id), func.coalesce(func.sum(Invoice.subtotal), 0),
                func.coalesce(func.sum(Invoice.discount_total), 0), func.coalesce(func.sum(Invoice.total), 0),
                func.coalesce(func.sum(Invoice.balance), 0)]

    pay_conds = scope + [Payment.is_void.is_(False), Invoice.status != "void"]
    pay_from = Payment.__table__.join(Invoice.__table__, (Payment.invoice_id == Invoice.id)
                                      & (Payment.health_center_id == Invoice.health_center_id))
    if start is not None:
        pay_conds.append(Payment.paid_at >= start)
    if end is not None:
        pay_conds.append(Payment.paid_at < end)
    pay_cols = [func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0)]

    out_conds = scope + [Invoice.status.in_(("issued", "partially_paid"))]
    out_cols = [func.count(Invoice.id), func.coalesce(func.sum(Invoice.balance), 0)]

    def run(cols, conds, frm):
        stmt = select(*([gcol] if gcol is not None else []), *cols).select_from(frm).where(*conds)
        if gcol is not None:
            stmt = stmt.group_by(gcol)
        return db.session.execute(stmt).all()

    inv_rows = run(inv_cols, inv_conds, Invoice)
    pay_rows = run(pay_cols, pay_conds, pay_from)
    out_rows = run(out_cols, out_conds, Invoice)

    def blank():
        return {"invoice_count": 0, "subtotal": "0.00", "discounts": "0.00", "revenue": "0.00",
                "outstanding_in_period": "0.00", "payment_count": 0, "payments_received": "0.00",
                "open_invoice_count": 0, "outstanding_total": "0.00"}

    buckets = {}

    def bucket(key):
        return buckets.setdefault(key, blank())

    off = 1 if gcol is not None else 0
    for r in inv_rows:
        b = bucket(r[0] if off else None)
        b["invoice_count"] = r[off]
        b["subtotal"], b["discounts"], b["revenue"], b["outstanding_in_period"] = (
            str(money(r[off + 1])), str(money(r[off + 2])), str(money(r[off + 3])), str(money(r[off + 4])))
    for r in pay_rows:
        b = bucket(r[0] if off else None)
        b["payment_count"], b["payments_received"] = r[off], str(money(r[off + 1]))
    for r in out_rows:
        b = bucket(r[0] if off else None)
        b["open_invoice_count"], b["outstanding_total"] = r[off], str(money(r[off + 1]))

    currency = _currency(p)
    if gcol is None:
        return {"group_by": "none", "currency": currency, "totals": buckets.get(None, blank())}
    names = _names(p, group, [k for k in buckets if k is not None])
    rows = [{"key": k, "name": names.get(k) if k is not None else None, **v}
            for k, v in sorted(buckets.items(), key=lambda kv: (kv[0] is None, names.get(kv[0]) or ""))]
    totals = blank()
    for f in totals:
        if f.endswith("count"):
            totals[f] = sum(r[f] for r in rows)
        else:
            totals[f] = str(sum((money(r[f]) for r in rows), money(0)))
    return {"group_by": group, "currency": currency, "rows": rows, "totals": totals}


def _currency(p):
    from backend.app.models import HealthCenter
    c = db.session.get(HealthCenter, p.center_id)
    return c.currency if c else None


def _names(p, group, keys):
    if not keys:
        return {}
    from backend.app.models import User
    model = {"department": Department, "clinic": Clinic, "doctor": User}[group]
    rows = db.session.execute(select(model.id, model.name).where(model.id.in_(keys),
                                                                 model.health_center_id == p.center_id)).all()
    return {i: n for i, n in rows}
