from tests.test_billing_helpers import BASE, make_patient, new_invoice


def _svc(c, **kw):
    body = {"name": "Teeth cleaning", "price": "100.00", "cost": "20.00", "category": "Hygiene",
            "kind": "treatment", "duration_minutes": 30}
    body.update(kw)
    return c.post(f"{BASE}/services", json=body)


def test_service_crud_and_price_inheritance(app, world, client_for):
    a = world["A"]
    mgr = client_for(a["users"]["manager"])
    r = _svc(mgr, department_id=a["departments"]["dentistry"])
    assert r.status_code == 201, r.get_json()
    s = r.get_json()
    assert s["level"] == "department" and s["price"] == "100.00"
    center_svc = _svc(mgr, name="Consultation", price="50").get_json()
    assert center_svc["level"] == "center"

    # department override then clinic override
    r = mgr.put(f"{BASE}/services/{s['id']}/prices", json={"department_id": a["departments"]["dentistry"],
                                                           "price": "90.00"})
    assert r.status_code == 200
    r = mgr.put(f"{BASE}/services/{s['id']}/prices", json={"clinic_id": a["clinics"]["dent2"], "price": "80.00"})
    assert r.status_code == 200
    clinic_price_id = r.get_json()["id"]
    r = mgr.put(f"{BASE}/services/{s['id']}/prices", json={"clinic_id": a["clinics"]["dent2"], "price": "85.00"})
    assert r.get_json()["id"] == clinic_price_id and r.get_json()["price"] == "85.00"  # upsert
    ep = lambda ck: mgr.get(f"{BASE}/services/{s['id']}/effective-price?clinic_id={a['clinics'][ck]}").get_json()
    assert ep("dent1") == {"service_id": s["id"], "clinic_id": a["clinics"]["dent1"], "price": "90.00",
                           "source": "department"}
    assert ep("dent2")["price"] == "85.00" and ep("dent2")["source"] == "clinic"
    # not applicable in dermatology
    r = mgr.get(f"{BASE}/services/{s['id']}/effective-price?clinic_id={a['clinics']['derm1']}")
    assert r.status_code == 422
    # exactly one level
    assert mgr.put(f"{BASE}/services/{s['id']}/prices", json={"price": "1"}).status_code == 422

    # list applicable to a clinic includes effective prices; derm clinic only sees center service
    lst = mgr.get(f"{BASE}/services?clinic_id={a['clinics']['dent2']}").get_json()["items"]
    byid = {x["id"]: x for x in lst}
    assert byid[s["id"]]["effective_price"] == "85.00" and byid[center_svc["id"]]["effective_price"] == "50.00"
    lst = mgr.get(f"{BASE}/services?clinic_id={a['clinics']['derm1']}").get_json()["items"]
    assert {x["id"] for x in lst} >= {center_svc["id"]} and s["id"] not in {x["id"] for x in lst}

    # invoice line from a service uses the effective price; custom price allowed
    pid = make_patient(app, a, "dent2")
    inv = new_invoice(mgr, a, pid, "dent2", items=[{"service_id": s["id"]},
                                                   {"service_id": s["id"], "unit_price": "60.00"}]).get_json()
    assert [i["unit_price"] for i in inv["items"]] == ["85.00", "60.00"]
    assert inv["items"][0]["description"] == "Teeth cleaning" and inv["items"][0]["kind"] == "treatment"
    assert inv["items"][1]["list_price"] == "85.00"
    # service from another department rejected on the invoice
    derm = _svc(mgr, name="Peel", department_id=a["departments"]["dermatology"]).get_json()
    r = new_invoice(mgr, a, pid, "dent2", items=[{"service_id": derm["id"]}])
    assert r.status_code == 422

    # update with version, conflict
    r = mgr.put(f"{BASE}/services/{s['id']}", json={"version": s["version"], "price": "110", "is_active": False})
    assert r.status_code == 200 and r.get_json()["price"] == "110.00" and r.get_json()["is_active"] is False
    r = mgr.put(f"{BASE}/services/{s['id']}", json={"version": s["version"], "price": "120"})
    assert r.status_code == 409
    # remove clinic override -> falls back to department
    assert mgr.delete(f"{BASE}/services/{s['id']}/prices/{clinic_price_id}").status_code == 200
    assert ep("dent2")["source"] == "department"

    # delete + undo
    r = mgr.delete(f"{BASE}/services/{s['id']}")
    assert r.status_code == 202
    assert mgr.get(f"{BASE}/services/{s['id']}").status_code == 404
    assert mgr.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    assert mgr.get(f"{BASE}/services/{s['id']}").status_code == 200


def test_service_permissions_and_scope(app, world, client_for):
    a, b = world["A"], world["B"]
    mgr = client_for(a["users"]["manager"])
    dent = _svc(mgr, department_id=a["departments"]["dentistry"]).get_json()
    derm = _svc(mgr, name="Derm", department_id=a["departments"]["dermatology"]).get_json()
    # doctor: billing.view but no services.manage
    doc = client_for(a["users"]["dent_doc1"])
    assert _svc(doc, clinic_id=a["clinics"]["dent1"]).status_code == 403
    ids = {x["id"] for x in doc.get(f"{BASE}/services").get_json()["items"]}
    assert dent["id"] in ids and derm["id"] not in ids
    assert doc.get(f"{BASE}/services/{derm['id']}").status_code == 404
    # department manager manages own department only; cannot create center-wide services
    head = client_for(a["users"]["dent_head"])
    assert _svc(head, clinic_id=a["clinics"]["dent2"]).status_code == 201
    assert _svc(head, department_id=a["departments"]["dermatology"]).status_code == 404
    assert _svc(head).status_code == 403
    assert head.put(f"{BASE}/services/{dent['id']}/prices",
                    json={"clinic_id": a["clinics"]["derm1"], "price": "1"}).status_code == 404
    # cross-tenant
    other = client_for(b["users"]["manager"])
    assert other.get(f"{BASE}/services/{dent['id']}").status_code == 404
    assert other.put(f"{BASE}/services/{dent['id']}", json={"version": 1, "price": "1"}).status_code == 404
    assert other.delete(f"{BASE}/services/{dent['id']}").status_code == 404
    # validation
    assert _svc(mgr, price="-1").status_code == 422
    assert _svc(mgr, name="").status_code == 422
    assert _svc(mgr, clinic_id=a["clinics"]["dent1"], department_id=a["departments"]["dermatology"]
                ).status_code == 422


def test_meta(app, world, client_for):
    a = world["A"]
    r = client_for(a["users"]["rec_dent1"]).get(f"{BASE}/meta").get_json()
    assert r["payment_methods"] == ["cash"] and r["currency"] == "SYP" and "draft" in r["invoice_statuses"]
    assert r["can"]["billing.create"] is True and r["can"]["billing.delete"] is False
