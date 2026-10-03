import threading

from tests.test_billing_helpers import BASE, make_patient, new_invoice


def test_totals_discounts_partial_payments_and_status(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    c = client_for(a["users"]["rec_dent"])
    r = new_invoice(c, a, pid, items=[
        {"description": "Filling", "qty": 2, "unit_price": "150.00", "discount_percent": 10, "kind": "treatment"},
        {"description": "X-ray", "qty": 1, "unit_price": "80.50", "discount_amount": "0.50"},
        {"description": "Cleaning", "qty": "1.5", "unit_price": "33.33"},
    ], invoice_discount="20.00")
    assert r.status_code == 201, r.get_json()
    inv = r.get_json()
    # 300 + 80.50 + 50.00 (1.5*33.33=49.995 -> 50.00) = 430.50; discounts 30 + 0.50 + 20 = 50.50
    assert inv["subtotal"] == "430.50"
    assert inv["discount_total"] == "50.50"
    assert inv["total"] == "380.00" and inv["balance"] == "380.00" and inv["paid_total"] == "0.00"
    assert inv["status"] == "draft" and inv["number"].startswith("INV-")
    assert [i["line_total"] for i in inv["items"]] == ["270.00", "80.00", "50.00"]
    assert inv["currency"] == "SYP"

    iid = inv["id"]
    r = c.post(f"{BASE}/invoices/{iid}/issue", json={"version": inv["version"]})
    assert r.status_code == 200 and r.get_json()["status"] == "issued"

    r = c.post(f"{BASE}/invoices/{iid}/payments", json={"amount": "300.00"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["invoice"]["status"] == "partially_paid"
    assert body["invoice"]["paid_total"] == "300.00" and body["invoice"]["balance"] == "80.00"
    assert body["payment"]["method"] == "cash" and body["payment"]["receipt_number"].endswith("-1")

    # overpayment rejected
    r = c.post(f"{BASE}/invoices/{iid}/payments", json={"amount": "80.01"})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "overpayment"
    # non-cash method rejected
    r = c.post(f"{BASE}/invoices/{iid}/payments", json={"amount": "1.00", "method": "card"})
    assert r.status_code == 422
    # zero / negative rejected
    assert c.post(f"{BASE}/invoices/{iid}/payments", json={"amount": "0"}).status_code == 422
    assert c.post(f"{BASE}/invoices/{iid}/payments", json={"amount": "-5"}).status_code == 422

    r = c.post(f"{BASE}/invoices/{iid}/payments", json={"amount": "80.00"})
    assert r.get_json()["invoice"]["status"] == "paid" and r.get_json()["invoice"]["balance"] == "0.00"
    pay_id = r.get_json()["payment"]["id"]

    # issued invoices cannot be edited
    cur = c.get(f"{BASE}/invoices/{iid}").get_json()
    r = c.put(f"{BASE}/invoices/{iid}", json={"version": cur["version"], "notes": "x"})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "invoice_not_draft"
    # cannot void with payments
    r = c.post(f"{BASE}/invoices/{iid}/void", json={})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "invoice_has_payments"

    # void a payment -> back to partially paid
    r = c.post(f"{BASE}/invoices/{iid}/payments/{pay_id}/void", json={"reason": "mistake"})
    assert r.status_code == 200
    assert r.get_json()["invoice"]["status"] == "partially_paid" and r.get_json()["invoice"]["balance"] == "80.00"
    assert r.get_json()["payment"]["is_void"] is True
    assert c.post(f"{BASE}/invoices/{iid}/payments/{pay_id}/void", json={}).status_code == 422


def test_payment_on_draft_issues_it_and_void_flow(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    c = client_for(a["users"]["dent_doc1"])
    inv = new_invoice(c, a, pid).get_json()
    assert inv["doctor_user_id"] == a["users"]["dent_doc1"]["id"]  # defaults to the doctor creating it
    r = c.post(f"{BASE}/invoices/{inv['id']}/payments", json={"amount": "40"})
    assert r.status_code == 201 and r.get_json()["invoice"]["status"] == "partially_paid"
    # empty draft cannot be issued
    empty = new_invoice(c, a, pid, items=[]).get_json()
    r = c.post(f"{BASE}/invoices/{empty['id']}/issue", json={})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "invoice_empty"
    r = c.post(f"{BASE}/invoices/{empty['id']}/void", json={"reason": "not needed"})
    assert r.status_code == 200 and r.get_json()["status"] == "void"
    r = c.post(f"{BASE}/invoices/{empty['id']}/payments", json={"amount": "1"})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "invoice_void"


def test_validation_errors(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    c = client_for(a["users"]["manager"])
    r = new_invoice(c, a, pid, items=[{"description": "x", "qty": 1, "unit_price": "10", "discount_amount": "11"}])
    assert r.status_code == 422
    r = new_invoice(c, a, pid, items=[{"description": "x", "qty": 1, "unit_price": "10"}], invoice_discount="11")
    assert r.status_code == 422
    r = new_invoice(c, a, pid, items=[{"qty": 1, "unit_price": "10"}])  # no description, no service
    assert r.status_code == 422
    r = new_invoice(c, a, pid, items=[{"description": "x", "qty": 0, "unit_price": "10"}])
    assert r.status_code == 422
    r = new_invoice(c, a, pid, items=[{"description": "x", "unit_price": "10.001"}])
    assert r.status_code == 422
    r = new_invoice(c, a, pid, items=[{"description": "x", "unit_price": "10", "kind": "bogus"}])
    assert r.status_code == 422
    r = c.post(f"{BASE}/invoices", json={"clinic_id": a["clinics"]["dent1"]})
    assert r.status_code == 422


def test_edit_draft_and_version_conflict(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    c = client_for(a["users"]["rec_center"])
    inv = new_invoice(c, a, pid).get_json()
    r = c.put(f"{BASE}/invoices/{inv['id']}", json={
        "version": inv["version"], "notes": "updated",
        "items": [{"description": "A", "unit_price": "10.00", "qty": 3}, {"description": "B", "unit_price": "5"}]})
    assert r.status_code == 200, r.get_json()
    upd = r.get_json()
    assert upd["total"] == "35.00" and upd["notes"] == "updated" and len(upd["items"]) == 2
    assert upd["version"] > inv["version"]
    r = c.put(f"{BASE}/invoices/{inv['id']}", json={"version": inv["version"], "notes": "stale"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    r = c.put(f"{BASE}/invoices/{inv['id']}", json={"notes": "no version"})
    assert r.status_code == 422


def test_scope_doctor_receptionist_manager(app, world, client_for):
    a = world["A"]
    p1 = make_patient(app, a, "dent1", "Patient One")
    p2 = make_patient(app, a, "dent2", "Patient Two")
    p3 = make_patient(app, a, "derm1", "Patient Three")
    mgr = client_for(a["users"]["manager"])
    i1 = new_invoice(mgr, a, p1, "dent1").get_json()
    i2 = new_invoice(mgr, a, p2, "dent2").get_json()
    i3 = new_invoice(mgr, a, p3, "derm1").get_json()

    doc = client_for(a["users"]["dent_doc1"])
    ids = {i["id"] for i in doc.get(f"{BASE}/invoices").get_json()["items"]}
    assert i1["id"] in ids and i2["id"] not in ids and i3["id"] not in ids
    assert doc.get(f"{BASE}/invoices/{i2['id']}").status_code == 404
    assert doc.get(f"{BASE}/invoices/{i2['id']}/pdf").status_code == 404
    assert doc.post(f"{BASE}/invoices/{i2['id']}/payments", json={"amount": "1"}).status_code == 404
    # doctor cannot create in another clinic (404 - out of scope) nor for an invisible patient
    assert new_invoice(doc, a, p2, "dent2").status_code == 404
    assert new_invoice(doc, a, p2, "dent1").status_code == 404
    # doctor has no billing.delete
    assert doc.delete(f"{BASE}/invoices/{i1['id']}").status_code == 403

    rec1 = client_for(a["users"]["rec_dent1"])
    ids = {i["id"] for i in rec1.get(f"{BASE}/invoices").get_json()["items"]}
    assert ids & {i1["id"], i2["id"], i3["id"]} == {i1["id"]}

    rec_multi = client_for(a["users"]["rec_multi"])
    ids = {i["id"] for i in rec_multi.get(f"{BASE}/invoices").get_json()["items"]}
    assert {i1["id"], i2["id"], i3["id"]} <= ids

    head = client_for(a["users"]["dent_head"])
    ids = {i["id"] for i in head.get(f"{BASE}/invoices").get_json()["items"]}
    assert {i1["id"], i2["id"]} <= ids and i3["id"] not in ids
    assert head.get(f"{BASE}/invoices/{i3['id']}").status_code == 404
    # filters
    r = mgr.get(f"{BASE}/invoices?clinic_id={a['clinics']['dent2']}").get_json()
    assert [i["id"] for i in r["items"]] == [i2["id"]]
    r = mgr.get(f"{BASE}/invoices?patient_id={p3}&status=draft").get_json()
    assert [i["id"] for i in r["items"]] == [i3["id"]] and r["items"][0]["patient_name"] == "Patient Three"
    assert mgr.get(f"{BASE}/invoices?status=bogus").status_code == 422
    r = mgr.get(f"{BASE}/invoices?q={i2['number']}").get_json()
    assert [i["id"] for i in r["items"]] == [i2["id"]]


def test_permission_denied_when_revoked(app, world, client_for):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import UserPermission
    a = world["A"]
    pid = make_patient(app, a)
    u = a["users"]["rec_dent1"]
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        for perm in ("billing.create", "billing.view"):
            db.session.add(UserPermission(health_center_id=a["center_id"], user_id=u["id"], permission=perm,
                                          allowed=False))
        db.session.commit()
    c = client_for(u)
    assert new_invoice(c, a, pid).status_code == 403
    assert c.get(f"{BASE}/invoices").status_code == 403


def test_cross_tenant_404(app, world, client_for):
    a, b = world["A"], world["B"]
    pid = make_patient(app, a)
    inv = new_invoice(client_for(a["users"]["manager"]), a, pid).get_json()
    other = client_for(b["users"]["manager"])
    assert other.get(f"{BASE}/invoices/{inv['id']}").status_code == 404
    assert other.get(f"{BASE}/invoices/{inv['id']}/pdf").status_code == 404
    assert other.post(f"{BASE}/invoices/{inv['id']}/payments", json={"amount": "1"}).status_code == 404
    assert other.delete(f"{BASE}/invoices/{inv['id']}").status_code == 404
    assert other.get(f"{BASE}/patients/{pid}/history").status_code == 404
    assert inv["id"] not in {i["id"] for i in other.get(f"{BASE}/invoices").get_json()["items"]}
    # B cannot invoice A's patient in its own clinic
    r = other.post(f"{BASE}/invoices", json={"patient_id": pid, "clinic_id": b["clinics"]["dent1"], "items": []})
    assert r.status_code == 404


def test_delete_and_undo(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    c = client_for(a["users"]["manager"])
    inv = new_invoice(c, a, pid).get_json()
    r = c.delete(f"{BASE}/invoices/{inv['id']}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert c.get(f"{BASE}/invoices/{inv['id']}").status_code == 404
    assert inv["id"] not in {i["id"] for i in c.get(f"{BASE}/invoices").get_json()["items"]}
    assert c.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert c.get(f"{BASE}/invoices/{inv['id']}").status_code == 200
    # rec_dent (receptionist) lacks billing.delete
    assert client_for(a["users"]["rec_dent"]).delete(f"{BASE}/invoices/{inv['id']}").status_code == 403


def test_invoice_numbers_unique_under_concurrency(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    keys = ["manager", "rec_center", "rec_dent", "dent_head", "rec_multi"]
    clients = [client_for(a["users"][k]) for k in keys]
    results, errors = [], []

    def work(cl):
        for _ in range(4):
            r = new_invoice(cl, a, pid)
            if r.status_code == 201:
                results.append(r.get_json()["number"])
            else:
                errors.append(r.status_code)

    threads = [threading.Thread(target=work, args=(cl,)) for cl in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 20 and len(set(results)) == 20
    nums = sorted(int(n.split("-")[1]) for n in results)
    assert nums == list(range(nums[0], nums[0] + 20))


def test_patient_history_and_summary(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a, "dent1")
    mgr = client_for(a["users"]["manager"])
    i1 = new_invoice(mgr, a, pid, "dent1", issue=True,
                     items=[{"description": "A", "unit_price": "200.00"}]).get_json()
    i2 = new_invoice(mgr, a, pid, "dent2", issue=True,
                     items=[{"description": "B", "unit_price": "100.00", "discount_amount": "10"}]).get_json()
    new_invoice(mgr, a, pid, "dent1")  # draft: excluded from totals
    mgr.post(f"{BASE}/invoices/{i1['id']}/payments", json={"amount": "150"})
    mgr.post(f"{BASE}/invoices/{i2['id']}/payments", json={"amount": "90"})

    h = mgr.get(f"{BASE}/patients/{pid}/history").get_json()
    assert h["totals"] == {"billed": "290.00", "paid": "240.00", "outstanding": "50.00", "discounts": "10.00",
                           "invoice_count": 2}
    assert len(h["invoices"]) == 3 and len(h["payments"]) == 2

    # doctor of dent1 sees only dent1's part of the history
    doc = client_for(a["users"]["dent_doc1"])
    h = doc.get(f"{BASE}/patients/{pid}/history").get_json()
    assert h["totals"]["billed"] == "200.00" and h["totals"]["outstanding"] == "50.00"

    s = mgr.get(f"{BASE}/summary").get_json()
    assert s["totals"]["revenue"] == "290.00" and s["totals"]["payments_received"] == "240.00"
    assert s["totals"]["outstanding_total"] == "50.00" and s["currency"] == "SYP"
    s = mgr.get(f"{BASE}/summary?group_by=clinic").get_json()
    by = {r["key"]: r for r in s["rows"]}
    assert by[a["clinics"]["dent1"]]["revenue"] == "200.00" and by[a["clinics"]["dent2"]]["revenue"] == "90.00"
    assert by[a["clinics"]["dent1"]]["name"] == "Dental Clinic 1"
    s = mgr.get(f"{BASE}/summary?group_by=department").get_json()
    assert s["rows"][0]["key"] == a["departments"]["dentistry"] and s["totals"]["revenue"] == "290.00"
    s = doc.get(f"{BASE}/summary").get_json()
    assert s["totals"]["revenue"] == "200.00" and s["totals"]["payments_received"] == "150.00"
    s = mgr.get(f"{BASE}/summary?date_from=2000-01-01&date_to=2000-01-02").get_json()
    assert s["totals"]["revenue"] == "0.00" and s["totals"]["outstanding_total"] == "50.00"
    assert mgr.get(f"{BASE}/summary?date_from=2020-01-02&date_to=2020-01-01").status_code == 422
    assert mgr.get(f"{BASE}/summary?group_by=doctor").status_code == 200
