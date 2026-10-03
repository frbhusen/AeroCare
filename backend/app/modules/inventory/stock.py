"""Stock operations: receive, consume (FEFO), adjust, write-off, transfer.

Concurrency: every mutation first locks the item row (SELECT ... FOR NO KEY UPDATE, items in id
order) and then the affected lots (SELECT ... FOR UPDATE). Balances are read only after the locks
are held, so concurrent decrements serialize and can never drive a lot below zero (the CHECK
constraint `quantity >= 0` is the final backstop).

Callers outside this module (pharmacy) use `lock_items()` + `decrement()` inside their own
transaction and commit themselves (low-stock notifications are added to the same transaction).
"""
from decimal import Decimal

from sqlalchemy import func, select

from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.timeutil import local_today
from backend.app.extensions import db
from backend.app.services.notifications import notify, recipients_for
from .models import InventoryItem, InventoryLocation, StockLot, StockMovement, StockTransfer, StockTransferItem
from .service import get_item, get_location, qstr

ZERO = Decimal("0")


# ---------------------------------------------------------------- primitives -------------------------

def lock_items(p, item_ids):
    """Lock (FOR NO KEY UPDATE) visible items in id order; returns {id: item}. 404 if any missing."""
    out = {}
    for iid in sorted(set(item_ids)):
        out[iid] = get_item(p, iid, lock=True)
    return out


def location_total(center_id, item_id, location_id):
    return db.session.execute(select(func.coalesce(func.sum(StockLot.quantity), 0)).where(
        StockLot.health_center_id == center_id, StockLot.item_id == item_id, StockLot.location_id == location_id)
    ).scalar_one()


def _movement(p, item, loc, lot, type_, qty, balance_after, reason=None, reference_type=None,
              reference_id=None, unit_cost=None):
    m = StockMovement(health_center_id=p.center_id, item_id=item.id, location_id=loc.id,
                      lot_id=lot.id if lot is not None else None, type=type_, quantity=qty,
                      balance_after=balance_after, reason=reason, reference_type=reference_type,
                      reference_id=reference_id,
                      unit_cost=unit_cost if unit_cost is not None else (lot.unit_cost if lot is not None else None))
    m.set_author(p.user)
    db.session.add(m)
    return m


def notify_low_stock(p, item, loc, before, after):
    """Notify once when the location total crosses to <= threshold (spec §76)."""
    th = item.low_stock_threshold
    if th is None or not (before > th >= after):
        return
    title = f"Low stock: {item.name} ({qstr(after)} left)"
    link = f"/inventory/stock?item_id={item.id}&location_id={loc.id}"
    if loc.kind == "clinic":
        notify(p.center_id, "low_stock", title, link=link, clinic_id=loc.clinic_id)
    elif loc.kind == "department_pool":
        notify(p.center_id, "low_stock", title, link=link, department_id=loc.department_id)
    else:
        notify(p.center_id, "low_stock", title, link=link, user_ids=recipients_for(p.center_id))


def add_to_lot(p, item, loc, qty, lot_code=None, expiry_date=None, unit_cost=None):
    """Increase stock (merging into an identical lot: same code + expiry). Item must be locked."""
    lot = db.session.execute(select(StockLot).where(
        StockLot.health_center_id == p.center_id, StockLot.item_id == item.id, StockLot.location_id == loc.id,
        StockLot.lot_code.is_not_distinct_from(lot_code), StockLot.expiry_date.is_not_distinct_from(expiry_date))
        .order_by(StockLot.id).limit(1).with_for_update()).scalar_one_or_none()
    if lot is None:
        lot = StockLot(health_center_id=p.center_id, item_id=item.id, location_id=loc.id, lot_code=lot_code,
                       expiry_date=expiry_date, quantity=qty, unit_cost=unit_cost)
        db.session.add(lot)
    else:
        if unit_cost is not None:
            if lot.unit_cost is None or lot.quantity + qty == 0:
                lot.unit_cost = unit_cost
            else:  # weighted average cost
                lot.unit_cost = ((lot.unit_cost * lot.quantity + unit_cost * qty) / (lot.quantity + qty)
                                 ).quantize(Decimal("0.01"))
        lot.quantity = lot.quantity + qty
    db.session.flush()
    return lot


def decrement(p, item, loc, qty, type_, *, lot_id=None, allow_expired=False, reason=None, reference_type=None,
              reference_id=None):
    """Remove `qty` of a locked item from a location. FEFO across non-expired lots (expiry
    ascending, undated last) unless `lot_id` is given. Returns [(lot, taken)].
    Raises 409 insufficient_stock / 422 lot_expired."""
    if qty <= 0:
        raise ValidationError("Invalid input", details={"quantity": "must be > 0"})
    lots = db.session.execute(select(StockLot).where(
        StockLot.health_center_id == p.center_id, StockLot.item_id == item.id, StockLot.location_id == loc.id)
        .order_by(StockLot.id).with_for_update()).scalars().all()
    before = sum((l.quantity for l in lots), ZERO)
    today = local_today()
    if lot_id is not None:
        cand = [l for l in lots if l.id == lot_id]
        if not cand:
            raise NotFound("Lot not found")
        if not allow_expired and cand[0].expiry_date is not None and cand[0].expiry_date < today:
            raise ValidationError("This lot is expired.", code="lot_expired", details={"lot_id": lot_id})
    else:
        cand = [l for l in lots if l.quantity > 0 and (allow_expired or l.expiry_date is None
                                                       or l.expiry_date >= today)]
        cand.sort(key=lambda l: (l.expiry_date is None, l.expiry_date or today, l.id))
    available = sum((l.quantity for l in cand), ZERO)
    if available < qty:
        raise Conflict("Not enough stock at this location.", code="insufficient_stock",
                       details={"item_id": item.id, "available": qstr(available), "requested": qstr(qty)})
    taken, remaining, balance = [], qty, before
    for lot in cand:
        if remaining <= 0:
            break
        t = min(lot.quantity, remaining)
        if t <= 0:
            continue
        lot.quantity = lot.quantity - t
        remaining -= t
        balance -= t
        _movement(p, item, loc, lot, type_, -t, balance, reason, reference_type, reference_id)
        taken.append((lot, t))
    db.session.flush()
    notify_low_stock(p, item, loc, before, balance)
    return taken


def taken_json(taken):
    return [{"lot_id": lot.id, "lot_code": lot.lot_code,
             "expiry_date": lot.expiry_date.isoformat() if lot.expiry_date else None, "quantity": qstr(t)}
            for lot, t in taken]


# ---------------------------------------------------------------- operations -------------------------

def receive(p, data):
    p.require("inventory.edit")
    loc = get_location(p, data["location_id"], "manage")
    item = lock_items(p, [data["item_id"]])[data["item_id"]]
    if not item.is_active:
        raise ValidationError("This item is inactive.", code="item_inactive")
    qty = data["quantity"]
    before = location_total(p.center_id, item.id, loc.id)
    cost = data.get("unit_cost")
    if cost is None:
        cost = item.cost
    lot = add_to_lot(p, item, loc, qty, data.get("lot_code"), data.get("expiry_date"), cost)
    _movement(p, item, loc, lot, "receive", qty, before + qty, data.get("reason"), unit_cost=cost)
    db.session.commit()
    return {"lot_id": lot.id, "item_id": item.id, "location_id": loc.id, "quantity": qstr(before + qty)}


def use(p, data):
    p.require("inventory.edit")
    loc = get_location(p, data["location_id"], "view")
    item = lock_items(p, [data["item_id"]])[data["item_id"]]
    taken = decrement(p, item, loc, data["quantity"], "use", lot_id=data.get("lot_id"), reason=data.get("reason"),
                      reference_type=data.get("reference_type"), reference_id=data.get("reference_id"))
    db.session.commit()
    return {"item_id": item.id, "location_id": loc.id, "lots": taken_json(taken),
            "quantity": qstr(location_total(p.center_id, item.id, loc.id))}


def adjust(p, data):
    """Stock count correction. delta > 0 adds to `lot_id` (or an undated/no-code lot); delta < 0
    removes (FEFO incl. expired lots, or the given lot)."""
    p.require("inventory.edit")
    loc = get_location(p, data["location_id"], "manage")
    item = lock_items(p, [data["item_id"]])[data["item_id"]]
    delta = data["delta"]
    if delta == 0:
        raise ValidationError("Invalid input", details={"delta": "must not be 0"})
    if delta < 0:
        taken = decrement(p, item, loc, -delta, "adjust", lot_id=data.get("lot_id"), allow_expired=True,
                          reason=data["reason"])
        lots = taken_json(taken)
    else:
        before = location_total(p.center_id, item.id, loc.id)
        if data.get("lot_id"):
            lot = db.session.execute(select(StockLot).where(
                StockLot.health_center_id == p.center_id, StockLot.id == data["lot_id"],
                StockLot.item_id == item.id, StockLot.location_id == loc.id).with_for_update()).scalar_one_or_none()
            if lot is None:
                raise NotFound("Lot not found")
            lot.quantity = lot.quantity + delta
        else:
            lot = add_to_lot(p, item, loc, delta, None, None, item.cost)
        _movement(p, item, loc, lot, "adjust", delta, before + delta, data["reason"])
        lots = [{"lot_id": lot.id, "quantity": qstr(delta)}]
    db.session.commit()
    return {"item_id": item.id, "location_id": loc.id, "lots": lots,
            "quantity": qstr(location_total(p.center_id, item.id, loc.id))}


def write_off(p, data):
    """Write off one lot (`lot_id`, optional `quantity`, default all) or every expired lot at the
    location (optionally only for `item_id`)."""
    p.require("inventory.edit")
    loc = get_location(p, data["location_id"], "manage")
    reason = data.get("reason") or "expired"
    if data.get("lot_id"):
        lot = db.session.execute(select(StockLot).where(
            StockLot.health_center_id == p.center_id, StockLot.id == data["lot_id"], StockLot.location_id == loc.id)
        ).scalar_one_or_none()
        if lot is None:
            raise NotFound("Lot not found")
        item = lock_items(p, [lot.item_id])[lot.item_id]
        db.session.refresh(lot, with_for_update=True)
        qty = data.get("quantity") or lot.quantity
        if qty <= 0:
            raise ValidationError("This lot is empty.", code="lot_empty")
        taken = decrement(p, item, loc, qty, "write_off", lot_id=lot.id, allow_expired=True, reason=reason)
        db.session.commit()
        return {"written_off": taken_json(taken)}
    today = local_today()
    stmt = select(StockLot.item_id).where(StockLot.health_center_id == p.center_id, StockLot.location_id == loc.id,
                                          StockLot.quantity > 0, StockLot.expiry_date < today)
    if data.get("item_id"):
        stmt = stmt.where(StockLot.item_id == data["item_id"])
    item_ids = set(db.session.execute(stmt).scalars())
    items = lock_items(p, item_ids) if item_ids else {}
    out = []
    for iid, item in items.items():
        lots = db.session.execute(select(StockLot).where(
            StockLot.health_center_id == p.center_id, StockLot.item_id == iid, StockLot.location_id == loc.id,
            StockLot.quantity > 0, StockLot.expiry_date < today).order_by(StockLot.id).with_for_update()
        ).scalars().all()
        for lot in lots:
            out += taken_json(decrement(p, item, loc, lot.quantity, "write_off", lot_id=lot.id, allow_expired=True,
                                        reason=reason))
    db.session.commit()
    return {"written_off": out}


def transfer(p, data):
    """Atomic transfer of one or more items between two locations (FEFO or explicit lots).
    Lot code, expiry and unit cost travel with the stock."""
    p.require("inventory.edit")
    if data["from_location_id"] == data["to_location_id"]:
        raise ValidationError("Invalid input", details={"to_location_id": "must differ from the source"})
    src = get_location(p, data["from_location_id"], "view")
    dst = get_location(p, data["to_location_id"], "view")
    lines = data["items"]
    items = lock_items(p, [l["item_id"] for l in lines])
    tr = StockTransfer(health_center_id=p.center_id, from_location_id=src.id, to_location_id=dst.id,
                       status="completed", notes=data.get("notes"))
    tr.set_author(p.user)
    db.session.add(tr)
    db.session.flush()
    for line in lines:
        item = items[line["item_id"]]
        taken = decrement(p, item, src, line["quantity"], "transfer_out", lot_id=line.get("lot_id"),
                          reason=data.get("notes"), reference_type="transfer", reference_id=tr.id)
        balance = location_total(p.center_id, item.id, dst.id)
        for lot, t in taken:
            new_lot = add_to_lot(p, item, dst, t, lot.lot_code, lot.expiry_date, lot.unit_cost)
            balance += t
            _movement(p, item, dst, new_lot, "transfer_in", t, balance, data.get("notes"), "transfer", tr.id)
        db.session.add(StockTransferItem(health_center_id=p.center_id, transfer_id=tr.id, item_id=item.id,
                                         quantity=line["quantity"], lots=taken_json(taken)))
    db.session.commit()
    return tr
