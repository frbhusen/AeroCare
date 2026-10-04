"""Pharmacy: queue visibility, dispensing (FEFO, substitution, status transitions), sales, catalog."""
from datetime import timedelta
from decimal import Decimal

from backend.app.core.timeutil import local_today
from tests.test_inventory_core import API as INV, level, loc_id, mk_item, receive

PH = "/api/v1/pharmacy"


def make_rx(app, center, clinic_key, dept_code, author_key, items, patient_name="Rx Patient"):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import Patient, Prescription, PrescriptionItem, User
    from backend.app.services.centers import next_sequence
    cid = center["center_id"]
    with app.app_context(), tenancy.scoped("tenant", cid):
        pt = Patient(health_center_id=cid, code=next_sequence(cid, "patient_seq"), full_name=patient_name,
                     search_name=patient_name.lower(), allergies="Penicillin", chronic_conditions="SECRET-HISTORY")
        db.session.add(pt)
        db.session.flush()
        rx = Prescription(health_center_id=cid, patient_id=pt.id, department_id=center["departments"][dept_code],
                          clinic_id=center["clinics"][clinic_key], status="pending")
        rx.set_author(db.session.get(User, center["users"][author_key]["id"]))
        db.session.add(rx)
        db.session.flush()
        ids = []
        for n, (name, inv_id, qty) in enumerate(items):
            i = PrescriptionItem(health_center_id=cid, prescription_id=rx.id, medication_name=name,
                                 inventory_item_id=inv_id, dose="500mg", frequency="3x/day",
                                 quantity=None if qty is None else Decimal(qty), sort_order=n)
            db.session.add(i)
            db.session.flush()
            ids.append(i.id)
        db.session.commit()
        return rx.id, ids, pt.id


def setup_pharmacy(world, client_for):
    a = world["A"]
    ph = client_for(a["users"]["pharm_doc"])
    loc = loc_id(ph, "clinic", a["clinics"]["pharm1"])
    amox = mk_item(ph, name="Amoxicillin 500", is_medication=True, selling_price="2.50", barcode="AMX500",
                   low_stock_threshold="2")
    para = mk_item(ph, name="Paracetamol", is_medication=True, selling_price="1.00")
    today = local_today()
    receive(ph, loc, amox["id"], 10, lot_code="LATE", expiry_date=(today + timedelta(days=300)).isoformat())
    receive(ph, loc, amox["id"], 5, lot_code="SOON", expiry_date=(today + timedelta(days=10)).isoformat())
    receive(ph, loc, para["id"], 20)
    assert amox["department_id"] == a["departments"]["pharmacy"]
    return ph, loc, amox, para


def test_queue_visibility_and_privacy(app, world, client_for):
    a = world["A"]
    ph, loc, amox, para = setup_pharmacy(world, client_for)
    rx_id, _, _ = make_rx(app, a, "derm1", "dermatology", "derm_doc", [("Amoxicillin", amox["id"], "6")])
    q = ph.get(f"{PH}/queue").get_json()
    row = [r for r in q["items"] if r["id"] == rx_id][0]
    assert row["patient"]["allergies"] == "Penicillin" and row["patient"]["code"].startswith("PAT-")
    assert "SECRET-HISTORY" not in str(q)  # no other medical history
    assert row["doctor_name"].startswith("derm_doc") and row["items"][0]["dose"] == "500mg"
    # center-wide receptionist sees it too; dermatology doctor does not (no pharmacy scope)
    assert client_for(a["users"]["rec_center"]).get(f"{PH}/queue").status_code == 200
    derm = client_for(a["users"]["derm_doc"])
    assert derm.get(f"{PH}/queue").status_code == 403
    assert derm.get(f"{PH}/prescriptions/{rx_id}").status_code == 403
    # search by patient name
    assert ph.get(f"{PH}/queue", query_string={"q": "rx pat"}).get_json()["total"] >= 1
    assert ph.get(f"{PH}/queue", query_string={"q": "zzz-nobody"}).get_json()["total"] == 0
    # cross tenant
    b_ph = client_for(world["B"]["users"]["pharm_doc"])
    assert b_ph.get(f"{PH}/prescriptions/{rx_id}").status_code == 404
    assert all(r["id"] != rx_id for r in b_ph.get(f"{PH}/queue").get_json()["items"])


def test_dispense_transitions_and_stock(app, world, client_for):
    a = world["A"]
    ph, loc, amox, para = setup_pharmacy(world, client_for)
    rx_id, (i1, i2), _ = make_rx(app, a, "gen1", "general_medicine", "gen_doc",
                                 [("Amoxicillin", amox["id"], "8"), ("Pain killer", None, "4")])
    url = f"{PH}/prescriptions/{rx_id}/dispense"
    # over-dispensing rejected
    r = ph.post(url, json={"items": [{"prescription_item_id": i1, "quantity": 9}]})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "exceeds_prescribed"
    # unlinked line needs an inventory item
    r = ph.post(url, json={"items": [{"prescription_item_id": i2, "quantity": 1}]})
    assert r.status_code == 422
    # partial: 6 amoxicillin FEFO -> SOON(5) + LATE(1)
    r = ph.post(url, json={"items": [{"prescription_item_id": i1, "quantity": 6}]})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "partially_dispensed"
    lots = body["dispensations"][0]["items"][0]["lots"]
    assert [(l["lot_code"], l["quantity"]) for l in lots] == [("SOON", "5"), ("LATE", "1")]
    assert level(ph, loc, amox["id"]) == "9"
    mv = ph.get(f"{INV}/movements", query_string={"item_id": amox["id"], "type": "dispense"}).get_json()
    assert mv["total"] == 2
    # substitution needs a note
    r = ph.post(url, json={"items": [{"prescription_item_id": i1, "inventory_item_id": para["id"], "quantity": 2}]})
    assert r.status_code == 422 and "items.0.note" in r.get_json()["error"]["details"]
    r = ph.post(url, json={"items": [
        {"prescription_item_id": i1, "inventory_item_id": para["id"], "quantity": 2, "note": "out of brand"},
        {"prescription_item_id": i2, "inventory_item_id": para["id"], "quantity": 4}]})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "dispensed"
    d2 = body["dispensations"][1]["items"]
    assert d2[0]["is_substitution"] is True and d2[1]["is_substitution"] is False
    assert [i["dispensed_quantity"] for i in body["items"]] == ["8", "4"]
    assert level(ph, loc, para["id"]) == "14"
    # closed: no further dispensing, and gone from the open queue
    r = ph.post(url, json={"items": [{"prescription_item_id": i1, "quantity": 1}]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "prescription_closed"
    assert all(x["id"] != rx_id for x in ph.get(f"{PH}/queue").get_json()["items"])
    assert any(x["id"] == rx_id for x in ph.get(f"{PH}/queue", query_string={"status": "dispensed"}
                                               ).get_json()["items"])


def test_dispense_insufficient_stock_is_atomic_and_complete_flag(app, world, client_for):
    a = world["A"]
    ph, loc, amox, para = setup_pharmacy(world, client_for)
    rx_id, (i1, i2), _ = make_rx(app, a, "gen1", "general_medicine", "gen_doc",
                                 [("Paracetamol", para["id"], "5"), ("Amoxicillin", amox["id"], None)])
    url = f"{PH}/prescriptions/{rx_id}/dispense"
    r = ph.post(url, json={"items": [{"prescription_item_id": i1, "quantity": 5},
                                     {"prescription_item_id": i2, "quantity": 100}]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "insufficient_stock"
    assert level(ph, loc, para["id"]) == "20"  # rolled back
    detail = ph.get(f"{PH}/prescriptions/{rx_id}").get_json()
    assert detail["status"] == "pending" and detail["dispensations"] == []
    # stale version rejected
    r = ph.post(url, json={"version": detail["version"] + 5, "items": [{"prescription_item_id": i1, "quantity": 1}]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    r = ph.post(url, json={"items": [{"prescription_item_id": i1, "quantity": 2}], "complete": True})
    assert r.status_code == 200 and r.get_json()["status"] == "dispensed"


def test_dispense_permissions(app, world, client_for):
    a = world["A"]
    ph, loc, amox, para = setup_pharmacy(world, client_for)
    rx_id, (i1,), _ = make_rx(app, a, "gen1", "general_medicine", "gen_doc", [("Amox", amox["id"], "1")])
    body = {"items": [{"prescription_item_id": i1, "quantity": 1}]}
    assert client_for(a["users"]["dent_doc1"]).post(f"{PH}/prescriptions/{rx_id}/dispense", json=body
                                                    ).status_code == 403
    # center manager must act from a pharmacy clinic (the only one is picked automatically)
    mgr = client_for(a["users"]["manager"])
    r = mgr.post(f"{PH}/prescriptions/{rx_id}/dispense", json=dict(body, clinic_id=a["clinics"]["derm1"]))
    assert r.status_code == 404
    r = mgr.post(f"{PH}/prescriptions/{rx_id}/dispense", json=body)
    assert r.status_code == 200 and r.get_json()["status"] == "dispensed"


def test_sales_catalog_and_expiry(app, world, client_for):
    a = world["A"]
    ph, loc, amox, para = setup_pharmacy(world, client_for)
    r = ph.post(f"{PH}/sales", json={"items": [{"inventory_item_id": para["id"], "quantity": 3},
                                               {"inventory_item_id": amox["id"], "quantity": 2, "unit_price": "3"}],
                                     "paid_amount": "10", "customer_name": "Walk-in"})
    assert r.status_code == 201, r.get_json()
    s = r.get_json()
    assert s["total"] == "9.00" and s["change"] == "1.00" and len(s["items"]) == 2
    assert level(ph, loc, para["id"]) == "17" and level(ph, loc, amox["id"]) == "13"
    assert ph.get(f"{INV}/movements", query_string={"type": "sale"}).get_json()["total"] == 2
    assert ph.get(f"{PH}/sales/{s['id']}").get_json()["items"][0]["item_name"] == "Paracetamol"
    assert ph.get(f"{PH}/sales").get_json()["total"] == 1
    # insufficient stock
    r = ph.post(f"{PH}/sales", json={"items": [{"inventory_item_id": para["id"], "quantity": 100}]})
    assert r.status_code == 409
    # derm doctor: no pharmacy scope; other center: 404
    assert client_for(a["users"]["derm_doc"]).post(f"{PH}/sales", json={
        "items": [{"inventory_item_id": para["id"], "quantity": 1}]}).status_code == 403
    assert client_for(world["B"]["users"]["pharm_doc"]).get(f"{PH}/sales/{s['id']}").status_code == 404
    # medication catalog with usable stock at the pharmacy
    meds = ph.get(f"{PH}/medications", query_string={"q": "amox"}).get_json()
    assert [(m["name"], m["available"]) for m in meds["items"]] == [("Amoxicillin 500", "13")]
    assert ph.get(f"{PH}/medications", query_string={"q": "AMX500"}).get_json()["total"] == 1
    # expiry view of the pharmacy location
    exp = ph.get(f"{PH}/expiry", query_string={"days": 30}).get_json()["items"]
    assert [(e["lot_code"], e["status"]) for e in exp] == [("SOON", "expiring")]
    m = ph.get(f"{PH}/meta").get_json()
    assert m["clinics"][0]["id"] == a["clinics"]["pharm1"] and m["clinics"][0]["location_id"] == loc


def test_sale_creates_billing_invoice(app, world, client_for):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import Patient
    from backend.app.services.centers import next_sequence
    from backend.app.services.clinical import link_patient_to_clinic
    a = world["A"]
    ph, loc, amox, para = setup_pharmacy(world, client_for)
    cid = a["center_id"]
    with app.app_context(), tenancy.scoped("tenant", cid):
        pt = Patient(health_center_id=cid, code=next_sequence(cid, "patient_seq"), full_name="Buyer",
                     search_name="buyer")
        db.session.add(pt)
        db.session.flush()
        link_patient_to_clinic(cid, pt.id, a["clinics"]["pharm1"])
        db.session.commit()
        pid = pt.id
    # invoice needs a patient
    r = ph.post(f"{PH}/sales", json={"create_invoice": True,
                                     "items": [{"inventory_item_id": para["id"], "quantity": 1}]})
    assert r.status_code == 422 and level(ph, loc, para["id"]) == "20"
    r = ph.post(f"{PH}/sales", json={"create_invoice": True, "patient_id": pid, "paid_amount": "2.00",
                                     "items": [{"inventory_item_id": para["id"], "quantity": 4}]})
    assert r.status_code == 201, r.get_json()
    s = r.get_json()
    assert s["invoice_id"] and s["total"] == "4.00"
    inv = ph.get(f"/api/v1/billing/invoices/{s['invoice_id']}").get_json()
    assert inv["total"] == "4.00" and inv["paid_total"] == "2.00" and inv["status"] == "partially_paid"
    assert inv["items"][0]["reference_type"] == "pharmacy_sale" and inv["items"][0]["kind"] == "medicine"
    # patient not visible to the pharmacy -> 404, nothing sold
    with app.app_context(), tenancy.scoped("tenant", cid):
        other = Patient(health_center_id=cid, code=next_sequence(cid, "patient_seq"), full_name="Hidden",
                        search_name="hidden")
        db.session.add(other)
        db.session.commit()
        oid = other.id
    r = ph.post(f"{PH}/sales", json={"patient_id": oid, "items": [{"inventory_item_id": para["id"], "quantity": 1}]})
    assert r.status_code == 404 and level(ph, loc, para["id"]) == "16"
