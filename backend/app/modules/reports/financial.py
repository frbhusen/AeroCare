"""Revenue / payments / outstanding balances and billed services. All require billing.view
(checked by the registry) and are restricted to invoices in the principal's clinic scope."""
from sqlalchemy import and_, func, select

from backend.app.core.timeutil import to_local
from backend.app.extensions import db
from backend.app.models import HealthCenter, Patient
from backend.app.modules.billing.models import Invoice, InvoiceItem, Service
from backend.app.modules.billing.summary import summary
from .common import bounded, col, group_col, money_str, qty_str, sum_totals

_BILLED = ("issued", "partially_paid", "paid")
REVENUE_KEYS = ("invoice_count", "subtotal", "discounts", "revenue", "payment_count", "payments_received",
                "outstanding_in_period", "open_invoice_count", "outstanding_total")


def _currency_meta(res):
    return {"currency": res.get("currency")}


def revenue(p, f):
    """Reuses billing.summary (revenue = invoices issued in range, payments by paid_at,
    outstanding_total = all open invoices now)."""
    g = f.group_by
    args = {"group_by": g, "department_id": f.department_id, "clinic_id": f.clinic_id,
            "doctor_user_id": f.doctor_id}
    res = summary(p, args, f.start, f.end)
    columns = [group_col(g)] + [col(k, "int" if k.endswith("count") else "money") for k in REVENUE_KEYS]
    if g == "none":
        rows = [{"key": None, "group": "All", **{k: res["totals"][k] for k in REVENUE_KEYS}}]
        totals = None
    else:
        rows = [{"key": r["key"], "group": r["name"] or ("Unassigned" if r["key"] is None else f"#{r['key']}"),
                 **{k: r[k] for k in REVENUE_KEYS}} for r in res["rows"]]
        totals = {k: res["totals"][k] for k in REVENUE_KEYS}
    return {"columns": columns, "rows": rows, "totals": totals, "truncated": False, "meta": _currency_meta(res),
            "notes": ["Revenue = issued invoices in the period (after discounts). Payments by payment date. "
                      "Outstanding (now) = all open invoice balances, regardless of the period."]}


def _scope(p, f):
    return [p.tenant(Invoice), Invoice.live(), p.clinic_clause(Invoice.clinic_id),
            *([Invoice.department_id == f.department_id] if f.department_id else []),
            *([Invoice.clinic_id == f.clinic_id] if f.clinic_id else []),
            *([Invoice.doctor_user_id == f.doctor_id] if f.doctor_id else [])]


def outstanding(p, f):
    """Open balances as of now, per patient (largest first). The date range is not applied."""
    bal = func.sum(Invoice.balance)
    stmt = (select(Invoice.patient_id, Patient.code, Patient.full_name, func.count(Invoice.id), bal,
                   func.min(Invoice.issued_at))
            .join(Patient, and_(Patient.id == Invoice.patient_id,
                                Patient.health_center_id == Invoice.health_center_id))
            .where(*_scope(p, f), Invoice.status.in_(("issued", "partially_paid")), Invoice.balance > 0)
            .group_by(Invoice.patient_id, Patient.code, Patient.full_name)
            .order_by(bal.desc(), Invoice.patient_id))
    data, truncated = bounded(stmt)
    rows = [{"key": pid, "patient_code": f"PAT-{code:06d}", "group": name, "open_invoice_count": n,
             "balance": money_str(b), "oldest_issued": to_local(oldest).date().isoformat() if oldest else None}
            for pid, code, name, n, b, oldest in data]
    columns = [col("patient_code", "text"), col("group", "text", "patient"), col("open_invoice_count"),
               col("balance", "money"), col("oldest_issued", "date")]
    tot = db.session.execute(select(func.count(func.distinct(Invoice.patient_id)), func.count(Invoice.id),
                                    func.coalesce(bal, 0))
                             .where(*_scope(p, f), Invoice.status.in_(("issued", "partially_paid")),
                                    Invoice.balance > 0)).one()
    center = db.session.get(HealthCenter, p.center_id)
    return {"columns": columns, "rows": rows,
            "totals": {"open_invoice_count": tot[1], "balance": money_str(tot[2])}, "truncated": truncated,
            "meta": {"currency": center.currency if center else None, "patients": tot[0]},
            "notes": ["Current open balances (issued / partially paid invoices); the date range does not apply."]}


def services(p, f):
    """Billed lines of issued invoices in range, by service (or free-text description) or by kind."""
    g = f.group_by
    label_expr = func.coalesce(Service.name, InvoiceItem.description)
    gross = func.sum(InvoiceItem.line_total + InvoiceItem.discount_amount)
    metrics = [func.count(InvoiceItem.id), func.coalesce(func.sum(InvoiceItem.qty), 0), func.coalesce(gross, 0),
               func.coalesce(func.sum(InvoiceItem.discount_amount), 0),
               func.coalesce(func.sum(InvoiceItem.line_total), 0)]
    frm = (select().select_from(InvoiceItem)
           .join(Invoice, and_(Invoice.id == InvoiceItem.invoice_id,
                               Invoice.health_center_id == InvoiceItem.health_center_id))
           .outerjoin(Service, and_(Service.id == InvoiceItem.service_id,
                                    Service.health_center_id == InvoiceItem.health_center_id)))
    conds = [*_scope(p, f), Invoice.status.in_(_BILLED), Invoice.issued_at >= f.start, Invoice.issued_at < f.end]
    if g == "service":
        stmt = frm.add_columns(InvoiceItem.service_id, label_expr, *metrics).where(*conds).group_by(
            InvoiceItem.service_id, label_expr)
        off = 2
    else:
        stmt = frm.add_columns(InvoiceItem.kind, InvoiceItem.kind, *metrics).where(*conds).group_by(InvoiceItem.kind)
        off = 2
    data, truncated = bounded(stmt.order_by(func.sum(InvoiceItem.line_total).desc()))
    rows = []
    for r in data:
        rows.append({"key": r[0], "group": r[1], "lines": r[off], "quantity": qty_str(r[off + 1]),
                     "gross": money_str(r[off + 2]), "discounts": money_str(r[off + 3]), "net": money_str(r[off + 4])})
    columns = [group_col(g), col("lines"), col("quantity", "number"), col("gross", "money"),
               col("discounts", "money"), col("net", "money")]
    return {"columns": columns, "rows": rows, "totals": sum_totals(columns, rows), "truncated": truncated,
            "notes": ["Line-level amounts of issued invoices in the period; invoice-level discounts are not "
                      "allocated to lines (see the revenue report for net revenue)."]}


def cash_close(p, f):
    """Daily cash close: cash taken per cashier (or per day) in the period.
    Billing payments (non-void, by paid_at) + pharmacy cash sales that did not create an invoice
    (their payment is already counted through the invoice). Scoped to clinics the principal sees."""
    from sqlalchemy import case, literal
    from backend.app.modules.billing.models import Payment
    from backend.app.modules.pharmacy.models import Sale
    from .common import local_day
    by_day = f.group_by == "day"
    pay_key = local_day(Payment.paid_at) if by_day else Payment.author_user_id
    pay_name = literal(None) if by_day else func.max(Payment.author_name)
    pay = (select(pay_key.label("k"), pay_name.label("n"),
                  func.count(Payment.id).filter(Payment.is_void.is_(False)),
                  func.coalesce(func.sum(Payment.amount).filter(Payment.is_void.is_(False)), 0),
                  func.count(Payment.id).filter(Payment.is_void.is_(True)))
           .join(Invoice, and_(Invoice.id == Payment.invoice_id, Invoice.health_center_id == Payment.health_center_id))
           .where(p.tenant(Payment), *_scope(p, f), Payment.paid_at >= f.start, Payment.paid_at < f.end)
           .group_by(pay_key))
    sale_cash = case((Sale.paid_amount < Sale.total, Sale.paid_amount), else_=Sale.total)
    sale_key = local_day(Sale.created_at) if by_day else Sale.author_user_id
    sale_name = literal(None) if by_day else func.max(Sale.author_name)
    sales_scope = [p.tenant(Sale), p.clinic_clause(Sale.clinic_id), Sale.invoice_id.is_(None),
                   Sale.created_at >= f.start, Sale.created_at < f.end,
                   *([Sale.clinic_id == f.clinic_id] if f.clinic_id else [])]
    if f.department_id:
        from backend.app.models import Clinic
        sales_scope.append(Sale.clinic_id.in_(select(Clinic.id).where(Clinic.department_id == f.department_id)))
    sales = (select(sale_key.label("k"), sale_name.label("n"), func.count(Sale.id), func.coalesce(func.sum(sale_cash), 0))
             .where(*sales_scope).group_by(sale_key))
    rows = {}
    for k, n, cnt, amt, voided in db.session.execute(pay).all():
        r = rows.setdefault(k, {"key": k, "group": n, "payment_count": 0, "payments_cash": 0, "sale_count": 0,
                                "sales_cash": 0, "voided_count": 0})
        r.update(payment_count=cnt, payments_cash=amt, voided_count=voided)
        r["group"] = r["group"] or n
    if not f.doctor_id:  # sales have no doctor; a doctor filter means "invoices of that doctor"
        for k, n, cnt, amt in db.session.execute(sales).all():
            r = rows.setdefault(k, {"key": k, "group": n, "payment_count": 0, "payments_cash": 0, "sale_count": 0,
                                    "sales_cash": 0, "voided_count": 0})
            r.update(sale_count=cnt, sales_cash=amt)
            r["group"] = r["group"] or n
    out = []
    for r in sorted(rows.values(), key=lambda x: (str(x["key"]) if by_day else (x["group"] or ""))):
        total = r["payments_cash"] + r["sales_cash"]
        out.append({**r, "group": (r["key"] if by_day else r["group"] or "—"),
                    "payments_cash": money_str(r["payments_cash"]), "sales_cash": money_str(r["sales_cash"]),
                    "total_cash": money_str(total)})
    columns = [col("group", "text", "day" if by_day else "cashier"), col("payment_count"), col("payments_cash", "money"),
               col("sale_count"), col("sales_cash", "money"), col("total_cash", "money"), col("voided_count")]
    center = db.session.get(HealthCenter, p.center_id)
    return {"columns": columns, "rows": out, "totals": sum_totals(columns, out), "truncated": False,
            "meta": {"currency": center.currency if center else None},
            "notes": ["Cash received in the period: invoice payments (voided payments excluded, counted separately) "
                      "plus pharmacy cash sales without an invoice. Compare with the cash in the drawer."]}
