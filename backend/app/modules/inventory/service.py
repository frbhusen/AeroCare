"""Inventory catalog + locations + access rules. Stock operations live in stock.py.

Location access (see docs/modules/inventory.md):
  view   clinic: clinic in scope | department_pool: department visible | center_pool: center-wide
  draw   (use / transfer out / dispense / sale)  == view
  manage (receive / adjust / write-off)  clinic: clinic in scope | department_pool: department-level
         access (department manager, department receptionist, center-wide) | center_pool: center-wide
Every stock mutation also requires `inventory.edit` (pharmacy flows require `pharmacy.dispense`).
Out-of-scope locations/items are 404.

Item visibility: center-wide items (department_id NULL) are visible to everyone with
inventory.view; department-owned items to principals who see that department. Editing a
center-wide item requires a center-wide principal; editing a department item requires seeing it.
"""
from decimal import Decimal

from sqlalchemy import func, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso
from backend.app.extensions import db
from backend.app.models import Clinic, Department
from backend.app.services import deletion
from .models import InventoryItem, InventoryLocation, StockLot, StockMovement

deletion.register("inventory_item", InventoryItem)


def qstr(d):
    """Quantity as a compact string ("12", "1.5")."""
    if d is None:
        return None
    return format(Decimal(d).normalize(), "f")


def mstr(d):
    return None if d is None else str(Decimal(d).quantize(Decimal("0.01")))


# ---------------------------------------------------------------- items ------------------------------

def item_clause(p):
    if p.center_wide:
        return true()
    ids = sorted(p.visible_department_ids)
    return or_(InventoryItem.department_id.is_(None), InventoryItem.department_id.in_(ids or [-1]))


def item_json(i):
    return {"id": i.id, "name": i.name, "category": i.category, "sku": i.sku, "barcode": i.barcode, "unit": i.unit,
            "cost": mstr(i.cost), "selling_price": mstr(i.selling_price),
            "low_stock_threshold": qstr(i.low_stock_threshold), "supplier": i.supplier,
            "is_medication": i.is_medication, "department_id": i.department_id, "is_active": i.is_active,
            "notes": i.notes, "version": i.version, "created_at": iso(i.created_at), "updated_at": iso(i.updated_at)}


def get_item(p, item_id, lock=False):
    stmt = select(InventoryItem).where(InventoryItem.id == item_id, p.tenant(InventoryItem), InventoryItem.live(),
                                       item_clause(p))
    if lock:
        stmt = stmt.with_for_update(key_share=True)  # FOR NO KEY UPDATE: serializes stock ops per item
    item = db.session.execute(stmt).scalar_one_or_none()
    if item is None:
        raise NotFound("Item not found")
    return item


def list_items_stmt(p, q=None, category=None, is_medication=None, department_id=None, active=None,
                    include_center=False):
    stmt = select(InventoryItem).where(p.tenant(InventoryItem), InventoryItem.live(), item_clause(p))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(InventoryItem.name).like(like), func.lower(InventoryItem.sku) == q.lower(),
                              InventoryItem.barcode == q, func.lower(InventoryItem.category).like(like)))
    if category:
        stmt = stmt.where(InventoryItem.category == category)
    if is_medication is not None:
        stmt = stmt.where(InventoryItem.is_medication.is_(is_medication))
    if department_id:
        own = InventoryItem.department_id == department_id
        stmt = stmt.where(or_(own, InventoryItem.department_id.is_(None)) if include_center else own)
    if active is not None:
        stmt = stmt.where(InventoryItem.is_active.is_(active))
    return stmt.order_by(InventoryItem.name, InventoryItem.id)


def _check_owner(p, department_id, creating):
    if department_id is None:
        if not p.center_wide:
            if creating:
                raise ValidationError("Invalid input", details={"department_id": "is required"})
            raise Forbidden("Only center-wide staff can edit center-wide items.")
        return
    if not (p.center_wide or p.sees_department(department_id)):
        raise NotFound("Department not found")


def _check_codes(p, item_id, sku, barcode):
    if barcode:
        hit = db.session.execute(select(InventoryItem.id).where(
            p.tenant(InventoryItem), InventoryItem.barcode == barcode, InventoryItem.id != (item_id or -1))).first()
        if hit:
            raise Conflict("Another item already uses this barcode.", code="barcode_taken")
    if sku:
        hit = db.session.execute(select(InventoryItem.id).where(
            p.tenant(InventoryItem), func.lower(InventoryItem.sku) == sku.lower(),
            InventoryItem.id != (item_id or -1))).first()
        if hit:
            raise Conflict("Another item already uses this SKU.", code="sku_taken")


ITEM_FIELDS = ("name", "category", "sku", "barcode", "unit", "cost", "selling_price", "low_stock_threshold",
               "supplier", "is_medication", "department_id", "is_active", "notes")


def create_item(p, data):
    p.require("inventory.edit")
    dept = data.get("department_id")
    if dept is None and not p.center_wide and "department_id" not in data:
        visible = sorted(p.visible_department_ids)
        dept = visible[0] if len(visible) == 1 else None
    data["department_id"] = dept
    _check_owner(p, dept, creating=True)
    _check_codes(p, None, data.get("sku"), data.get("barcode"))
    item = InventoryItem(health_center_id=p.center_id)
    for k in ITEM_FIELDS:
        if k in data and data[k] is not None:
            setattr(item, k, data[k])
    db.session.add(item)
    db.session.commit()
    return item


def update_item(p, item_id, data):
    item = get_item(p, item_id)
    p.require("inventory.edit")
    _check_owner(p, item.department_id, creating=False)
    check_version(item, data.get("version"))
    if "department_id" in data and data["department_id"] != item.department_id:
        _check_owner(p, data["department_id"], creating=False)
    _check_codes(p, item.id, data.get("sku", item.sku), data.get("barcode", item.barcode))
    for k in ITEM_FIELDS:
        if k in data:
            if k in ("name", "is_medication", "is_active") and data[k] is None:
                continue
            setattr(item, k, data[k])
    db.session.commit()
    return item


def delete_item(p, item_id):
    item = get_item(p, item_id)
    p.require("inventory.delete")
    _check_owner(p, item.department_id, creating=False)
    used = db.session.execute(select(StockMovement.id).where(p.tenant(StockMovement), StockMovement.item_id == item.id)
                              .limit(1)).first()
    if used:
        raise Conflict("This item has stock history; deactivate it instead.", code="item_in_use")
    return deletion.stage(p, item, "inventory_item", item.name)


def lookup(p, code):
    """Exact barcode match, then case-insensitive SKU match (USB scanners type the code + Enter)."""
    code = (code or "").strip()
    if not code:
        raise ValidationError("Invalid input", details={"code": "is required"})
    base = select(InventoryItem).where(p.tenant(InventoryItem), InventoryItem.live(), item_clause(p))
    item = db.session.execute(base.where(InventoryItem.barcode == code)).scalar_one_or_none()
    if item is None:
        item = db.session.execute(base.where(func.lower(InventoryItem.sku) == code.lower())).scalar_one_or_none()
    if item is None:
        raise NotFound("No item matches this code")
    return item


# ---------------------------------------------------------------- locations --------------------------

def location_clause(p, mode="view"):
    """SQL filter over InventoryLocation for the principal (mode: view | manage)."""
    clinics = sorted(p.clinic_ids) or [-1]
    depts = sorted(p.managed_department_ids if mode == "manage" else p.visible_department_ids) or [-1]
    conds = [(InventoryLocation.kind == "clinic") & InventoryLocation.clinic_id.in_(clinics),
             (InventoryLocation.kind == "department_pool") & InventoryLocation.department_id.in_(depts)]
    if p.center_wide:
        conds.append(InventoryLocation.kind == "center_pool")
    return or_(*conds)


def can_location(p, loc, mode="view"):
    if loc.kind == "clinic":
        return p.can_clinic(loc.clinic_id)
    if loc.kind == "department_pool":
        return p.can_department(loc.department_id) if mode == "manage" else p.sees_department(loc.department_id)
    return p.center_wide


def get_location(p, location_id, mode="view", lock=False):
    """mode: view | draw | manage. Not visible -> 404; visible but not manageable -> 403."""
    loc = db.session.execute(select(InventoryLocation).where(InventoryLocation.id == location_id,
                                                             p.tenant(InventoryLocation))).scalar_one_or_none()
    if loc is None or not can_location(p, loc, "view"):
        raise NotFound("Location not found")
    if mode == "manage" and not can_location(p, loc, "manage"):
        raise Forbidden("You cannot manage stock at this location.")
    return loc


def ensure_locations(p):
    """Create (idempotently) location rows for every clinic/department/center pool in scope."""
    rows = [{"health_center_id": p.center_id, "kind": "clinic", "clinic_id": c, "department_id": d}
            for c, d in sorted(p.clinic_department.items())]
    depts = sorted(p.visible_department_ids)
    rows += [{"health_center_id": p.center_id, "kind": "department_pool", "clinic_id": None, "department_id": d}
             for d in depts]
    if p.center_wide:
        rows.append({"health_center_id": p.center_id, "kind": "center_pool", "clinic_id": None,
                     "department_id": None})
    for r in rows:
        db.session.execute(pg_insert(InventoryLocation).values(**r).on_conflict_do_nothing())
    db.session.commit()


def clinic_location(p, clinic_id):
    """Location row of a clinic in scope (created on demand)."""
    if not p.can_clinic(clinic_id):
        raise NotFound("Clinic not found")
    dept = p.clinic_department[clinic_id]
    db.session.execute(pg_insert(InventoryLocation).values(
        health_center_id=p.center_id, kind="clinic", clinic_id=clinic_id, department_id=dept)
        .on_conflict_do_nothing())
    return db.session.execute(select(InventoryLocation).where(
        p.tenant(InventoryLocation), InventoryLocation.kind == "clinic", InventoryLocation.clinic_id == clinic_id)
    ).scalar_one()


def location_names(center_id, locs):
    clinic_ids = {l.clinic_id for l in locs if l.clinic_id}
    dept_ids = {l.department_id for l in locs if l.department_id}
    cn = dict(db.session.execute(select(Clinic.id, Clinic.name).where(
        Clinic.health_center_id == center_id, Clinic.id.in_(clinic_ids or [-1]))).all())
    dn = dict(db.session.execute(select(Department.id, Department.name).where(
        Department.health_center_id == center_id, Department.id.in_(dept_ids or [-1]))).all())
    return cn, dn


def location_json(l, cn, dn, p=None):
    if l.kind == "clinic":
        name = cn.get(l.clinic_id, "")
    elif l.kind == "department_pool":
        name = dn.get(l.department_id, "")
    else:
        name = "Center"
    out = {"id": l.id, "kind": l.kind, "clinic_id": l.clinic_id, "department_id": l.department_id, "name": name,
           "department_name": dn.get(l.department_id) if l.department_id else None}
    if p is not None:
        out["can_manage"] = can_location(p, l, "manage")
    return out


def list_locations(p):
    ensure_locations(p)
    locs = db.session.execute(select(InventoryLocation).where(p.tenant(InventoryLocation), location_clause(p))
                              .order_by(InventoryLocation.kind, InventoryLocation.department_id,
                                        InventoryLocation.clinic_id)).scalars().all()
    cn, dn = location_names(p.center_id, locs)
    return [location_json(l, cn, dn, p) for l in locs]


def visible_location_ids(p, mode="view"):
    return [r for r in db.session.execute(select(InventoryLocation.id).where(
        p.tenant(InventoryLocation), location_clause(p, mode))).scalars()]


def lot_json(lot):
    return {"id": lot.id, "item_id": lot.item_id, "location_id": lot.location_id, "lot_code": lot.lot_code,
            "expiry_date": iso(lot.expiry_date), "quantity": qstr(lot.quantity), "unit_cost": mstr(lot.unit_cost),
            "received_at": iso(lot.received_at)}


def item_stock_by_location(p, item_id):
    """[{location_id, quantity}] for visible locations holding the item."""
    rows = db.session.execute(select(StockLot.location_id, func.sum(StockLot.quantity)).where(
        p.tenant(StockLot), StockLot.item_id == item_id, StockLot.location_id.in_(visible_location_ids(p) or [-1]))
        .group_by(StockLot.location_id)).all()
    return [{"location_id": lid, "quantity": qstr(q)} for lid, q in rows]



def meta(p):
    """Form choices for the UI: locations, categories, units, departments, capabilities."""
    from .models import MOVEMENT_TYPES

    def distinct_of(col):
        return db.session.execute(select(col).distinct().where(
            p.tenant(InventoryItem), InventoryItem.live(), item_clause(p), col.is_not(None)).order_by(col)
        ).scalars().all()
    depts = db.session.execute(select(Department.id, Department.name).where(
        p.tenant(Department), Department.id.in_(sorted(p.visible_department_ids) or [-1])).order_by(Department.name)
    ).all()
    return {"locations": list_locations(p), "categories": distinct_of(InventoryItem.category),
            "units": distinct_of(InventoryItem.unit), "departments": [{"id": i, "name": n} for i, n in depts],
            "movement_types": list(MOVEMENT_TYPES), "can_edit": p.has("inventory.edit"),
            "can_delete": p.has("inventory.delete"), "can_edit_center_items": p.center_wide}
