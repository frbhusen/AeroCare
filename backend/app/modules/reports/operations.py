"""Inventory, laboratory and radiology reports.

Inventory reuses the inventory module's visibility rules (location_clause / item_clause and the
stock aggregate statement). Laboratory / radiology use the modules' own requester-side and
lab/radiology-side clauses, so a report never shows a request its caller could not open."""
from datetime import timedelta

from sqlalchemy import and_, extract, func, or_, select

from backend.app.core.errors import NotFound
from backend.app.core.timeutil import iso, local_today
from backend.app.extensions import db
from backend.app.modules.inventory.models import (MOVEMENT_TYPES, InventoryItem, InventoryLocation, StockLot,
                                                  StockMovement)
from backend.app.modules.inventory.reports import _stock_stmt
from backend.app.modules.inventory.service import item_clause, location_clause, location_names
from backend.app.modules.laboratory.models import LabRequest, LabRequestItem
from backend.app.modules.laboratory.service import lab_side_clause, requester_clause as lab_requester_clause
from backend.app.modules.radiology.models import RadiologyStudy
from backend.app.modules.radiology.service import (radiology_side_clause,
                                                   requester_clause as rad_requester_clause)
from .common import (bounded, col, group_col, group_label, hours, local_day, local_month, qty_str, rate,
                     sum_totals)


# ---- inventory ------------------------------------------------------------------------
def _locations(p, f):
    """{location_id: label} of visible locations matching the filters."""
    L = InventoryLocation
    stmt = select(L).where(p.tenant(L), location_clause(p))
    if f.location_id:
        stmt = stmt.where(L.id == f.location_id)
    if f.clinic_id:
        stmt = stmt.where(L.kind == "clinic", L.clinic_id == f.clinic_id)
    elif f.department_id:
        stmt = stmt.where(L.department_id == f.department_id)
    locs = db.session.execute(stmt).scalars().all()
    if f.location_id and not locs:
        raise NotFound("Location not found")
    cn, dn = location_names(p.center_id, locs)

    def name(loc):
        if loc.kind == "clinic":
            return cn.get(loc.clinic_id) or f"#{loc.clinic_id}"
        if loc.kind == "department_pool":
            return f"{dn.get(loc.department_id) or loc.department_id} (pool)"
        return "Center pool"
    return {loc.id: name(loc) for loc in locs}


def _yes(v):
    return "yes" if v else "no"


def inventory(p, f):
    locs = _locations(p, f)
    loc_ids = sorted(locs) or [-1]
    if f.view in ("stock", "low_stock"):
        stmt, qty = _stock_stmt(p, loc_ids)
        if f.view == "stock":
            stmt = stmt.having(qty > 0)
        else:
            stmt = stmt.where(InventoryItem.low_stock_threshold.is_not(None),
                              InventoryItem.is_active.is_(True)).having(
                qty <= func.max(InventoryItem.low_stock_threshold))
        data, truncated = bounded(stmt.order_by(InventoryItem.name, StockLot.location_id))
        rows = []
        for item, loc_id, q, usable, nearest in data:
            th = item.low_stock_threshold
            rows.append({"key": item.id, "group": item.name, "category": item.category, "unit": item.unit,
                         "location": locs.get(loc_id), "quantity": qty_str(q), "usable_quantity": qty_str(usable),
                         "expired_quantity": qty_str(q - usable), "nearest_expiry": iso(nearest),
                         "threshold": qty_str(th), "low": _yes(th is not None and q <= th)})
        columns = [col("group", "text", "item"), col("category", "text"), col("unit", "text"),
                   col("location", "text"), col("quantity", "number"), col("usable_quantity", "number"),
                   col("expired_quantity", "number"), col("nearest_expiry", "date"), col("threshold", "number"),
                   col("low", "bool")]
        return {"columns": columns, "rows": rows, "totals": None, "truncated": truncated,
                "notes": ["Current stock (date range not applied)."]}
    if f.view == "expiry":
        today = local_today()
        limit = today + timedelta(days=f.days)
        stmt = (select(StockLot, InventoryItem)
                .join(InventoryItem, and_(InventoryItem.id == StockLot.item_id,
                                          InventoryItem.health_center_id == StockLot.health_center_id))
                .where(p.tenant(StockLot), InventoryItem.live(), item_clause(p), StockLot.location_id.in_(loc_ids),
                       StockLot.quantity > 0, StockLot.expiry_date.is_not(None), StockLot.expiry_date <= limit)
                .order_by(StockLot.expiry_date, StockLot.id))
        data, truncated = bounded(stmt)
        rows = [{"key": lot.id, "group": item.name, "location": locs.get(lot.location_id), "lot_code": lot.lot_code,
                 "expiry_date": iso(lot.expiry_date), "days_left": (lot.expiry_date - today).days,
                 "quantity": qty_str(lot.quantity), "status": "expired" if lot.expiry_date < today else "expiring"}
                for lot, item in data]
        columns = [col("group", "text", "item"), col("location", "text"), col("lot_code", "text"),
                   col("expiry_date", "date"), col("days_left"), col("quantity", "number"), col("status", "text")]
        return {"columns": columns, "rows": rows, "totals": None, "truncated": truncated,
                "notes": [f"Lots expired or expiring within {f.days} days (date range not applied)."]}
    # movements: per item, summed by movement type within the period
    M = StockMovement
    type_keys = {"receive": "received", "use": "used", "dispense": "dispensed", "sale": "sold",
                 "transfer_in": "transferred_in", "transfer_out": "transferred_out", "adjust": "adjusted",
                 "write_off": "written_off"}
    cols = [func.coalesce(func.sum(M.quantity).filter(M.type == t), 0) for t in MOVEMENT_TYPES]
    stmt = (select(InventoryItem.id, InventoryItem.name, InventoryItem.unit, func.count(M.id), *cols,
                   func.sum(M.quantity))
            .join(InventoryItem, and_(InventoryItem.id == M.item_id,
                                      InventoryItem.health_center_id == M.health_center_id))
            .where(p.tenant(M), item_clause(p), M.location_id.in_(loc_ids), M.created_at >= f.start,
                   M.created_at < f.end)
            .group_by(InventoryItem.id, InventoryItem.name, InventoryItem.unit).order_by(InventoryItem.name))
    data, truncated = bounded(stmt)
    rows = []
    for r in data:
        row = {"key": r[0], "group": r[1], "unit": r[2], "movements": r[3]}
        for i, t in enumerate(MOVEMENT_TYPES):
            row[type_keys[t]] = qty_str(r[4 + i])
        row["net_change"] = qty_str(r[4 + len(MOVEMENT_TYPES)])
        rows.append(row)
    columns = ([col("group", "text", "item"), col("unit", "text"), col("movements")]
               + [col(type_keys[t], "number") for t in MOVEMENT_TYPES] + [col("net_change", "number")])
    return {"columns": columns, "rows": rows, "totals": None, "truncated": truncated,
            "notes": ["Signed quantities (outgoing movements are negative)."]}


# ---- laboratory / radiology ------------------------------------------------------------
def _request_report(p, f, model, statuses, scope, conds, clinic_col, done_status, done_col, extra_groups=None):
    g = f.group_by
    gexprs = {"status": model.status, "clinic": clinic_col, "day": local_day(model.requested_at),
              "month": local_month(model.requested_at), **(extra_groups or {})}
    gexpr = gexprs[g]
    tat = func.avg(extract("epoch", done_col - model.requested_at)).filter(model.status == done_status)
    metrics = ([func.count(model.id)] + [func.count(model.id).filter(model.status == s) for s in statuses]
               + [func.count(model.id).filter(model.priority == "urgent"), tat])
    where = [p.tenant(model), model.live(), scope, model.requested_at >= f.start, model.requested_at < f.end,
             *conds]
    data, truncated = bounded(select(gexpr, *metrics).where(*where).group_by(gexpr).order_by(gexpr))
    lbl = group_label(p, g, [r[0] for r in data])
    rows = []
    for r in data:
        row = {"key": r[0], "group": lbl(r[0]), "total": r[1]}
        row.update({s: r[2 + i] for i, s in enumerate(statuses)})
        row["urgent"] = r[2 + len(statuses)]
        row["avg_turnaround_hours"] = hours(r[3 + len(statuses)])
        rows.append(row)
    if g == "clinic":
        rows.sort(key=lambda x: str(x["group"]).lower())
    columns = ([group_col(g), col("total")] + [col(s) for s in statuses]
               + [col("urgent"), col("avg_turnaround_hours", "number")])
    totals = sum_totals(columns, rows)
    totals.pop("avg_turnaround_hours", None)
    totals["avg_turnaround_hours"] = hours(db.session.execute(select(tat).where(*where)).scalar())
    return {"columns": columns, "rows": rows, "totals": totals, "truncated": truncated}


def _lab_filters(f):
    R = LabRequest
    out = []
    if f.department_id:
        out.append(or_(R.requesting_department_id == f.department_id, R.lab_department_id == f.department_id))
    if f.clinic_id:
        out.append(or_(R.requesting_clinic_id == f.clinic_id, R.lab_clinic_id == f.clinic_id))
    if f.doctor_id:
        out.append(R.author_user_id == f.doctor_id)
    return out


def laboratory(p, f):
    R, I = LabRequest, LabRequestItem
    scope = or_(lab_requester_clause(p), lab_side_clause(p))
    conds = _lab_filters(f)
    if f.group_by != "test":
        out = _request_report(p, f, R, ("requested", "in_progress", "completed", "cancelled"), scope, conds,
                              R.requesting_clinic_id, "completed", R.finalized_at)
        out["notes"] = ["Requests made or processed in your scope, by request date. Turnaround = request to "
                        "finalized result. Clinic = requesting clinic."]
        return out
    abnormal = I.abnormal_flag.in_(("L", "H", "A"))
    done = R.status == "completed"
    stmt = (select(I.test_code, I.test_name, func.count(I.id), func.count(I.id).filter(done, I.result_value.is_not(None)),
                   func.count(I.id).filter(done, abnormal))
            .join(R, and_(R.id == I.request_id, R.health_center_id == I.health_center_id))
            .where(p.tenant(I), p.tenant(R), R.live(), scope, R.status != "cancelled", R.requested_at >= f.start,
                   R.requested_at < f.end, *conds)
            .group_by(I.test_code, I.test_name).order_by(func.count(I.id).desc(), I.test_code))
    data, truncated = bounded(stmt)
    rows = [{"key": code, "test_code": code, "group": name, "ordered": n, "resulted": res, "abnormal": ab,
             "abnormal_rate": rate(ab, res)} for code, name, n, res, ab in data]
    columns = [col("test_code", "text"), col("group", "text", "test"), col("ordered"), col("resulted"),
               col("abnormal"), col("abnormal_rate", "percent")]
    totals = sum_totals(columns, rows, skip=("group", "test_code"))
    totals["abnormal_rate"] = rate(totals["abnormal"], totals["resulted"])
    return {"columns": columns, "rows": rows, "totals": totals, "truncated": truncated,
            "notes": ["Tests of non-cancelled requests; abnormal = L/H/A flags on finalized results."]}


def radiology(p, f):
    S = RadiologyStudy
    scope = or_(rad_requester_clause(p), radiology_side_clause(p))
    conds = []
    if f.department_id:
        conds.append(or_(S.requesting_department_id == f.department_id, S.radiology_department_id == f.department_id))
    if f.clinic_id:
        conds.append(or_(S.requesting_clinic_id == f.clinic_id, S.radiology_clinic_id == f.clinic_id))
    if f.doctor_id:
        conds.append(S.author_user_id == f.doctor_id)
    out = _request_report(p, f, S, ("requested", "scheduled", "in_progress", "reported", "finalized", "cancelled"),
                          scope, conds, S.requesting_clinic_id, "finalized", S.finalized_at,
                          extra_groups={"exam_type": S.exam_type})
    out["notes"] = ["Studies requested or performed in your scope, by request date. Turnaround = request to "
                    "finalized report. Clinic = requesting clinic."]
    return out
