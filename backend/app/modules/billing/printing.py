"""Serialization and printable documents (invoice / receipt PDFs) for billing."""
from sqlalchemy import select

from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import iso
from backend.app.extensions import db
from backend.app.models import Clinic, Department, Patient
from backend.app.services import documents
from backend.app.services.pdf import format_dt, format_money
from .pricing import m
from .service import items_of, payments_of

L = {
    "invoice": ("Invoice", "فاتورة"), "receipt": ("Payment receipt", "إيصال دفع"),
    "patient": ("Patient", "المريض"), "patient_code": ("Patient code", "رمز المريض"),
    "number": ("Invoice no.", "رقم الفاتورة"), "date": ("Date", "التاريخ"), "status": ("Status", "الحالة"),
    "clinic": ("Clinic", "العيادة"), "department": ("Department", "القسم"), "doctor": ("Doctor", "الطبيب"),
    "items": ("Items", "البنود"), "description": ("Description", "الوصف"), "qty": ("Qty", "الكمية"),
    "unit_price": ("Unit price", "سعر الوحدة"), "discount": ("Discount", "الخصم"), "amount": ("Amount", "المبلغ"),
    "subtotal": ("Subtotal", "المجموع الفرعي"), "invoice_discount": ("Invoice discount", "خصم الفاتورة"),
    "discount_total": ("Total discounts", "إجمالي الخصومات"), "total": ("Total", "الإجمالي"),
    "paid": ("Paid", "المدفوع"), "balance": ("Remaining", "المتبقي"), "payments": ("Payments", "الدفعات"),
    "receipt_no": ("Receipt no.", "رقم الإيصال"), "method": ("Method", "طريقة الدفع"),
    "received_by": ("Received by", "استلمها"), "notes": ("Notes", "ملاحظات"), "cash": ("Cash", "نقداً"),
    "amount_paid": ("Amount paid", "المبلغ المدفوع"), "for_invoice": ("For invoice", "عن الفاتورة"),
    "signature": ("Signature", "التوقيع"), "void": ("VOID", "ملغاة"), "draft": ("DRAFT", "مسودة"),
    "issued": ("Issued", "صادرة"), "partially_paid": ("Partially paid", "مدفوعة جزئياً"),
    "paid_status": ("Paid", "مدفوعة"), "voided_payment": ("(void)", "(ملغاة)"),
}


def lbl(key, lang):
    en, ar = L[key]
    return ar if lang == "ar" else en


def status_label(status, lang):
    return lbl({"paid": "paid_status"}.get(status, status), lang)


def receipt_number(inv, pay):
    return f"{inv.display_number}-{pay.seq}"


# ---------------------------------------------------------------- JSON
def _lookup(inv):
    patient = db.session.get(Patient, inv.patient_id)
    clinic = db.session.get(Clinic, inv.clinic_id)
    dept = db.session.get(Department, inv.department_id)
    return patient, clinic, dept


def serialize_item(i):
    return {"id": i.id, "position": i.position, "kind": i.kind, "service_id": i.service_id,
            "description": i.description, "qty": str(i.qty), "unit_price": m(i.unit_price),
            "list_price": m(i.list_price), "discount_percent": None if i.discount_percent is None else str(
                i.discount_percent), "discount_amount": m(i.discount_amount), "line_total": m(i.line_total),
            "reference_type": i.reference_type, "reference_id": i.reference_id}


def serialize_payment(pay, inv=None):
    return {"id": pay.id, "invoice_id": pay.invoice_id, "seq": pay.seq,
            "receipt_number": receipt_number(inv, pay) if inv else None, "amount": m(pay.amount),
            "method": pay.method, "paid_at": iso(pay.paid_at), "notes": pay.notes, "received_by": pay.author_name,
            "received_by_user_id": pay.author_user_id, "is_void": pay.is_void, "voided_at": iso(pay.voided_at),
            "voided_by": pay.voided_by_name, "void_reason": pay.void_reason}


def serialize_invoice(inv, brief=False, names=None):
    out = {"id": inv.id, "number": inv.display_number, "number_int": inv.number, "patient_id": inv.patient_id,
           "department_id": inv.department_id, "clinic_id": inv.clinic_id, "doctor_user_id": inv.doctor_user_id,
           "doctor_name": inv.doctor_name, "status": inv.status, "subtotal": m(inv.subtotal),
           "invoice_discount": m(inv.invoice_discount), "discount_total": m(inv.discount_total),
           "total": m(inv.total), "paid_total": m(inv.paid_total), "balance": m(inv.balance),
           "currency": inv.currency, "issued_at": iso(inv.issued_at), "created_at": iso(inv.created_at),
           "created_by": inv.author_name, "version": inv.version}
    if names is not None:
        out.update(names.get(inv.id, {}))
    if brief:
        return out
    patient, clinic, dept = _lookup(inv)
    out.update({
        "patient_name": patient.full_name if patient else None,
        "patient_code": patient.display_code if patient else None,
        "clinic_name": clinic.name if clinic else None, "department_name": dept.name if dept else None,
        "notes": inv.notes, "voided_at": iso(inv.voided_at), "void_reason": inv.void_reason,
        "items": [serialize_item(i) for i in items_of(inv)],
        "payments": [serialize_payment(pay, inv) for pay in payments_of(inv)],
    })
    return out


def list_names(invoices):
    """Patient / clinic names for a page of invoices in 2 queries."""
    pids = {i.patient_id for i in invoices}
    cids = {i.clinic_id for i in invoices}
    pats = {r.id: r for r in db.session.execute(select(Patient).where(Patient.id.in_(pids or [-1]))).scalars()}
    clin = dict(db.session.execute(select(Clinic.id, Clinic.name).where(Clinic.id.in_(cids or [-1]))).all())
    out = {}
    for i in invoices:
        pt = pats.get(i.patient_id)
        out[i.id] = {"patient_name": pt.full_name if pt else None,
                     "patient_code": pt.display_code if pt else None, "clinic_name": clin.get(i.clinic_id)}
    return out


# ---------------------------------------------------------------- PDF
def _header_kv(inv, patient, clinic, dept, lang):
    kv = [[lbl("number", lang), inv.display_number],
          [lbl("date", lang), format_dt(inv.issued_at or inv.created_at)],
          [lbl("patient", lang), patient.full_name if patient else ""],
          [lbl("patient_code", lang), patient.display_code if patient else ""],
          [lbl("department", lang), dept.name if dept else ""], [lbl("clinic", lang), clinic.name if clinic else ""]]
    if inv.doctor_name:
        kv.append([lbl("doctor", lang), inv.doctor_name])
    kv.append([lbl("status", lang), status_label(inv.status, lang)])
    return kv


def invoice_pdf(inv, lang="en"):
    patient, clinic, dept = _lookup(inv)
    cur = inv.currency
    rows = []
    for i in items_of(inv):
        disc = ""
        if i.discount_amount and i.discount_amount > 0:
            disc = format_money(i.discount_amount)
            if i.discount_percent is not None:
                disc += f" ({i.discount_percent.normalize():f}%)"
        rows.append([i.description, f"{i.qty.normalize():f}", format_money(i.unit_price), disc,
                     format_money(i.line_total)])
    totals = [[lbl("subtotal", lang), format_money(inv.subtotal, cur)]]
    if inv.discount_total and inv.discount_total > 0:
        totals.append([lbl("discount_total", lang), format_money(inv.discount_total, cur)])
    totals += [[lbl("total", lang), format_money(inv.total, cur), True],
               [lbl("paid", lang), format_money(inv.paid_total, cur)],
               [lbl("balance", lang), format_money(inv.balance, cur), True]]
    sections = [
        {"type": "key_values", "items": _header_kv(inv, patient, clinic, dept, lang), "columns": 2},
        {"type": "heading", "text": lbl("items", lang)},
        {"type": "table", "columns": [lbl(k, lang) for k in ("description", "qty", "unit_price", "discount",
                                                               "amount")],
         "rows": rows, "widths": [4, 1, 1.6, 1.6, 1.8], "align": ["start", "center", "end", "end", "end"]},
        {"type": "totals", "items": totals},
    ]
    pays = [pay for pay in payments_of(inv) if not pay.is_void]
    if pays:
        sections += [{"type": "heading", "text": lbl("payments", lang)},
                     {"type": "table", "columns": [lbl("receipt_no", lang), lbl("date", lang), lbl("method", lang),
                                                   lbl("received_by", lang), lbl("amount", lang)],
                      "rows": [[receipt_number(inv, pay), format_dt(pay.paid_at), lbl("cash", lang),
                                pay.author_name, format_money(pay.amount, cur)] for pay in pays],
                      "widths": [2, 2, 1.2, 2.2, 2], "align": ["start", "start", "start", "start", "end"]}]
    if inv.notes:
        sections += [{"type": "heading", "text": lbl("notes", lang)}, {"type": "paragraph", "text": inv.notes}]
    sections.append({"type": "signature", "labels": [lbl("signature", lang)]})
    title = lbl("invoice", lang)
    if inv.status in ("void", "draft"):
        title = f"{title} — {lbl(inv.status, lang)}"
    return documents.render(inv.health_center_id, inv.department_id, "invoice", title, sections, lang=lang,
                            subtitle=inv.display_number)


def receipt_pdf(inv, payment_id=None, lang="en"):
    pays = [pay for pay in payments_of(inv) if not pay.is_void]
    if payment_id is not None:
        pays = [pay for pay in payments_of(inv) if pay.id == payment_id]
        if not pays:
            raise NotFound("Payment not found")
    if not pays:
        raise ValidationError("This invoice has no payments.", code="no_payments")
    patient, clinic, dept = _lookup(inv)
    cur = inv.currency
    kv = [[lbl("for_invoice", lang), inv.display_number],
          [lbl("patient", lang), patient.full_name if patient else ""],
          [lbl("patient_code", lang), patient.display_code if patient else ""],
          [lbl("clinic", lang), clinic.name if clinic else ""]]
    if len(pays) == 1:
        pay = pays[0]
        kv = [[lbl("receipt_no", lang), receipt_number(inv, pay)], [lbl("date", lang), format_dt(pay.paid_at)]] + kv
        kv += [[lbl("method", lang), lbl("cash", lang)], [lbl("received_by", lang), pay.author_name]]
        subtitle = receipt_number(inv, pay)
    else:
        subtitle = inv.display_number
    rows = [[receipt_number(inv, pay), format_dt(pay.paid_at), pay.author_name,
             format_money(pay.amount, cur) + (" " + lbl("voided_payment", lang) if pay.is_void else "")]
            for pay in pays]
    paid_here = sum((pay.amount for pay in pays if not pay.is_void), 0)
    sections = [
        {"type": "key_values", "items": kv, "columns": 2},
        {"type": "table", "columns": [lbl("receipt_no", lang), lbl("date", lang), lbl("received_by", lang),
                                      lbl("amount", lang)],
         "rows": rows, "widths": [2, 2, 2.5, 2], "align": ["start", "start", "start", "end"]},
        {"type": "totals", "items": [[lbl("amount_paid", lang), format_money(paid_here, cur), True],
                                     [lbl("total", lang), format_money(inv.total, cur)],
                                     [lbl("paid", lang), format_money(inv.paid_total, cur)],
                                     [lbl("balance", lang), format_money(inv.balance, cur), True]]},
        {"type": "signature", "labels": [lbl("received_by", lang)]},
    ]
    return documents.render(inv.health_center_id, inv.department_id, "receipt", lbl("receipt", lang), sections,
                            lang=lang, subtitle=subtitle, page_size="A5")
