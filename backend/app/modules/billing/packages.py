"""Billing Packages & Treatment Plans service (laser packages, orthodontic phases, installment schedules)."""
from decimal import Decimal
from sqlalchemy import select

from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import Bool, Enum, Id, Int, List, Num, Obj, Str, Text, validate
from backend.app.extensions import db
from backend.app.models.clinical import Patient
from backend.app.models.org import Clinic, Department
from backend.app.modules.billing.models import BillingPackage, Invoice, PACKAGE_STATUSES
from backend.app.services import deletion
from backend.app.services.clinical import get_patient

INSTALLMENT_ITEM = Obj({
    "due_date": Str(max_len=50),
    "amount": Num(min_value=0, places=2),
    "label": Str(max_len=200),
    "paid": Bool(),
})


def package_json(pkg, invoice=None, patient=None):
    if pkg is None:
        return None
    inv_data = None
    if invoice:
        inv_data = {
            "id": invoice.id,
            "number": invoice.number,
            "display_number": f"INV-{invoice.number:06d}",
            "status": invoice.status,
            "total": str(invoice.total),
            "paid_total": str(invoice.paid_total),
            "balance": str(invoice.balance),
        }
    return {
        "id": pkg.id,
        "patient_id": pkg.patient_id,
        "patient_name": patient.full_name if patient else None,
        "patient_code": patient.display_code if patient else None,
        "department_id": pkg.department_id,
        "clinic_id": pkg.clinic_id,
        "invoice_id": pkg.invoice_id,
        "invoice": inv_data,
        "title": pkg.title,
        "total_price": str(pkg.total_price),
        "total_sessions": pkg.total_sessions,
        "completed_sessions": pkg.completed_sessions,
        "remaining_sessions": max(0, pkg.total_sessions - pkg.completed_sessions),
        "status": pkg.status,
        "installments": pkg.installments or [],
        "notes": pkg.notes,
        "author_name": pkg.author_name,
        "created_at": iso(pkg.created_at),
        "version": pkg.version,
    }


def list_packages(p, query=None):
    p.require("billing.view")
    q = query or {}
    stmt = select(BillingPackage).where(p.tenant(BillingPackage), BillingPackage.live())

    if q.get("patient_id"):
        stmt = stmt.where(BillingPackage.patient_id == int(q["patient_id"]))
    if q.get("department_id"):
        stmt = stmt.where(BillingPackage.department_id == int(q["department_id"]))
    if q.get("clinic_id"):
        stmt = stmt.where(BillingPackage.clinic_id == int(q["clinic_id"]))
    if q.get("status"):
        stmt = stmt.where(BillingPackage.status == q["status"])

    stmt = stmt.order_by(BillingPackage.created_at.desc(), BillingPackage.id.desc())
    items = db.session.execute(stmt).scalars().all()

    inv_ids = {pkg.invoice_id for pkg in items if pkg.invoice_id}
    pt_ids = {pkg.patient_id for pkg in items}
    invoices = {inv.id: inv for inv in db.session.execute(select(Invoice).where(Invoice.id.in_(inv_ids))).scalars()} if inv_ids else {}
    patients = {pt.id: pt for pt in db.session.execute(select(Patient).where(Patient.id.in_(pt_ids))).scalars()} if pt_ids else {}

    return {"items": [package_json(pkg, invoices.get(pkg.invoice_id), patients.get(pkg.patient_id)) for pkg in items]}


def _clean_installments(items):
    out = []
    for it in (items or []):
        d = dict(it)
        if "amount" in d and d["amount"] is not None:
            d["amount"] = str(d["amount"])
        out.append(d)
    return out


def create_package(p, body):
    p.require("billing.create")
    data = validate(body, {
        "patient_id": Id(required=True),
        "department_id": Id(required=True),
        "clinic_id": Id(required=True),
        "title": Str(required=True, min_len=2, max_len=200),
        "total_price": Num(min_value=0, places=2, required=True),
        "total_sessions": Int(min_value=1, max_value=1000, required=True),
        "installments": List(INSTALLMENT_ITEM, max_items=50),
        "notes": Text(max_len=5000),
    })

    get_patient(p, data["patient_id"])
    p.require(clinic_id=data["clinic_id"])

    pkg = BillingPackage(
        health_center_id=p.center_id,
        patient_id=data["patient_id"],
        department_id=data["department_id"],
        clinic_id=data["clinic_id"],
        title=data["title"].strip(),
        total_price=Decimal(str(data["total_price"])),
        total_sessions=data["total_sessions"],
        completed_sessions=0,
        status="active",
        installments=_clean_installments(data.get("installments")),
        notes=data.get("notes"),
    )
    pkg.set_author(p.user)
    db.session.add(pkg)
    db.session.commit()
    return package_json(pkg)


def record_session(p, package_id, body=None):
    p.require("billing.edit")
    pkg = db.session.execute(
        select(BillingPackage).where(p.tenant(BillingPackage), BillingPackage.id == package_id, BillingPackage.live())
    ).scalar_one_or_none()
    if not pkg:
        raise NotFound("Package not found")

    if pkg.status != "active":
        raise Conflict(f"Cannot record session on {pkg.status} package.", code="package_not_active")

    delta = (body or {}).get("delta", 1)
    new_completed = pkg.completed_sessions + delta
    if new_completed > pkg.total_sessions:
        raise ValidationError("Cannot exceed total sessions in package.", details={"completed_sessions": "exceeds total"})
    if new_completed < 0:
        new_completed = 0

    pkg.completed_sessions = new_completed
    if pkg.completed_sessions >= pkg.total_sessions:
        pkg.status = "completed"

    db.session.commit()
    return package_json(pkg)


def update_package(p, package_id, body):
    p.require("billing.edit")
    pkg = db.session.execute(
        select(BillingPackage).where(p.tenant(BillingPackage), BillingPackage.id == package_id, BillingPackage.live())
    ).scalar_one_or_none()
    if not pkg:
        raise NotFound("Package not found")

    data = validate(body, {
        "title": Str(min_len=2, max_len=200),
        "status": Enum(PACKAGE_STATUSES),
        "completed_sessions": Int(min_value=0, max_value=1000),
        "total_sessions": Int(min_value=1, max_value=1000),
        "installments": List(INSTALLMENT_ITEM, max_items=50),
        "notes": Text(max_len=5000),
    }, partial=True)

    for k, val in data.items():
        if val is not None:
            if k == "installments":
                val = _clean_installments(val)
            setattr(pkg, k, val)

    if pkg.completed_sessions > pkg.total_sessions:
        pkg.total_sessions = pkg.completed_sessions

    db.session.commit()
    return package_json(pkg)
