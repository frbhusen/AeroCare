"""Bill clinical work: turn a lab request, radiology study or dental treatment into invoice lines
(reference_type/reference_id) and the patient-summary 'financial' provider.

    preview_source(p, "lab_request", 12)       -> {patient, clinic_options, default_clinic_id, lines, billed_in}
    create_from_source(p, {...})               -> draft (or issued) Invoice
    is_referenced(center_id, "dental_treatment", 7) -> True if a live, non-void invoice bills it

Price fields: lab_request_items.price (snapshot), dental_treatments.fee; radiology studies have no
price, so the line starts at 0.00 (or a given unit_price) for the user to set.
"""
from decimal import Decimal

from sqlalchemy import select

from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.extensions import db
from backend.app.models import Clinic
from .models import Invoice, InvoiceItem
from .pricing import m, money

SOURCE_TYPES = ("lab_request", "radiology_study", "dental_treatment")


def _model(source_type):
    try:
        if source_type == "lab_request":
            from backend.app.modules.laboratory.models import LabRequest
            return LabRequest
        if source_type == "radiology_study":
            from backend.app.modules.radiology.models import RadiologyStudy
            return RadiologyStudy
        if source_type == "dental_treatment":
            from backend.app.modules.dentistry.models import Treatment
            return Treatment
    except ImportError:
        pass
    raise NotFound("Not found")


def _clinic_options(p, obj, source_type):
    """Clinics the work may be billed in (performing clinic first), limited to the caller's scope."""
    if source_type == "dental_treatment":
        ids = [obj.clinic_id]
    else:
        perf_clinic = obj.lab_clinic_id if source_type == "lab_request" else obj.radiology_clinic_id
        perf_dept = obj.lab_department_id if source_type == "lab_request" else obj.radiology_department_id
        ids = [perf_clinic] if perf_clinic else sorted(c for c, d in p.clinic_department.items() if d == perf_dept)
        ids.append(obj.requesting_clinic_id)
    out = []
    for cid in ids:
        if cid and cid not in out and p.can_clinic(cid):
            out.append(cid)
    return out


def load_source(p, source_type, source_id):
    if source_type not in SOURCE_TYPES:
        raise ValidationError("Invalid input", details={"source_type": "unknown"})
    model = _model(source_type)
    obj = db.session.execute(select(model).where(model.id == source_id, p.tenant(model), model.live())
                             ).scalar_one_or_none()
    if obj is None:
        raise NotFound("Not found")
    options = _clinic_options(p, obj, source_type)
    if not options:
        raise NotFound("Not found")
    if getattr(obj, "status", None) == "cancelled":
        raise ValidationError("Cancelled work cannot be billed.", code="source_cancelled")
    return obj, options


def source_lines(source_type, obj, unit_price=None):
    ref = {"reference_type": source_type, "reference_id": obj.id}
    if source_type == "lab_request":
        from backend.app.modules.laboratory.models import LabRequestItem
        items = db.session.execute(select(LabRequestItem).where(
            LabRequestItem.request_id == obj.id, LabRequestItem.health_center_id == obj.health_center_id)
            .order_by(LabRequestItem.sort_order, LabRequestItem.id)).scalars().all()
        return [{"kind": "lab_test", "description": f"{i.test_name} ({i.test_code})"[:300], "qty": "1",
                 "unit_price": m(i.price or 0), **ref} for i in items]
    if source_type == "radiology_study":
        desc = " - ".join(x for x in (obj.exam_type, obj.body_region) if x)
        return [{"kind": "radiology", "description": desc[:300] or "Radiology", "qty": "1",
                 "unit_price": m(unit_price or 0), **ref}]
    tooth = f" #{obj.tooth_number}" if obj.tooth_number else ""
    desc = (obj.procedure or obj.description or "Dental treatment") + tooth
    return [{"kind": "treatment", "description": desc[:300], "qty": "1", "unit_price": m(obj.fee or 0), **ref}]


def billed_in(center_id, source_type, source_id):
    """Invoice numbers (non-void, live) that already reference this work."""
    rows = db.session.execute(select(Invoice.number).join(
        InvoiceItem, (InvoiceItem.invoice_id == Invoice.id) & (InvoiceItem.health_center_id == Invoice.health_center_id))
        .where(Invoice.health_center_id == center_id, Invoice.live(), Invoice.status != "void",
               InvoiceItem.reference_type == source_type, InvoiceItem.reference_id == source_id).distinct()).scalars()
    return [f"INV-{n:06d}" for n in rows]


def is_referenced(center_id, reference_type, reference_id):
    return bool(billed_in(center_id, reference_type, reference_id))


def preview_source(p, source_type, source_id):
    p.require("billing.view")
    obj, options = load_source(p, source_type, source_id)
    clinics = {c.id: c.name for c in db.session.execute(select(Clinic).where(Clinic.id.in_(options))).scalars()}
    return {"source_type": source_type, "source_id": obj.id, "patient_id": obj.patient_id,
            "clinic_options": [{"id": c, "name": clinics.get(c)} for c in options], "default_clinic_id": options[0],
            "doctor_user_id": getattr(obj, "doctor_user_id", None),
            "lines": source_lines(source_type, obj), "billed_in": billed_in(p.center_id, source_type, obj.id)}


def create_from_source(p, data):
    from .service import create_invoice
    obj, options = load_source(p, data["source_type"], data["source_id"])
    clinic_id = data.get("clinic_id") or options[0]
    if clinic_id not in options:
        raise ValidationError("Invalid input", details={"clinic_id": "not a billing clinic for this work"})
    already = billed_in(p.center_id, data["source_type"], obj.id)
    if already and not data.get("allow_duplicate"):
        raise Conflict("This work is already billed.", code="already_billed", details={"invoices": already})
    lines = source_lines(data["source_type"], obj, data.get("unit_price"))
    for ln in lines:
        ln["qty"] = Decimal(ln["qty"])
        ln["unit_price"] = money(ln["unit_price"])
    body = {"patient_id": obj.patient_id, "clinic_id": clinic_id, "items": lines, "issue": data.get("issue"),
            "notes": data.get("notes")}
    if getattr(obj, "doctor_user_id", None):
        body["doctor_user_id"] = obj.doctor_user_id
    return create_invoice(p, body)


# ---------------------------------------------------------------- patient summary provider
def financial_summary(p, patient):
    if not p.has("billing.view"):
        return None
    from .service import patient_history
    _, invoices, _, totals = patient_history(p, patient.id)
    if not invoices:
        return None
    return {"totals": totals, "invoices": [
        {"id": i.id, "number": i.display_number, "status": i.status, "clinic_id": i.clinic_id, "total": m(i.total),
         "paid_total": m(i.paid_total), "balance": m(i.balance), "currency": i.currency,
         "issued_at": i.issued_at.isoformat() if i.issued_at else None} for i in invoices[:20]]}


def register_summary():
    try:
        from backend.app.modules.patients.summary import register_summary_provider
    except ImportError:
        return
    register_summary_provider("financial", financial_summary, order=300)
