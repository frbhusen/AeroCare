"""Invoices and payments.

Status machine:
    draft --issue--> issued --payments--> partially_paid --payments--> paid
    draft|issued (no active payments) --void--> void
Payments move issued/partially_paid/paid automatically (recalculate()). Recording a payment on a
draft issues it first. Only drafts are editable. Overpayment is rejected (also by a DB CHECK).
All totals are Decimal(2) and kept consistent here only.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select

from backend.app.core.api import check_version
from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import utcnow
from backend.app.extensions import db
from backend.app.models import Clinic, HealthCenter, Patient, User
from backend.app.services import centers as center_svc
from backend.app.services.clinical import get_patient, link_patient_to_clinic
from .models import Invoice, InvoiceItem, Payment, Service
from .pricing import applicable_clause, effective_price, money, visible_clause

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")
PAYABLE = ("issued", "partially_paid", "paid")


def q2(v):
    return Decimal(v).quantize(CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- loading
def get_invoice(p, invoice_id, lock=False):
    stmt = select(Invoice).where(Invoice.id == invoice_id, p.tenant(Invoice), Invoice.live(),
                                 p.clinic_clause(Invoice.clinic_id))
    if lock:
        stmt = stmt.with_for_update()
    inv = db.session.execute(stmt).scalar_one_or_none()
    if inv is None:
        raise NotFound("Invoice not found")
    return inv


def items_of(inv):
    return db.session.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id,
                                                        InvoiceItem.health_center_id == inv.health_center_id)
                              .order_by(InvoiceItem.position, InvoiceItem.id)).scalars().all()


def payments_of(inv):
    return db.session.execute(select(Payment).where(Payment.invoice_id == inv.id,
                                                    Payment.health_center_id == inv.health_center_id)
                              .order_by(Payment.seq)).scalars().all()


def _clinic(p, clinic_id):
    c = db.session.execute(select(Clinic).where(Clinic.id == clinic_id, p.tenant(Clinic), Clinic.live())
                           ).scalar_one_or_none()
    if c is None or not p.can_clinic(c.id):
        raise NotFound("Clinic not found")
    return c


def _doctor(p, user_id):
    u = db.session.execute(select(User).where(User.id == user_id, User.health_center_id == p.center_id,
                                              User.role.in_(("doctor", "department_manager", "center_manager")))
                           ).scalar_one_or_none()
    if u is None:
        raise ValidationError("Invalid input", details={"doctor_user_id": "unknown doctor"})
    return u


# ---------------------------------------------------------------- items / totals
def build_items(p, inv, clinic, items):
    """Replace the invoice's items from validated dicts. Returns the new rows."""
    for old in items_of(inv):
        db.session.delete(old)
    db.session.flush()
    services = {}
    ids = {it["service_id"] for it in items if it.get("service_id")}
    if ids:
        rows = db.session.execute(select(Service).where(Service.id.in_(ids), visible_clause(p),
                                                        applicable_clause(clinic))).scalars().all()
        services = {s.id: s for s in rows}
    out, errors = [], {}
    for i, it in enumerate(items):
        svc = None
        if it.get("service_id"):
            svc = services.get(it["service_id"])
            if svc is None:
                errors[f"items.{i}.service_id"] = "unknown service for this clinic"
                continue
        list_price = effective_price(svc, clinic)[0] if svc else None
        unit_price = it.get("unit_price")
        if unit_price is None:
            if list_price is None:
                errors[f"items.{i}.unit_price"] = "is required"
                continue
            unit_price = list_price
        description = it.get("description") or (svc.name if svc else None)
        if not description:
            errors[f"items.{i}.description"] = "is required"
            continue
        qty = it.get("qty") or Decimal("1")
        gross = q2(qty * unit_price)
        pct = it.get("discount_percent")
        if pct is not None and it.get("discount_amount"):
            errors[f"items.{i}.discount_amount"] = "give either discount_amount or discount_percent"
            continue
        disc = q2(gross * pct / 100) if pct is not None else q2(it.get("discount_amount") or ZERO)
        if disc > gross:
            errors[f"items.{i}.discount_amount"] = "exceeds the line amount"
            continue
        row = InvoiceItem(health_center_id=inv.health_center_id, invoice_id=inv.id, position=i,
                          kind=it.get("kind") or (svc.kind if svc else "service"), service_id=svc.id if svc else None,
                          description=description, qty=qty, unit_price=q2(unit_price), list_price=list_price,
                          discount_percent=pct, discount_amount=disc, line_total=gross - disc,
                          reference_type=it.get("reference_type"), reference_id=it.get("reference_id"))
        db.session.add(row)
        out.append(row)
    if errors:
        raise ValidationError("Invalid invoice items", details=errors)
    return out


def recalculate(inv, items=None):
    """Recompute subtotal/discounts/total/paid/balance and the payment-driven status."""
    items = items if items is not None else items_of(inv)
    subtotal = sum((q2(Decimal(i.qty) * Decimal(i.unit_price)) for i in items), ZERO)
    line_disc = sum((money(i.discount_amount) for i in items), ZERO)
    inv_disc = money(inv.invoice_discount or 0)
    if line_disc + inv_disc > subtotal:
        raise ValidationError("The discount exceeds the invoice amount.",
                              details={"invoice_discount": "exceeds the invoice amount"})
    paid = db.session.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.invoice_id == inv.id, Payment.health_center_id == inv.health_center_id,
        Payment.is_void.is_(False))).scalar_one() if inv.id else ZERO
    paid = money(paid)
    total = subtotal - line_disc - inv_disc
    if paid > total:
        raise ValidationError("Payments exceed the invoice total.", code="overpayment")
    inv.subtotal, inv.discount_total, inv.total = subtotal, line_disc + inv_disc, total
    inv.paid_total, inv.balance = paid, total - paid
    if inv.status in PAYABLE:
        inv.status = "issued" if paid == 0 and total > 0 else ("paid" if paid == total else "partially_paid")
    inv.updated_at = utcnow()  # forces a version bump even when amounts are unchanged


# ---------------------------------------------------------------- invoices
def create_invoice(p, data):
    clinic = _clinic(p, data["clinic_id"])
    p.require("billing.create", clinic_id=clinic.id)
    patient = get_patient(p, data["patient_id"], perm=None)
    doctor = None
    if data.get("doctor_user_id"):
        doctor = _doctor(p, data["doctor_user_id"])
    elif p.role == "doctor" and p.user.clinic_id == clinic.id:
        doctor = p.user
    center = db.session.get(HealthCenter, p.center_id)
    number = center_svc.next_sequence(p.center_id, "invoice_seq")
    inv = Invoice(health_center_id=p.center_id, number=number, patient_id=patient.id,
                  department_id=clinic.department_id, clinic_id=clinic.id,
                  doctor_user_id=doctor.id if doctor else None, doctor_name=doctor.name if doctor else None,
                  status="draft", currency=center.currency, notes=data.get("notes"),
                  invoice_discount=data.get("invoice_discount") or ZERO, subtotal=ZERO, discount_total=ZERO,
                  total=ZERO, paid_total=ZERO, balance=ZERO)
    inv.set_author(p.user)
    db.session.add(inv)
    db.session.flush()
    link_patient_to_clinic(p.center_id, patient.id, clinic.id, clinic.department_id)
    items = build_items(p, inv, clinic, data.get("items") or [])
    recalculate(inv, items)
    if data.get("issue"):
        _issue(inv, items)
    db.session.commit()
    return inv


def update_invoice(p, inv, data):
    p.require("billing.edit", clinic_id=inv.clinic_id)
    check_version(inv, data.get("version"))
    if inv.status != "draft":
        raise ValidationError("Only draft invoices can be edited.", code="invoice_not_draft")
    if "doctor_user_id" in data:
        doctor = _doctor(p, data["doctor_user_id"]) if data["doctor_user_id"] else None
        inv.doctor_user_id, inv.doctor_name = (doctor.id, doctor.name) if doctor else (None, None)
    if "notes" in data:
        inv.notes = data["notes"]
    if "invoice_discount" in data:
        inv.invoice_discount = data["invoice_discount"] or ZERO
    items = None
    if "items" in data:
        clinic = db.session.get(Clinic, inv.clinic_id)
        items = build_items(p, inv, clinic, data["items"] or [])
    recalculate(inv, items)
    db.session.commit()
    return inv


def _issue(inv, items):
    if not items:
        raise ValidationError("Add at least one item before issuing.", code="invoice_empty")
    inv.status = "issued"
    inv.issued_at = utcnow()
    recalculate(inv, items)


def issue_invoice(p, inv, version=None):
    p.require("billing.create", clinic_id=inv.clinic_id)
    if version is not None:
        check_version(inv, version)
    if inv.status != "draft":
        raise ValidationError("Only draft invoices can be issued.", code="invoice_not_draft")
    _issue(inv, items_of(inv))
    db.session.commit()
    return inv


def void_invoice(p, inv, reason=None, version=None):
    p.require("billing.edit", clinic_id=inv.clinic_id)
    if version is not None:
        check_version(inv, version)
    if inv.status == "void":
        raise ValidationError("The invoice is already void.", code="invoice_void")
    if money(inv.paid_total) > 0:
        raise ValidationError("Void the invoice's payments first.", code="invoice_has_payments")
    inv.status, inv.voided_at, inv.void_reason = "void", utcnow(), reason
    db.session.commit()
    return inv


# ---------------------------------------------------------------- payments
def add_payment(p, invoice_id, data):
    inv = get_invoice(p, invoice_id, lock=True)  # row lock serializes concurrent payments
    p.require("billing.create", clinic_id=inv.clinic_id)
    if inv.status == "void":
        raise ValidationError("Cannot pay a void invoice.", code="invoice_void")
    if inv.status == "draft":
        _issue(inv, items_of(inv))
    amount = money(data["amount"])
    if amount <= 0:
        raise ValidationError("Invalid input", details={"amount": "must be greater than 0"})
    if amount > money(inv.balance):
        raise ValidationError("The payment exceeds the remaining balance.", code="overpayment",
                              details={"amount": f"must be <= {money(inv.balance)}",
                                       "balance": str(money(inv.balance))})
    inv.payment_seq = (inv.payment_seq or 0) + 1
    pay = Payment(health_center_id=inv.health_center_id, invoice_id=inv.id, seq=inv.payment_seq, amount=amount,
                  method=data.get("method") or "cash", paid_at=data.get("paid_at") or utcnow(),
                  notes=data.get("notes"))
    pay.set_author(p.user)
    db.session.add(pay)
    db.session.flush()
    recalculate(inv)
    db.session.commit()
    return inv, pay


def get_payment(p, inv, payment_id):
    pay = db.session.execute(select(Payment).where(Payment.id == payment_id, Payment.invoice_id == inv.id,
                                                   p.tenant(Payment))).scalar_one_or_none()
    if pay is None:
        raise NotFound("Payment not found")
    return pay


def void_payment(p, invoice_id, payment_id, reason=None):
    inv = get_invoice(p, invoice_id, lock=True)
    p.require("billing.edit", clinic_id=inv.clinic_id)
    pay = get_payment(p, inv, payment_id)
    if pay.is_void:
        raise ValidationError("The payment is already void.", code="payment_void")
    pay.is_void, pay.voided_at, pay.voided_by_name, pay.void_reason = True, utcnow(), p.user.name, reason
    db.session.flush()
    recalculate(inv)
    db.session.commit()
    return inv, pay


# ---------------------------------------------------------------- lists
def invoice_filters(p, args):
    conds = [p.tenant(Invoice), Invoice.live(), p.clinic_clause(Invoice.clinic_id)]
    for key, col in (("patient_id", Invoice.patient_id), ("clinic_id", Invoice.clinic_id),
                     ("department_id", Invoice.department_id), ("doctor_user_id", Invoice.doctor_user_id)):
        if args.get(key):
            conds.append(col == args[key])
    if args.get("status"):
        conds.append(Invoice.status.in_(args["status"]))
    when = func.coalesce(Invoice.issued_at, Invoice.created_at)
    if args.get("date_from"):
        conds.append(when >= args["date_from"])
    if args.get("date_to"):
        conds.append(when < args["date_to"])
    if args.get("q"):
        q = args["q"].strip()
        digits = "".join(ch for ch in q if ch.isdigit())
        opts = [Invoice.patient_id.in_(select(Patient.id).where(
            Patient.health_center_id == p.center_id,
            Patient.full_name.ilike("%" + q.replace("%", r"\%").replace("_", r"\_") + "%")))]
        if digits and len(digits) <= 9:
            opts.append(Invoice.number == int(digits))
        conds.append(or_(*opts))
    return conds


def list_invoices(p, args, page, per_page):
    conds = invoice_filters(p, args)
    stmt = select(Invoice).where(*conds).order_by(Invoice.created_at.desc(), Invoice.id.desc())
    rows = db.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).scalars().all()
    total = db.session.execute(select(func.count()).select_from(Invoice).where(*conds)).scalar_one()
    totals = db.session.execute(select(func.coalesce(func.sum(Invoice.total), 0),
                                       func.coalesce(func.sum(Invoice.paid_total), 0),
                                       func.coalesce(func.sum(Invoice.balance), 0))
                                .where(*conds, Invoice.status.notin_(("draft", "void")))).one()
    return rows, total, {"total": str(money(totals[0])), "paid": str(money(totals[1])),
                         "balance": str(money(totals[2]))}


def patient_history(p, patient_id):
    p.require("billing.view")
    patient = get_patient(p, patient_id, perm=None)
    invoices = db.session.execute(select(Invoice).where(
        p.tenant(Invoice), Invoice.live(), p.clinic_clause(Invoice.clinic_id), Invoice.patient_id == patient.id)
        .order_by(Invoice.created_at.desc())).scalars().all()
    ids = [i.id for i in invoices]
    payments = db.session.execute(select(Payment).where(p.tenant(Payment), Payment.invoice_id.in_(ids or [-1]))
                                  .order_by(Payment.paid_at.desc())).scalars().all() if ids else []
    billed = [i for i in invoices if i.status not in ("draft", "void")]
    totals = {"billed": str(sum((money(i.total) for i in billed), ZERO)),
              "paid": str(sum((money(i.paid_total) for i in billed), ZERO)),
              "outstanding": str(sum((money(i.balance) for i in billed), ZERO)),
              "discounts": str(sum((money(i.discount_total) for i in billed), ZERO)),
              "invoice_count": len(billed)}
    return patient, invoices, payments, totals
