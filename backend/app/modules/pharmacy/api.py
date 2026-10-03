"""/api/v1/pharmacy — prescription queue, dispensing, OTC sales, medication catalog, expiry."""
from flask import Blueprint, jsonify

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import (Bool, Date, Enum, Id, Int, List, Money, Num, Obj, Str, query_args,
                                         request_json, validate)
from . import service

bp = Blueprint("pharmacy", __name__, url_prefix="/pharmacy")


def _qty(required=True):
    return Num(required=required, min_value="0.001", max_value=10**9, places=3)


@bp.get("/meta")
@login_required
def meta():
    return jsonify(service.meta(current_principal()))


@bp.get("/queue")
@login_required
def queue():
    f = query_args({"status": Enum(["open", "all", "pending", "partially_dispensed", "dispensed", "cancelled"]),
                    "q": Str(max_len=100), "patient_id": Id(), "date_from": Date(), "date_to": Date()})
    return jsonify(service.queue(current_principal(), f))


@bp.get("/prescriptions/<int:rx_id>")
@login_required
def get_prescription(rx_id):
    return jsonify(service.get_prescription(current_principal(), rx_id))


@bp.post("/prescriptions/<int:rx_id>/dispense")
@login_required
def dispense(rx_id):
    data = validate(request_json(), {
        "clinic_id": Id(), "version": Int(), "notes": Str(max_len=500), "complete": Bool(),
        "items": List(Obj({"prescription_item_id": Id(required=True), "inventory_item_id": Id(),
                           "quantity": _qty(), "lot_id": Id(), "is_substitution": Bool(),
                           "note": Str(max_len=500)}), max_items=100)})
    return jsonify(service.dispense(current_principal(), rx_id, data))


@bp.get("/sales")
@login_required
def list_sales():
    f = query_args({"clinic_id": Id(), "patient_id": Id(), "date_from": Date(), "date_to": Date()})
    return jsonify(service.list_sales(current_principal(), f))


@bp.post("/sales")
@login_required
def create_sale():
    data = validate(request_json(), {
        "clinic_id": Id(), "patient_id": Id(), "customer_name": Str(max_len=200), "paid_amount": Money(),
        "notes": Str(max_len=2000),
        "items": List(Obj({"inventory_item_id": Id(required=True), "quantity": _qty(), "unit_price": Money(),
                           "lot_id": Id()}), min_items=1, max_items=100, required=True)})
    return jsonify(service.create_sale(current_principal(), data)), 201


@bp.get("/sales/<int:sale_id>")
@login_required
def get_sale(sale_id):
    return jsonify(service.get_sale(current_principal(), sale_id))


@bp.get("/medications")
@login_required
def medications():
    f = query_args({"clinic_id": Id(), "q": Str(max_len=100), "in_stock": Bool()})
    return jsonify(service.medications(current_principal(), f))


@bp.get("/expiry")
@login_required
def expiry():
    f = query_args({"clinic_id": Id(), "days": Int(min_value=0, max_value=3650)})
    return jsonify(service.expiry(current_principal(), f))
