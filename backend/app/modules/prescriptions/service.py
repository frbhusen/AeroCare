"""Shared prescriptions (spec §42). Core models: models/clinical.py (Prescription, PrescriptionItem).

Ownership = clinic. Doctors write prescriptions for clinics in their scope; the pharmacy module
moves them pending -> partially_dispensed/dispensed (not here). Editing is allowed only while
the prescription is still `pending`.
"""
from decimal import Decimal

from sqlalchemy import delete as sa_delete, select

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import iso, local_day_bounds, utcnow
from backend.app.core.validation import Date, Enum, Id, List, Num, Obj, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Patient, Prescription, PrescriptionItem, Visit
from backend.app.models.clinical import PRESCRIPTION_STATUSES
from backend.app.services import deletion
from backend.app.services.clinical import get_clinic, get_patient, link_patient_to_clinic

from backend.app.modules.patients.helpers import clinic_names, department_info

deletion.register("prescription", Prescription)

ITEM_SCHEMA = {
    "medication_name": Str(required=True, max_len=200),
    "inventory_item_id": Id(),
    "dose": Str(max_len=100),
    "frequency": Str(max_len=100),
    "duration": Str(max_len=100),
    "instructions": Text(max_len=2000),
    "quantity": Num(min_value=0, max_value=1000000, places=2),
}
ITEMS = List(Obj(ITEM_SCHEMA), min_items=1, max_items=50, required=True)


# ------------------------------------------------------------------ serialization
def _num(d):
    return None if d is None else str(Decimal(d).quantize(Decimal("0.01")))


def item_json(i):
    return {"id": i.id, "medication_name": i.medication_name, "inventory_item_id": i.inventory_item_id,
            "dose": i.dose, "frequency": i.frequency, "duration": i.duration, "instructions": i.instructions,
            "quantity": _num(i.quantity), "dispensed_quantity": _num(i.dispensed_quantity),
            "sort_order": i.sort_order}


def _items_for(ids):
    out = {}
    if not ids:
        return out
    for i in db.session.execute(select(PrescriptionItem).where(PrescriptionItem.prescription_id.in_(ids))
                                .order_by(PrescriptionItem.sort_order, PrescriptionItem.id)).scalars():
        out.setdefault(i.prescription_id, []).append(item_json(i))
    return out


def serialize_many(center_id, rows, with_patient=True):
    items = _items_for([r.id for r in rows])
    names = clinic_names(center_id, [r.clinic_id for r in rows])
    depts = department_info(center_id, [r.department_id for r in rows])
    patients = {}
    if with_patient and rows:
        patients = {pt.id: pt for pt in db.session.execute(
            select(Patient).where(Patient.id.in_({r.patient_id for r in rows}))).scalars()}
    out = []
    for r in rows:
        d = {"id": r.id, "patient_id": r.patient_id, "clinic_id": r.clinic_id, "clinic_name": names.get(r.clinic_id),
             "department_id": r.department_id, "department_name": depts.get(r.department_id, {}).get("name"),
             "visit_id": r.visit_id, "prescribed_at": iso(r.prescribed_at), "status": r.status, "notes": r.notes,
             "author_user_id": r.author_user_id, "author_name": r.author_name, "author_role": r.author_role,
             "created_at": iso(r.created_at), "updated_at": iso(r.updated_at), "version": r.version,
             "items": items.get(r.id, [])}
        if with_patient:
            pt = patients.get(r.patient_id)
            d["patient"] = {"id": pt.id, "display_code": pt.display_code, "full_name": pt.full_name} if pt else None
        out.append(d)
    return out


def rx_json(rx):
    return serialize_many(rx.health_center_id, [rx])[0]


# ------------------------------------------------------------------ queries
def get_rx(p, rx_id, perm="medical_records.view"):
    rx = db.session.execute(select(Prescription).where(
        Prescription.id == rx_id, p.tenant(Prescription), Prescription.live(),
        p.clinic_clause(Prescription.clinic_id))).scalar_one_or_none()
    if rx is None:
        raise NotFound("Prescription not found")
    p.require(perm)
    return rx


def list_rx(p, args):
    p.require("medical_records.view")
    a = validate(args, {"patient_id": Id(), "clinic_id": Id(), "visit_id": Id(), "department_id": Id(),
                        "status": Enum(PRESCRIPTION_STATUSES), "date_from": Date(), "date_to": Date()})
    stmt = select(Prescription).where(p.tenant(Prescription), Prescription.live(),
                                      p.clinic_clause(Prescription.clinic_id))
    if a.get("patient_id"):
        get_patient(p, a["patient_id"])
        stmt = stmt.where(Prescription.patient_id == a["patient_id"])
    else:
        stmt = stmt.where(Prescription.patient_id.in_(select(Patient.id).where(p.tenant(Patient), Patient.live())))
    if a.get("clinic_id"):
        p.require(clinic_id=a["clinic_id"])
        stmt = stmt.where(Prescription.clinic_id == a["clinic_id"])
    if a.get("department_id"):
        p.require(department_id=a["department_id"])
        stmt = stmt.where(Prescription.department_id == a["department_id"])
    if a.get("visit_id"):
        stmt = stmt.where(Prescription.visit_id == a["visit_id"])
    if a.get("status"):
        stmt = stmt.where(Prescription.status == a["status"])
    if a.get("date_from"):
        stmt = stmt.where(Prescription.prescribed_at >= local_day_bounds(a["date_from"])[0])
    if a.get("date_to"):
        stmt = stmt.where(Prescription.prescribed_at < local_day_bounds(a["date_to"])[1])
    stmt = stmt.order_by(Prescription.prescribed_at.desc(), Prescription.id.desc())
    out = paginate(db.session, stmt, lambda r: r)
    out["items"] = serialize_many(p.center_id, out["items"], with_patient=not a.get("patient_id"))
    return out


# ------------------------------------------------------------------ mutations
def _check_visit(p, visit_id, clinic_id, patient_id):
    v = db.session.execute(select(Visit).where(Visit.id == visit_id, p.tenant(Visit), Visit.live(),
                                               p.clinic_clause(Visit.clinic_id))).scalar_one_or_none()
    if v is None:
        raise NotFound("Visit not found")
    if v.clinic_id != clinic_id or v.patient_id != patient_id:
        raise ValidationError("The visit must belong to the same patient and clinic.",
                              details={"visit_id": "belongs to another patient or clinic"})
    return v


def _check_inventory_items(p, items):
    """inventory_item_id is an optional catalog link. If the inventory module is installed,
    verify the ids exist in this center (no cross-tenant references)."""
    ids = sorted({i["inventory_item_id"] for i in items if i.get("inventory_item_id")})
    table = db.metadata.tables.get("inventory_items")
    if not ids or table is None:
        return
    found = set(db.session.execute(select(table.c.id).where(table.c.id.in_(ids),
                                                            table.c.health_center_id == p.center_id)).scalars())
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValidationError("Unknown medication item.", details={"inventory_item_id": missing})


def _replace_items(rx, items):
    db.session.execute(sa_delete(PrescriptionItem).where(PrescriptionItem.prescription_id == rx.id))
    for n, it in enumerate(items):
        db.session.add(PrescriptionItem(health_center_id=rx.health_center_id, prescription_id=rx.id,
                                        medication_name=it["medication_name"],
                                        inventory_item_id=it.get("inventory_item_id"), dose=it.get("dose"),
                                        frequency=it.get("frequency"), duration=it.get("duration"),
                                        instructions=it.get("instructions"), quantity=it.get("quantity"),
                                        sort_order=n))


def create(p, body):
    data = validate(body, {"patient_id": Id(required=True), "clinic_id": Id(required=True), "visit_id": Id(),
                           "notes": Text(max_len=5000), "items": ITEMS})
    p.require("medical_records.create", clinic_id=data["clinic_id"])
    clinic = get_clinic(p, data["clinic_id"])
    pt = get_patient(p, data["patient_id"])
    if data.get("visit_id"):
        _check_visit(p, data["visit_id"], clinic.id, pt.id)
    _check_inventory_items(p, data["items"])
    link_patient_to_clinic(p.center_id, pt.id, clinic.id, clinic.department_id)
    rx = Prescription(health_center_id=p.center_id, patient_id=pt.id, department_id=clinic.department_id,
                      clinic_id=clinic.id, visit_id=data.get("visit_id"), prescribed_at=utcnow(), status="pending",
                      notes=data.get("notes"))
    rx.set_author(p.user)
    db.session.add(rx)
    db.session.flush()
    _replace_items(rx, data["items"])
    db.session.commit()
    return rx


def update(p, rx_id, body):
    rx = get_rx(p, rx_id, perm="medical_records.edit")
    data = validate(body, {"version": Id(required=True), "visit_id": Id(), "notes": Text(max_len=5000),
                           "items": List(Obj(ITEM_SCHEMA), min_items=1, max_items=50)}, partial=True)
    check_version(rx, data.pop("version"))
    if rx.status != "pending":
        raise ValidationError("Only pending prescriptions can be edited.", code="prescription_not_pending")
    if "visit_id" in data:
        if data["visit_id"]:
            _check_visit(p, data["visit_id"], rx.clinic_id, rx.patient_id)
        rx.visit_id = data["visit_id"]
    if "notes" in data:
        rx.notes = data["notes"]
    if data.get("items"):
        _check_inventory_items(p, data["items"])
        _replace_items(rx, data["items"])
    rx.updated_at = utcnow()  # always bump the row version (items live in another table)
    db.session.commit()
    return rx


def cancel(p, rx_id, body):
    rx = get_rx(p, rx_id, perm="medical_records.edit")
    data = validate(body, {"version": Id(required=True)})
    check_version(rx, data["version"])
    if rx.status not in ("pending", "partially_dispensed"):
        raise ValidationError("This prescription can no longer be cancelled.", code="prescription_not_cancellable")
    rx.status = "cancelled"
    db.session.commit()
    return rx


def delete(p, rx_id):
    rx = get_rx(p, rx_id, perm="medical_records.delete")
    dispensed = db.session.execute(select(PrescriptionItem.id).where(
        PrescriptionItem.prescription_id == rx.id, PrescriptionItem.dispensed_quantity > 0).limit(1)).first()
    if rx.status in ("dispensed", "partially_dispensed") or dispensed:
        raise ValidationError("Dispensed prescriptions cannot be deleted.", code="prescription_dispensed")
    return deletion.stage(p, rx, "prescription", f"Prescription #{rx.id}")


# ------------------------------------------------------------------ summary section
def summary_section(p, patient):
    if not p.has("medical_records.view"):
        return None
    rows = db.session.execute(select(Prescription).where(
        Prescription.patient_id == patient.id, p.tenant(Prescription), Prescription.live(),
        p.clinic_clause(Prescription.clinic_id)).order_by(Prescription.prescribed_at.desc()).limit(50)
    ).scalars().all()
    return {"items": serialize_many(p.center_id, rows, with_patient=False)}
