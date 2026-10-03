"""Pharmacy business logic: prescription queue, dispensing, OTC sales, medication catalog.

Access: `pharmacy.dispense` AND (a pharmacy-environment clinic in scope OR center-wide).
Pharmacy staff see prescription lines + basic patient identity (name, code, age, gender,
allergies) only — never visits or specialty records.
"""
from decimal import Decimal

from sqlalchemy import func, or_, select

from backend.app.core.api import check_version, page_params
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, local_day_bounds, local_today
from backend.app.extensions import db
from backend.app.models import Clinic, Department, Patient, Prescription, PrescriptionItem
from backend.app.services.clinical import get_patient, normalize_name
from backend.app.modules.inventory.service import clinic_location, mstr, qstr
from backend.app.modules.inventory import stock
from .models import Dispensation, DispensationItem, Sale, SaleItem

OPEN = ("pending", "partially_dispensed")
CENT = Decimal("0.01")


# ---------------------------------------------------------------- access ---------------------------

def pharmacy_clinics(p):
    return sorted(c for c in p.clinic_ids if p.department_env.get(p.clinic_department.get(c)) == "pharmacy")


def require_pharmacy(p):
    p.require("pharmacy.dispense")
    if not (p.center_wide or pharmacy_clinics(p)):
        raise Forbidden("Pharmacy access required.", code="no_pharmacy_scope")


def resolve_clinic(p, clinic_id):
    """Pharmacy clinic to act from (explicit, or the only one in scope)."""
    clinics = pharmacy_clinics(p)
    if clinic_id is None:
        if len(clinics) != 1:
            raise ValidationError("Invalid input", details={"clinic_id": "is required"})
        return clinics[0]
    if clinic_id not in clinics:
        raise NotFound("Pharmacy clinic not found")
    return clinic_id


def meta(p):
    require_pharmacy(p)
    clinics = pharmacy_clinics(p)
    names = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        p.tenant(Clinic), Clinic.id.in_(clinics or [-1]))).all())
    out = []
    for c in clinics:
        loc = clinic_location(p, c)
        out.append({"id": c, "name": names.get(c), "location_id": loc.id})
    db.session.commit()
    return {"clinics": out, "statuses": ["pending", "partially_dispensed", "dispensed", "cancelled"],
            "can_view_inventory": p.has("inventory.view")}


# ---------------------------------------------------------------- serialization --------------------

def _age(dob):
    if not dob:
        return None
    t = local_today()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


def patient_brief(pt):
    return {"id": pt.id, "full_name": pt.full_name, "code": pt.display_code, "age": _age(pt.date_of_birth),
            "gender": pt.gender, "allergies": pt.allergies}


def rx_item_json(i):
    return {"id": i.id, "medication_name": i.medication_name, "inventory_item_id": i.inventory_item_id,
            "dose": i.dose, "frequency": i.frequency, "duration": i.duration, "instructions": i.instructions,
            "quantity": qstr(i.quantity), "dispensed_quantity": qstr(i.dispensed_quantity or 0)}


def _rx_bundle(p, rxs):
    ids = [r.id for r in rxs]
    items = db.session.execute(select(PrescriptionItem).where(
        p.tenant(PrescriptionItem), PrescriptionItem.prescription_id.in_(ids or [-1]))
        .order_by(PrescriptionItem.sort_order, PrescriptionItem.id)).scalars().all()
    by_rx = {}
    for i in items:
        by_rx.setdefault(i.prescription_id, []).append(i)
    pts = {pt.id: pt for pt in db.session.execute(select(Patient).where(
        p.tenant(Patient), Patient.id.in_({r.patient_id for r in rxs} or {-1}))).scalars()}
    clinics = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        p.tenant(Clinic), Clinic.id.in_({r.clinic_id for r in rxs} or {-1}))).all())
    depts = dict(db.session.execute(select(Department.id, Department.name).where(
        p.tenant(Department), Department.id.in_({r.department_id for r in rxs} or {-1}))).all())

    def one(r):
        return {"id": r.id, "status": r.status, "prescribed_at": iso(r.prescribed_at), "notes": r.notes,
                "doctor_name": r.author_name, "clinic_name": clinics.get(r.clinic_id),
                "department_name": depts.get(r.department_id), "version": r.version,
                "patient": patient_brief(pts[r.patient_id]) if r.patient_id in pts else None,
                "items": [rx_item_json(i) for i in by_rx.get(r.id, [])]}
    return [one(r) for r in rxs]


# ---------------------------------------------------------------- queue ----------------------------

def queue(p, f):
    require_pharmacy(p)
    stmt = select(Prescription).where(p.tenant(Prescription), Prescription.live())
    status = f.get("status")
    if status in (None, "open"):
        stmt = stmt.where(Prescription.status.in_(OPEN))
    elif status != "all":
        stmt = stmt.where(Prescription.status == status)
    if f.get("q"):
        q = f["q"].strip()
        conds = [Patient.search_name.like(f"%{normalize_name(q)}%")]
        digits = q.upper().replace("PAT-", "").lstrip("0")
        if digits.isdigit():
            conds.append(Patient.code == int(digits))
        stmt = stmt.where(Prescription.patient_id.in_(select(Patient.id).where(p.tenant(Patient), or_(*conds))))
    if f.get("patient_id"):
        stmt = stmt.where(Prescription.patient_id == f["patient_id"])
    if f.get("date_from"):
        stmt = stmt.where(Prescription.prescribed_at >= local_day_bounds(f["date_from"])[0])
    if f.get("date_to"):
        stmt = stmt.where(Prescription.prescribed_at < local_day_bounds(f["date_to"])[1])
    page, per_page = page_params(25)
    total = db.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.session.execute(stmt.order_by(Prescription.prescribed_at, Prescription.id)
                              .limit(per_page).offset((page - 1) * per_page)).scalars().all()
    return {"items": _rx_bundle(p, rows), "page": page, "per_page": per_page, "total": total}


def _get_rx(p, rx_id, lock=False):
    stmt = select(Prescription).where(Prescription.id == rx_id, p.tenant(Prescription), Prescription.live())
    if lock:
        stmt = stmt.with_for_update()
    rx = db.session.execute(stmt).scalar_one_or_none()
    if rx is None:
        raise NotFound("Prescription not found")
    return rx


def dispensation_json(d, items):
    return {"id": d.id, "prescription_id": d.prescription_id, "clinic_id": d.clinic_id, "notes": d.notes,
            "author_name": d.author_name, "created_at": iso(d.created_at),
            "items": [{"id": i.id, "prescription_item_id": i.prescription_item_id,
                       "inventory_item_id": i.inventory_item_id, "item_name": i.item_name,
                       "quantity": qstr(i.quantity), "is_substitution": i.is_substitution, "note": i.note,
                       "lots": i.lots} for i in items]}


def _dispensations(p, rx_id):
    ds = db.session.execute(select(Dispensation).where(p.tenant(Dispensation), Dispensation.prescription_id == rx_id)
                            .order_by(Dispensation.created_at, Dispensation.id)).scalars().all()
    items = db.session.execute(select(DispensationItem).where(
        p.tenant(DispensationItem), DispensationItem.dispensation_id.in_([d.id for d in ds] or [-1]))
        .order_by(DispensationItem.id)).scalars().all()
    return [dispensation_json(d, [i for i in items if i.dispensation_id == d.id]) for d in ds]


def get_prescription(p, rx_id):
    require_pharmacy(p)
    rx = _get_rx(p, rx_id)
    out = _rx_bundle(p, [rx])[0]
    out["dispensations"] = _dispensations(p, rx.id)
    return out


# ---------------------------------------------------------------- dispensing -----------------------

def _line_done(i):
    disp = i.dispensed_quantity or 0
    return disp >= i.quantity if i.quantity is not None else disp > 0


def dispense(p, rx_id, data):
    require_pharmacy(p)
    clinic_id = resolve_clinic(p, data.get("clinic_id"))
    rx = _get_rx(p, rx_id, lock=True)
    if rx.status not in OPEN:
        raise Conflict("This prescription is already closed.", code="prescription_closed",
                       details={"status": rx.status})
    if data.get("version") is not None:
        check_version(rx, data["version"])
    lines = data.get("items") or []
    if not lines and not data.get("complete"):
        raise ValidationError("Invalid input", details={"items": "must have at least 1 items"})
    rx_items = {i.id: i for i in db.session.execute(select(PrescriptionItem).where(
        p.tenant(PrescriptionItem), PrescriptionItem.prescription_id == rx.id).with_for_update()).scalars()}
    loc = clinic_location(p, clinic_id)
    planned, add = [], {}
    for n, line in enumerate(lines):
        ri = rx_items.get(line["prescription_item_id"])
        if ri is None:
            raise ValidationError("Invalid input", details={f"items.{n}.prescription_item_id": "not on this prescription"})
        inv_id = line.get("inventory_item_id") or ri.inventory_item_id
        if not inv_id:
            raise ValidationError("Invalid input", details={f"items.{n}.inventory_item_id": "is required"})
        subst = bool(line.get("is_substitution")) or (ri.inventory_item_id is not None and inv_id != ri.inventory_item_id)
        if subst and not line.get("note"):
            raise ValidationError("Invalid input", details={f"items.{n}.note": "is required for a substitution"})
        add[ri.id] = add.get(ri.id, Decimal(0)) + line["quantity"]
        if ri.quantity is not None and (ri.dispensed_quantity or 0) + add[ri.id] > ri.quantity:
            raise ValidationError("Quantity exceeds what was prescribed.", code="exceeds_prescribed",
                                  details={f"items.{n}.quantity": f"at most {qstr(ri.quantity - (ri.dispensed_quantity or 0))}"})
        planned.append((ri, inv_id, subst, line))
    items = stock.lock_items(p, [inv for _, inv, _, _ in planned])
    d = Dispensation(health_center_id=p.center_id, prescription_id=rx.id, clinic_id=clinic_id,
                     patient_id=rx.patient_id, notes=data.get("notes"))
    d.set_author(p.user)
    db.session.add(d)
    db.session.flush()
    for ri, inv_id, subst, line in planned:
        item = items[inv_id]
        if not item.is_medication or not item.is_active:
            raise ValidationError("Invalid input", details={"inventory_item_id": "must be an active medication"})
        taken = stock.decrement(p, item, loc, line["quantity"], "dispense", lot_id=line.get("lot_id"),
                                reason=f"Prescription #{rx.id}", reference_type="dispensation", reference_id=d.id)
        db.session.add(DispensationItem(health_center_id=p.center_id, dispensation_id=d.id, prescription_item_id=ri.id,
                                        inventory_item_id=item.id, item_name=item.name, quantity=line["quantity"],
                                        is_substitution=subst, note=line.get("note"), lots=stock.taken_json(taken)))
        ri.dispensed_quantity = (ri.dispensed_quantity or 0) + line["quantity"]
    if data.get("complete") or all(_line_done(i) for i in rx_items.values()):
        rx.status = "dispensed"
    elif any((i.dispensed_quantity or 0) > 0 for i in rx_items.values()):
        rx.status = "partially_dispensed"
    db.session.commit()
    return get_prescription(p, rx.id)


# ---------------------------------------------------------------- sales ----------------------------

def sale_json(s, items=None):
    out = {"id": s.id, "clinic_id": s.clinic_id, "patient_id": s.patient_id, "customer_name": s.customer_name,
           "total": mstr(s.total), "paid_amount": mstr(s.paid_amount), "change": mstr(max(s.paid_amount - s.total, 0)),
           "balance_due": mstr(max(s.total - s.paid_amount, 0)), "notes": s.notes, "author_name": s.author_name,
           "created_at": iso(s.created_at)}
    if items is not None:
        out["items"] = [{"id": i.id, "inventory_item_id": i.inventory_item_id, "item_name": i.item_name,
                         "quantity": qstr(i.quantity), "unit_price": mstr(i.unit_price),
                         "line_total": mstr(i.line_total), "lots": i.lots} for i in items]
    return out


def create_sale(p, data):
    require_pharmacy(p)
    clinic_id = resolve_clinic(p, data.get("clinic_id"))
    patient_id = None
    if data.get("patient_id"):
        patient_id = get_patient(p, data["patient_id"], perm=None).id
    loc = clinic_location(p, clinic_id)
    items = stock.lock_items(p, [l["inventory_item_id"] for l in data["items"]])
    s = Sale(health_center_id=p.center_id, clinic_id=clinic_id, patient_id=patient_id,
             customer_name=data.get("customer_name"), total=Decimal(0), notes=data.get("notes"))
    s.set_author(p.user)
    db.session.add(s)
    db.session.flush()
    total, rows = Decimal(0), []
    for n, line in enumerate(data["items"]):
        item = items[line["inventory_item_id"]]
        if not item.is_active:
            raise ValidationError("Invalid input", details={f"items.{n}.inventory_item_id": "item is inactive"})
        price = line.get("unit_price")
        if price is None:
            price = item.selling_price
        if price is None:
            raise ValidationError("Invalid input", details={f"items.{n}.unit_price": "is required (no selling price)"})
        taken = stock.decrement(p, item, loc, line["quantity"], "sale", lot_id=line.get("lot_id"),
                                reason=f"Sale #{s.id}", reference_type="sale", reference_id=s.id)
        lt = (price * line["quantity"]).quantize(CENT)
        total += lt
        rows.append(SaleItem(health_center_id=p.center_id, sale_id=s.id, inventory_item_id=item.id, item_name=item.name,
                             quantity=line["quantity"], unit_price=price, line_total=lt, lots=stock.taken_json(taken)))
    db.session.add_all(rows)
    s.total = total
    s.paid_amount = data["paid_amount"] if data.get("paid_amount") is not None else total
    db.session.commit()
    return sale_json(s, rows)


def _sale_clause(p):
    return Sale.clinic_id.in_(pharmacy_clinics(p) or [-1])


def list_sales(p, f):
    require_pharmacy(p)
    stmt = select(Sale).where(p.tenant(Sale), _sale_clause(p))
    if f.get("clinic_id"):
        stmt = stmt.where(Sale.clinic_id == f["clinic_id"])
    if f.get("patient_id"):
        stmt = stmt.where(Sale.patient_id == f["patient_id"])
    if f.get("date_from"):
        stmt = stmt.where(Sale.created_at >= local_day_bounds(f["date_from"])[0])
    if f.get("date_to"):
        stmt = stmt.where(Sale.created_at < local_day_bounds(f["date_to"])[1])
    page, per_page = page_params(25)
    total = db.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.session.execute(stmt.order_by(Sale.created_at.desc(), Sale.id.desc())
                              .limit(per_page).offset((page - 1) * per_page)).scalars().all()
    return {"items": [sale_json(s) for s in rows], "page": page, "per_page": per_page, "total": total}


def get_sale(p, sale_id):
    require_pharmacy(p)
    s = db.session.execute(select(Sale).where(Sale.id == sale_id, p.tenant(Sale), _sale_clause(p))
                           ).scalar_one_or_none()
    if s is None:
        raise NotFound("Sale not found")
    items = db.session.execute(select(SaleItem).where(p.tenant(SaleItem), SaleItem.sale_id == s.id)
                               .order_by(SaleItem.id)).scalars().all()
    return sale_json(s, items)


# ---------------------------------------------------------------- catalog / expiry -----------------

def medications(p, f):
    """Active medication items with usable stock at the pharmacy clinic location."""
    require_pharmacy(p)
    from backend.app.modules.inventory.models import InventoryItem, StockLot
    from backend.app.modules.inventory.service import item_clause
    clinic_id = resolve_clinic(p, f.get("clinic_id"))
    loc = clinic_location(p, clinic_id)
    db.session.commit()
    today = local_today()
    usable = (select(func.coalesce(func.sum(StockLot.quantity), 0)).where(
        StockLot.health_center_id == InventoryItem.health_center_id, StockLot.item_id == InventoryItem.id,
        StockLot.location_id == loc.id, or_(StockLot.expiry_date.is_(None), StockLot.expiry_date >= today))
        .correlate(InventoryItem).scalar_subquery())
    nearest = (select(func.min(StockLot.expiry_date)).where(
        StockLot.health_center_id == InventoryItem.health_center_id, StockLot.item_id == InventoryItem.id,
        StockLot.location_id == loc.id, StockLot.quantity > 0, StockLot.expiry_date >= today)
        .correlate(InventoryItem).scalar_subquery())
    stmt = select(InventoryItem, usable.label("usable"), nearest.label("nearest")).where(
        p.tenant(InventoryItem), InventoryItem.live(), item_clause(p), InventoryItem.is_medication.is_(True),
        InventoryItem.is_active.is_(True))
    if f.get("q"):
        q = f["q"].strip()
        stmt = stmt.where(or_(func.lower(InventoryItem.name).like(f"%{q.lower()}%"), InventoryItem.barcode == q,
                              func.lower(InventoryItem.sku) == q.lower()))
    if f.get("in_stock"):
        stmt = stmt.where(usable > 0)
    page, per_page = page_params(50)
    total = db.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.session.execute(stmt.order_by(InventoryItem.name, InventoryItem.id)
                              .limit(per_page).offset((page - 1) * per_page)).all()
    return {"location_id": loc.id, "clinic_id": clinic_id, "page": page, "per_page": per_page, "total": total,
            "items": [{"id": i.id, "name": i.name, "category": i.category, "sku": i.sku, "barcode": i.barcode,
                       "unit": i.unit, "selling_price": mstr(i.selling_price), "available": qstr(u),
                       "nearest_expiry": iso(ne), "low": i.low_stock_threshold is not None
                       and u <= i.low_stock_threshold} for i, u, ne in rows]}


def expiry(p, f):
    require_pharmacy(p)
    from backend.app.modules.inventory import reports
    clinic_id = resolve_clinic(p, f.get("clinic_id"))
    loc = clinic_location(p, clinic_id)
    db.session.commit()
    days = f.get("days")
    return reports.expiry_report(p, 30 if days is None else days, loc.id)

