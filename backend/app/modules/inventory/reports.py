"""Read-side inventory views (spec §60): stock levels, low stock, expiry, movements, transfers.
All queries are restricted to locations visible to the principal."""
from datetime import timedelta

from sqlalchemy import and_, case, func, or_, select

from backend.app.core.api import page_params
from backend.app.core.errors import NotFound
from backend.app.core.timeutil import iso, local_day_bounds, local_today
from backend.app.extensions import db
from .models import InventoryItem, InventoryLocation, StockLot, StockMovement, StockTransfer, StockTransferItem
from .service import item_clause, location_clause, location_json, location_names, lot_json, mstr, qstr


def _page(stmt, serialize):
    page, per_page = page_params(50)
    total = db.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    return {"items": [serialize(r) for r in rows], "page": page, "per_page": per_page, "total": total}


def _loc_filter(p, location_id):
    """Visible location ids (optionally a single one; 404 if not visible)."""
    ids = set(db.session.execute(select(InventoryLocation.id).where(p.tenant(InventoryLocation),
                                                                    location_clause(p))).scalars())
    if location_id:
        if location_id not in ids:
            raise NotFound("Location not found")
        return [location_id]
    return sorted(ids) or [-1]


def _item_brief(i):
    return {"id": i.id, "name": i.name, "category": i.category, "sku": i.sku, "barcode": i.barcode, "unit": i.unit,
            "is_medication": i.is_medication, "selling_price": mstr(i.selling_price),
            "low_stock_threshold": qstr(i.low_stock_threshold)}


def _stock_stmt(p, loc_ids, item_id=None, q=None, category=None, is_medication=None):
    today = local_today()
    qty = func.sum(StockLot.quantity)
    usable = func.sum(case((or_(StockLot.expiry_date.is_(None), StockLot.expiry_date >= today), StockLot.quantity),
                           else_=0))
    nearest = func.min(case((StockLot.quantity > 0, StockLot.expiry_date)))
    stmt = (select(InventoryItem, StockLot.location_id, qty.label("qty"), usable.label("usable"),
                   nearest.label("nearest"))
            .join(StockLot, and_(StockLot.item_id == InventoryItem.id,
                                 StockLot.health_center_id == InventoryItem.health_center_id))
            .where(p.tenant(InventoryItem), InventoryItem.live(), item_clause(p), StockLot.location_id.in_(loc_ids))
            .group_by(InventoryItem.id, StockLot.location_id))
    if item_id:
        stmt = stmt.where(InventoryItem.id == item_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(InventoryItem.name).like(like), InventoryItem.barcode == q,
                              func.lower(InventoryItem.sku) == q.lower()))
    if category:
        stmt = stmt.where(InventoryItem.category == category)
    if is_medication is not None:
        stmt = stmt.where(InventoryItem.is_medication.is_(is_medication))
    return stmt, qty


def _stock_row(r):
    item, loc_id, qty, usable, nearest = r
    th = item.low_stock_threshold
    return {"item": _item_brief(item), "location_id": loc_id, "quantity": qstr(qty), "usable_quantity": qstr(usable),
            "expired_quantity": qstr(qty - usable), "nearest_expiry": iso(nearest),
            "low": th is not None and qty <= th}


def stock_levels(p, location_id=None, item_id=None, q=None, category=None, is_medication=None, include_zero=False):
    stmt, qty = _stock_stmt(p, _loc_filter(p, location_id), item_id, q, category, is_medication)
    if not include_zero:
        stmt = stmt.having(qty > 0)
    return _page(stmt.order_by(InventoryItem.name, StockLot.location_id), _stock_row)


def low_stock(p, location_id=None):
    """(item, location) pairs at or below the item's threshold, among locations that stock the item."""
    stmt, qty = _stock_stmt(p, _loc_filter(p, location_id))
    stmt = stmt.where(InventoryItem.low_stock_threshold.is_not(None), InventoryItem.is_active.is_(True)).having(
        qty <= func.max(InventoryItem.low_stock_threshold))
    return _page(stmt.order_by(InventoryItem.name, StockLot.location_id), _stock_row)


def expiry_report(p, days=30, location_id=None, item_id=None, is_medication=None):
    today = local_today()
    limit = today + timedelta(days=days)
    stmt = (select(StockLot, InventoryItem)
            .join(InventoryItem, and_(InventoryItem.id == StockLot.item_id,
                                      InventoryItem.health_center_id == StockLot.health_center_id))
            .where(p.tenant(StockLot), InventoryItem.live(), item_clause(p),
                   StockLot.location_id.in_(_loc_filter(p, location_id)), StockLot.quantity > 0,
                   StockLot.expiry_date.is_not(None), StockLot.expiry_date <= limit))
    if item_id:
        stmt = stmt.where(StockLot.item_id == item_id)
    if is_medication is not None:
        stmt = stmt.where(InventoryItem.is_medication.is_(is_medication))

    def row(r):
        lot, item = r
        out = lot_json(lot)
        out["item"] = _item_brief(item)
        out["status"] = "expired" if lot.expiry_date < today else "expiring"
        out["days_left"] = (lot.expiry_date - today).days
        return out
    return _page(stmt.order_by(StockLot.expiry_date, StockLot.id), row)


def movement_json(m, item_name=None):
    return {"id": m.id, "item_id": m.item_id, "item_name": item_name, "location_id": m.location_id,
            "lot_id": m.lot_id, "type": m.type, "quantity": qstr(m.quantity), "balance_after": qstr(m.balance_after),
            "unit_cost": mstr(m.unit_cost), "reason": m.reason, "reference_type": m.reference_type,
            "reference_id": m.reference_id, "author_name": m.author_name, "created_at": iso(m.created_at)}


def movements(p, f):
    stmt = (select(StockMovement, InventoryItem.name)
            .join(InventoryItem, and_(InventoryItem.id == StockMovement.item_id,
                                      InventoryItem.health_center_id == StockMovement.health_center_id))
            .where(p.tenant(StockMovement), item_clause(p),
                   StockMovement.location_id.in_(_loc_filter(p, f.get("location_id")))))
    if f.get("item_id"):
        stmt = stmt.where(StockMovement.item_id == f["item_id"])
    if f.get("type"):
        stmt = stmt.where(StockMovement.type == f["type"])
    if f.get("reference_type"):
        stmt = stmt.where(StockMovement.reference_type == f["reference_type"])
    if f.get("reference_id"):
        stmt = stmt.where(StockMovement.reference_id == f["reference_id"])
    if f.get("date_from"):
        stmt = stmt.where(StockMovement.created_at >= local_day_bounds(f["date_from"])[0])
    if f.get("date_to"):
        stmt = stmt.where(StockMovement.created_at < local_day_bounds(f["date_to"])[1])
    return _page(stmt.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()),
                 lambda r: movement_json(r[0], r[1]))


def _transfer_clause(p):
    vis = select(InventoryLocation.id).where(p.tenant(InventoryLocation), location_clause(p))
    return or_(StockTransfer.from_location_id.in_(vis), StockTransfer.to_location_id.in_(vis))


def transfer_json(p, tr, with_items=False):
    locs = db.session.execute(select(InventoryLocation).where(
        p.tenant(InventoryLocation), InventoryLocation.id.in_([tr.from_location_id, tr.to_location_id]))
    ).scalars().all()
    cn, dn = location_names(p.center_id, locs)
    by_id = {l.id: location_json(l, cn, dn) for l in locs}
    out = {"id": tr.id, "from_location": by_id.get(tr.from_location_id), "to_location": by_id.get(tr.to_location_id),
           "status": tr.status, "notes": tr.notes, "author_name": tr.author_name, "created_at": iso(tr.created_at)}
    if with_items:
        rows = db.session.execute(select(StockTransferItem, InventoryItem.name).join(
            InventoryItem, and_(InventoryItem.id == StockTransferItem.item_id,
                                InventoryItem.health_center_id == StockTransferItem.health_center_id))
            .where(p.tenant(StockTransferItem), StockTransferItem.transfer_id == tr.id)
            .order_by(StockTransferItem.id)).all()
        out["items"] = [{"item_id": ti.item_id, "item_name": name, "quantity": qstr(ti.quantity), "lots": ti.lots}
                        for ti, name in rows]
    return out


def list_transfers(p, location_id=None):
    stmt = select(StockTransfer).where(p.tenant(StockTransfer), _transfer_clause(p))
    if location_id:
        stmt = stmt.where(or_(StockTransfer.from_location_id == location_id,
                              StockTransfer.to_location_id == location_id))
    return _page(stmt.order_by(StockTransfer.created_at.desc(), StockTransfer.id.desc()),
                 lambda r: transfer_json(p, r[0]))


def get_transfer(p, transfer_id):
    tr = db.session.execute(select(StockTransfer).where(StockTransfer.id == transfer_id, p.tenant(StockTransfer),
                                                        _transfer_clause(p))).scalar_one_or_none()
    if tr is None:
        raise NotFound("Transfer not found")
    return transfer_json(p, tr, with_items=True)


def lots(p, item_id, location_id=None, include_empty=False):
    stmt = select(StockLot).where(p.tenant(StockLot), StockLot.item_id == item_id,
                                  StockLot.location_id.in_(_loc_filter(p, location_id)))
    if not include_empty:
        stmt = stmt.where(StockLot.quantity > 0)
    rows = db.session.execute(stmt.order_by(StockLot.location_id, StockLot.expiry_date.asc().nulls_last(),
                                            StockLot.id)).scalars().all()
    return [lot_json(l) for l in rows]
