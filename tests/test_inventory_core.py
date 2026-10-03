"""Inventory: catalog, locations/scope, stock math, FEFO, reports, transfers."""
from datetime import timedelta

from backend.app.core.timeutil import local_today

API = "/api/v1/inventory"


def locs(c):
    r = c.get(f"{API}/locations")
    assert r.status_code == 200, r.get_json()
    return r.get_json()["items"]


def loc_id(c, kind, clinic_id=None, department_id=None):
    for l in locs(c):
        if l["kind"] == kind and (clinic_id is None or l["clinic_id"] == clinic_id) and \
                (department_id is None or l["department_id"] == department_id):
            return l["id"]
    raise AssertionError("location not found")


def mk_item(c, **kw):
    body = {"name": "Gloves", "unit": "box", "cost": "10.00", "selling_price": "15.00"}
    body.update(kw)
    r = c.post(f"{API}/items", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def receive(c, loc, item, qty, **kw):
    r = c.post(f"{API}/receive", json={"location_id": loc, "item_id": item, "quantity": qty, **kw})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def level(c, loc, item):
    r = c.get(f"{API}/stock", query_string={"location_id": loc, "item_id": item, "include_zero": 1})
    assert r.status_code == 200, r.get_json()
    items = r.get_json()["items"]
    return items[0]["quantity"] if items else "0"


def test_item_crud_version_and_codes(world, client_for):
    a = world["A"]
    head = client_for(a["users"]["dent_head"])
    it = mk_item(head, name="Composite", sku="CMP-1", barcode="6291041500213", low_stock_threshold="5")
    assert it["department_id"] == a["departments"]["dentistry"]  # defaulted to the only visible dept
    # duplicate barcode / sku (case-insensitive) rejected
    r = head.post(f"{API}/items", json={"name": "X", "barcode": "6291041500213"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "barcode_taken"
    r = head.post(f"{API}/items", json={"name": "X", "sku": "cmp-1"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "sku_taken"
    # validation
    r = head.post(f"{API}/items", json={"name": "", "cost": "-1"})
    assert r.status_code == 422 and {"name", "cost"} <= set(r.get_json()["error"]["details"])
    # update with version
    r = head.patch(f"{API}/items/{it['id']}", json={"name": "Composite A2", "version": it["version"]})
    assert r.status_code == 200 and r.get_json()["version"] == it["version"] + 1
    r = head.patch(f"{API}/items/{it['id']}", json={"name": "Stale", "version": it["version"]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    # barcode / SKU lookup (scanner)
    r = head.get(f"{API}/lookup", query_string={"code": "6291041500213"})
    assert r.status_code == 200 and r.get_json()["id"] == it["id"]
    r = head.get(f"{API}/lookup", query_string={"code": "cmp-1"})
    assert r.status_code == 200 and r.get_json()["id"] == it["id"]
    assert head.get(f"{API}/lookup", query_string={"code": "nope"}).status_code == 404
    # dermatology doctor cannot see a dentistry item
    derm = client_for(a["users"]["derm_doc"])
    assert derm.get(f"{API}/items/{it['id']}").status_code == 404
    assert derm.get(f"{API}/lookup", query_string={"code": "6291041500213"}).status_code == 404
    # cross-tenant
    b_mgr = client_for(world["B"]["users"]["manager"])
    assert b_mgr.get(f"{API}/items/{it['id']}").status_code == 404
    assert b_mgr.get(f"{API}/lookup", query_string={"code": "6291041500213"}).status_code == 404
    # center B may reuse the same barcode
    mk_item(b_mgr, name="Other", barcode="6291041500213")


def test_item_delete_permissions_and_undo(world, client_for):
    a = world["A"]
    doc = client_for(a["users"]["dent_doc1"])
    it = mk_item(doc, name="Bur")
    assert doc.delete(f"{API}/items/{it['id']}").status_code == 403  # doctors lack inventory.delete
    head = client_for(a["users"]["dent_head"])
    r = head.delete(f"{API}/items/{it['id']}")
    assert r.status_code == 202
    assert head.get(f"{API}/items/{it['id']}").status_code == 404
    assert head.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    assert head.get(f"{API}/items/{it['id']}").status_code == 200
    # item with stock history cannot be deleted
    loc = loc_id(head, "clinic", a["clinics"]["dent1"])
    receive(head, loc, it["id"], 3)
    r = head.delete(f"{API}/items/{it['id']}")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "item_in_use"


def test_center_wide_items_need_center_wide_editor(world, client_for):
    a = world["A"]
    mgr = client_for(a["users"]["manager"])
    it = mk_item(mgr, name="Paper towels")
    assert it["department_id"] is None
    doc = client_for(a["users"]["dent_doc1"])
    assert doc.get(f"{API}/items/{it['id']}").status_code == 200  # visible to all
    r = doc.patch(f"{API}/items/{it['id']}", json={"name": "x", "version": it["version"]})
    assert r.status_code == 403
    # receptionist with several departments must pick an owner department
    rec = client_for(a["users"]["rec_multi"])
    r = rec.post(f"{API}/items", json={"name": "Masks"})
    assert r.status_code == 422 and "department_id" in r.get_json()["error"]["details"]
    r = rec.post(f"{API}/items", json={"name": "Masks", "department_id": a["departments"]["laboratory"]})
    assert r.status_code == 404


def test_locations_scope(world, client_for):
    a = world["A"]
    doc = client_for(a["users"]["dent_doc1"])
    kinds = {(l["kind"], l["clinic_id"], l["department_id"]) for l in locs(doc)}
    assert kinds == {("clinic", a["clinics"]["dent1"], a["departments"]["dentistry"]),
                     ("department_pool", None, a["departments"]["dentistry"])}
    mgr = client_for(a["users"]["manager"])
    all_locs = locs(mgr)
    assert any(l["kind"] == "center_pool" for l in all_locs)
    assert len([l for l in all_locs if l["kind"] == "clinic"]) == 8
    # doctor sees the department pool but cannot manage it
    pool = [l for l in locs(doc) if l["kind"] == "department_pool"][0]
    assert pool["can_manage"] is False


def test_stock_math_fefo_and_negative_guard(world, client_for):
    a = world["A"]
    doc = client_for(a["users"]["dent_doc1"])
    loc = loc_id(doc, "clinic", a["clinics"]["dent1"])
    it = mk_item(doc, name="Anesthetic", low_stock_threshold="4")
    today = local_today()
    receive(doc, loc, it["id"], 5, lot_code="L-LATE", expiry_date=(today + timedelta(days=200)).isoformat())
    receive(doc, loc, it["id"], 3, lot_code="L-SOON", expiry_date=(today + timedelta(days=20)).isoformat(),
            unit_cost="2.50")
    receive(doc, loc, it["id"], 2, lot_code="L-OLD", expiry_date=(today - timedelta(days=1)).isoformat())
    assert level(doc, loc, it["id"]) == "10"
    # FEFO: soonest non-expired lot first, expired lot skipped
    r = doc.post(f"{API}/use", json={"location_id": loc, "item_id": it["id"], "quantity": 4})
    assert r.status_code == 200, r.get_json()
    lots = r.get_json()["lots"]
    assert [(x["lot_code"], x["quantity"]) for x in lots] == [("L-SOON", "3"), ("L-LATE", "1")]
    assert level(doc, loc, it["id"]) == "6"
    # only 4 usable left (2 expired): asking for 5 fails, nothing changes
    r = doc.post(f"{API}/use", json={"location_id": loc, "item_id": it["id"], "quantity": 5})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "insufficient_stock"
    assert r.get_json()["error"]["details"]["available"] == "4"
    assert level(doc, loc, it["id"]) == "6"
    # explicit expired lot cannot be used
    lot_list = doc.get(f"{API}/lots", query_string={"item_id": it["id"], "location_id": loc}).get_json()["items"]
    old = [l for l in lot_list if l["lot_code"] == "L-OLD"][0]
    r = doc.post(f"{API}/use", json={"location_id": loc, "item_id": it["id"], "quantity": 1, "lot_id": old["id"]})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "lot_expired"
    # low stock: 6 -> 3 crosses threshold 4 -> notification to clinic staff
    r = doc.post(f"{API}/use", json={"location_id": loc, "item_id": it["id"], "quantity": 3})
    assert r.status_code == 200
    notes = doc.get("/api/v1/notifications").get_json()["items"]
    assert any(n["type"] == "low_stock" and "Anesthetic" in n["title"] for n in notes)
    low = doc.get(f"{API}/low-stock").get_json()["items"]
    assert [(x["item"]["id"], x["quantity"]) for x in low] == [(it["id"], "3")]
    # expiry report: expired + expiring lots
    exp = doc.get(f"{API}/expiry", query_string={"days": 30, "location_id": loc}).get_json()["items"]
    assert [x["status"] for x in exp] == ["expired"]  # L-SOON is used up
    exp = doc.get(f"{API}/expiry", query_string={"days": 365}).get_json()["items"]
    assert [x["lot_code"] for x in exp] == ["L-OLD", "L-LATE"]
    # doctor cannot write off in... their own clinic is manageable -> write off all expired
    r = doc.post(f"{API}/write-off", json={"location_id": loc})
    assert r.status_code == 200 and [x["quantity"] for x in r.get_json()["written_off"]] == ["2"]
    assert level(doc, loc, it["id"]) == "1"
    # adjust: reason required, +/-
    r = doc.post(f"{API}/adjust", json={"location_id": loc, "item_id": it["id"], "delta": 2})
    assert r.status_code == 422
    r = doc.post(f"{API}/adjust", json={"location_id": loc, "item_id": it["id"], "delta": 2, "reason": "count"})
    assert r.status_code == 200 and r.get_json()["quantity"] == "3"
    r = doc.post(f"{API}/adjust", json={"location_id": loc, "item_id": it["id"], "delta": -5, "reason": "count"})
    assert r.status_code == 409
    r = doc.post(f"{API}/adjust", json={"location_id": loc, "item_id": it["id"], "delta": "-0.5", "reason": "x"})
    assert r.status_code == 200 and r.get_json()["quantity"] == "2.5"
    # movement history (newest first) and types
    mv = doc.get(f"{API}/movements", query_string={"item_id": it["id"]}).get_json()
    types = [m["type"] for m in mv["items"]]
    assert types[0] == "adjust" and types.count("receive") == 3 and "write_off" in types
    assert mv["items"][0]["balance_after"] == "2.5"
    assert doc.get(f"{API}/movements", query_string={"type": "write_off"}).get_json()["total"] == 1


def test_scope_isolation(world, client_for):
    a = world["A"]
    derm = client_for(a["users"]["derm_doc"])
    derm_loc = loc_id(derm, "clinic", a["clinics"]["derm1"])
    derm_item = mk_item(derm, name="Cream")
    receive(derm, derm_loc, derm_item["id"], 5)
    dent = client_for(a["users"]["dent_doc1"])
    dent_item = mk_item(dent, name="Floss")
    # dentistry user can't touch dermatology clinic stock
    r = dent.post(f"{API}/receive", json={"location_id": derm_loc, "item_id": dent_item["id"], "quantity": 1})
    assert r.status_code == 404
    r = dent.post(f"{API}/use", json={"location_id": derm_loc, "item_id": derm_item["id"], "quantity": 1})
    assert r.status_code == 404
    assert dent.get(f"{API}/stock", query_string={"location_id": derm_loc}).status_code == 404
    assert dent.get(f"{API}/movements", query_string={"location_id": derm_loc}).status_code == 404
    assert all(m["location_id"] != derm_loc for m in dent.get(f"{API}/movements").get_json()["items"])
    # other dentistry clinic is out of a dent1 doctor's scope
    mgr = client_for(a["users"]["manager"])
    dent2_loc = loc_id(mgr, "clinic", a["clinics"]["dent2"])
    r = dent.post(f"{API}/use", json={"location_id": dent2_loc, "item_id": dent_item["id"], "quantity": 1})
    assert r.status_code == 404
    # cross-tenant: center B manager
    b = client_for(world["B"]["users"]["manager"])
    r = b.post(f"{API}/use", json={"location_id": derm_loc, "item_id": derm_item["id"], "quantity": 1})
    assert r.status_code == 404
    assert b.get(f"{API}/stock", query_string={"location_id": derm_loc}).status_code == 404
    # doctor cannot receive into the department pool (department-level access needed)
    pool = loc_id(dent, "department_pool")
    r = dent.post(f"{API}/receive", json={"location_id": pool, "item_id": dent_item["id"], "quantity": 1})
    assert r.status_code == 403
    # receptionist without inventory.edit override... view-only check via permission removal is in
    # test_permission_denied below.
    assert derm.get(f"{API}/stock", query_string={"location_id": derm_loc}).get_json()["items"][0]["quantity"] == "5"


def test_permission_denied(app, world, client_for):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import UserPermission
    a = world["A"]
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        db.session.add(UserPermission(health_center_id=a["center_id"], user_id=a["users"]["rec_dent1"]["id"],
                                      permission="inventory.edit", allowed=False))
        db.session.commit()
    rec = client_for(a["users"]["rec_dent1"])
    loc = loc_id(rec, "clinic", a["clinics"]["dent1"])
    assert rec.post(f"{API}/items", json={"name": "x", "department_id": a["departments"]["dentistry"]}
                    ).status_code == 403
    head = client_for(a["users"]["dent_head"])
    it = mk_item(head, name="Tips")
    r = rec.post(f"{API}/receive", json={"location_id": loc, "item_id": it["id"], "quantity": 1})
    assert r.status_code == 403
    assert rec.get(f"{API}/stock").status_code == 200


def test_transfers_between_clinics_and_pools(world, client_for):
    a = world["A"]
    head = client_for(a["users"]["dent_head"])
    pool = loc_id(head, "department_pool")
    dent1 = loc_id(head, "clinic", a["clinics"]["dent1"])
    dent2 = loc_id(head, "clinic", a["clinics"]["dent2"])
    it = mk_item(head, name="Needles")
    today = local_today()
    receive(head, pool, it["id"], 4, lot_code="A", expiry_date=(today + timedelta(days=90)).isoformat(),
            unit_cost="1.00")
    receive(head, pool, it["id"], 6, lot_code="B", expiry_date=(today + timedelta(days=30)).isoformat())
    # department manager pushes pool stock to clinic 2 (FEFO: lot B first)
    r = head.post(f"{API}/transfers", json={"from_location_id": pool, "to_location_id": dent2,
                                            "items": [{"item_id": it["id"], "quantity": 8}], "notes": "restock"})
    assert r.status_code == 201, r.get_json()
    tr = r.get_json()
    assert tr["from_location"]["kind"] == "department_pool" and tr["to_location"]["clinic_id"] == a["clinics"]["dent2"]
    assert [(l["lot_code"], l["quantity"]) for l in tr["items"][0]["lots"]] == [("B", "6"), ("A", "2")]
    assert level(head, pool, it["id"]) == "2" and level(head, dent2, it["id"]) == "8"
    # lots keep code/expiry at the destination
    dl = head.get(f"{API}/lots", query_string={"item_id": it["id"], "location_id": dent2}).get_json()["items"]
    assert sorted((l["lot_code"], l["quantity"]) for l in dl) == [("A", "2"), ("B", "6")]
    # a dent1 doctor draws from the shared pool into their clinic
    doc = client_for(a["users"]["dent_doc1"])
    r = doc.post(f"{API}/transfers", json={"from_location_id": pool, "to_location_id": dent1,
                                           "items": [{"item_id": it["id"], "quantity": 2}]})
    assert r.status_code == 201
    assert level(head, pool, it["id"]) == "0" and level(head, dent1, it["id"]) == "2"
    # ... but cannot send to clinic 2 (out of scope) nor overdraw
    r = doc.post(f"{API}/transfers", json={"from_location_id": dent1, "to_location_id": dent2,
                                           "items": [{"item_id": it["id"], "quantity": 1}]})
    assert r.status_code == 404
    r = doc.post(f"{API}/transfers", json={"from_location_id": dent1, "to_location_id": pool,
                                           "items": [{"item_id": it["id"], "quantity": 3}]})
    assert r.status_code == 409
    assert level(head, dent1, it["id"]) == "2" and level(head, pool, it["id"]) == "0"  # atomic
    # manager: center pool -> dermatology clinic
    mgr = client_for(a["users"]["manager"])
    center = loc_id(mgr, "center_pool")
    gen = mk_item(mgr, name="Alcohol")
    receive(mgr, center, gen["id"], 10)
    derm_loc = loc_id(mgr, "clinic", a["clinics"]["derm1"])
    r = mgr.post(f"{API}/transfers", json={"from_location_id": center, "to_location_id": derm_loc,
                                           "items": [{"item_id": gen["id"], "quantity": 4}]})
    assert r.status_code == 201
    # transfers list: dentistry head sees pool/clinic transfers, not the derm one
    ids = [t["id"] for t in head.get(f"{API}/transfers").get_json()["items"]]
    assert tr["id"] in ids and r.get_json()["id"] not in ids
    assert head.get(f"{API}/transfers/{r.get_json()['id']}").status_code == 404
    assert mgr.get(f"{API}/transfers/{tr['id']}").status_code == 200
    # doctor cannot see the center pool
    assert doc.post(f"{API}/transfers", json={"from_location_id": center, "to_location_id": dent1,
                                              "items": [{"item_id": gen["id"], "quantity": 1}]}).status_code == 404
    # same source and destination rejected
    r = mgr.post(f"{API}/transfers", json={"from_location_id": center, "to_location_id": center,
                                           "items": [{"item_id": gen["id"], "quantity": 1}]})
    assert r.status_code == 422


def test_meta(world, client_for):
    a = world["A"]
    doc = client_for(a["users"]["dent_doc1"])
    mk_item(doc, name="Mirror", category="Instruments", unit="pcs")
    m = doc.get(f"{API}/meta").get_json()
    assert m["categories"] == ["Instruments"] and m["units"] == ["pcs"]
    assert [d["id"] for d in m["departments"]] == [a["departments"]["dentistry"]]
    assert m["can_edit"] and not m["can_delete"]
