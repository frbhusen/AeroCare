"""/api/v1/inventory — catalog, locations, stock operations and reports."""
from flask import Blueprint, jsonify

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.api import paginate
from backend.app.core.validation import (Bool, Date, Enum, Id, Int, List, Money, Num, Obj, Str, Text, query_args,
                                         request_json, validate)
from backend.app.extensions import db
from . import reports, service, stock
from .models import MOVEMENT_TYPES

bp = Blueprint("inventory", __name__, url_prefix="/inventory")

QTY = dict(min_value=0, max_value=10**9, places=3)


def _qty(required=True):
    return Num(required=required, min_value="0.001", max_value=10**9, places=3)


ITEM_SCHEMA = {
    "name": Str(required=True, max_len=200), "category": Str(max_len=100), "sku": Str(max_len=100),
    "barcode": Str(max_len=100), "unit": Str(max_len=40), "cost": Money(), "selling_price": Money(),
    "low_stock_threshold": Num(**QTY), "supplier": Str(max_len=200), "is_medication": Bool(),
    "department_id": Id(), "is_active": Bool(), "notes": Text(max_len=2000),
}


@bp.get("/meta")
@login_required(perm="inventory.view")
def meta():
    return jsonify(service.meta(current_principal()))


# ---- items ----------------------------------------------------------------------------------------

@bp.get("/items")
@login_required(perm="inventory.view")
def list_items():
    p = current_principal()
    f = query_args({"q": Str(max_len=100), "category": Str(max_len=100), "is_medication": Bool(),
                    "department_id": Id(), "active": Bool()})
    stmt = service.list_items_stmt(p, f.get("q"), f.get("category"), f.get("is_medication"), f.get("department_id"),
                                   f.get("active"))
    return jsonify(paginate(db.session, stmt, service.item_json, default_per_page=50))


@bp.post("/items")
@login_required
def create_item():
    data = validate(request_json(), ITEM_SCHEMA)
    return jsonify(service.item_json(service.create_item(current_principal(), data))), 201


@bp.get("/items/<int:item_id>")
@login_required(perm="inventory.view")
def get_item(item_id):
    p = current_principal()
    item = service.get_item(p, item_id)
    out = service.item_json(item)
    out["stock"] = service.item_stock_by_location(p, item.id)
    return jsonify(out)


@bp.patch("/items/<int:item_id>")
@login_required
def update_item(item_id):
    schema = dict(ITEM_SCHEMA, version=Int(required=True))
    data = validate(request_json(), schema, partial=True)
    return jsonify(service.item_json(service.update_item(current_principal(), item_id, data)))


@bp.delete("/items/<int:item_id>")
@login_required
def delete_item(item_id):
    return jsonify(service.delete_item(current_principal(), item_id)), 202


@bp.get("/lookup")
@login_required(perm="inventory.view")
def lookup():
    """Exact barcode / SKU lookup for USB scanners (keyboard wedge)."""
    p = current_principal()
    f = query_args({"code": Str(required=True, max_len=100)})
    item = service.lookup(p, f["code"])
    out = service.item_json(item)
    out["stock"] = service.item_stock_by_location(p, item.id)
    return jsonify(out)


# ---- locations & stock ----------------------------------------------------------------------------

@bp.get("/locations")
@login_required(perm="inventory.view")
def locations():
    return jsonify({"items": service.list_locations(current_principal())})


@bp.get("/stock")
@login_required(perm="inventory.view")
def stock_levels():
    f = query_args({"location_id": Id(), "item_id": Id(), "q": Str(max_len=100), "category": Str(max_len=100),
                    "is_medication": Bool(), "include_zero": Bool()})
    return jsonify(reports.stock_levels(current_principal(), f.get("location_id"), f.get("item_id"), f.get("q"),
                                        f.get("category"), f.get("is_medication"), bool(f.get("include_zero"))))


@bp.get("/lots")
@login_required(perm="inventory.view")
def lots():
    p = current_principal()
    f = query_args({"item_id": Id(required=True), "location_id": Id(), "include_empty": Bool()})
    service.get_item(p, f["item_id"])
    return jsonify({"items": reports.lots(p, f["item_id"], f.get("location_id"), bool(f.get("include_empty")))})


@bp.post("/receive")
@login_required
def receive():
    data = validate(request_json(), {
        "location_id": Id(required=True), "item_id": Id(required=True), "quantity": _qty(),
        "lot_code": Str(max_len=100), "expiry_date": Date(), "unit_cost": Money(), "reason": Str(max_len=300)})
    return jsonify(stock.receive(current_principal(), data)), 201


@bp.post("/use")
@login_required
def use():
    data = validate(request_json(), {
        "location_id": Id(required=True), "item_id": Id(required=True), "quantity": _qty(), "lot_id": Id(),
        "reason": Str(max_len=300), "reference_type": Str(max_len=40, pattern=r"[a-z_]{1,40}"),
        "reference_id": Id()})
    return jsonify(stock.use(current_principal(), data))


@bp.post("/adjust")
@login_required
def adjust():
    data = validate(request_json(), {
        "location_id": Id(required=True), "item_id": Id(required=True),
        "delta": Num(required=True, min_value=-10**9, max_value=10**9, places=3), "lot_id": Id(),
        "reason": Str(required=True, max_len=300)})
    return jsonify(stock.adjust(current_principal(), data))


@bp.post("/write-off")
@login_required
def write_off():
    data = validate(request_json(), {
        "location_id": Id(required=True), "item_id": Id(), "lot_id": Id(), "quantity": _qty(required=False),
        "reason": Str(max_len=300)})
    return jsonify(stock.write_off(current_principal(), data))


@bp.post("/transfers")
@login_required
def create_transfer():
    data = validate(request_json(), {
        "from_location_id": Id(required=True), "to_location_id": Id(required=True),
        "items": List(Obj({"item_id": Id(required=True), "quantity": _qty(), "lot_id": Id()}), min_items=1,
                      max_items=100, required=True),
        "notes": Str(max_len=500)})
    p = current_principal()
    tr = stock.transfer(p, data)
    return jsonify(reports.get_transfer(p, tr.id)), 201


@bp.get("/transfers")
@login_required(perm="inventory.view")
def list_transfers():
    f = query_args({"location_id": Id()})
    return jsonify(reports.list_transfers(current_principal(), f.get("location_id")))


@bp.get("/transfers/<int:transfer_id>")
@login_required(perm="inventory.view")
def get_transfer(transfer_id):
    return jsonify(reports.get_transfer(current_principal(), transfer_id))


@bp.get("/movements")
@login_required(perm="inventory.view")
def movements():
    f = query_args({"location_id": Id(), "item_id": Id(), "type": Enum(MOVEMENT_TYPES),
                    "reference_type": Str(max_len=40), "reference_id": Id(), "date_from": Date(), "date_to": Date()})
    return jsonify(reports.movements(current_principal(), f))


@bp.get("/low-stock")
@login_required(perm="inventory.view")
def low_stock():
    f = query_args({"location_id": Id()})
    return jsonify(reports.low_stock(current_principal(), f.get("location_id")))


@bp.get("/expiry")
@login_required(perm="inventory.view")
def expiry():
    f = query_args({"days": Int(min_value=0, max_value=3650), "location_id": Id(), "item_id": Id(),
                    "is_medication": Bool()})
    days = f.get("days")
    return jsonify(reports.expiry_report(current_principal(), 30 if days is None else days, f.get("location_id"),
                                         f.get("item_id"), f.get("is_medication")))
