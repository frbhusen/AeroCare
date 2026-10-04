from tests.test_patients_common import expire_and_purge, mk_patient, mk_visit, platform_exec, undo

ITEMS = [{"medication_name": "Amoxicillin 500mg", "dose": "1 cap", "frequency": "3x daily", "duration": "7 days",
          "quantity": 21}]


def _rx(client, pt, clinic, expect=201, **kw):
    r = client.post("/api/v1/prescriptions", json={"patient_id": pt, "clinic_id": clinic,
                                                   "items": kw.pop("items", ITEMS), **kw})
    assert r.status_code == expect, r.get_json()
    return r.get_json()


def _setup(world, client_for):
    a = world["A"]
    pt = mk_patient(client_for(a["users"]["manager"]), a["clinics"]["dent1"], "Rx Patient")
    return a, pt["id"]


def test_create_list_get(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    v = mk_visit(doc, pt, a["clinics"]["dent1"])
    rx = _rx(doc, pt, a["clinics"]["dent1"], visit_id=v["id"], notes="after extraction",
             items=ITEMS + [{"medication_name": "Ibuprofen", "quantity": "10.5"}])
    assert rx["status"] == "pending" and rx["visit_id"] == v["id"] and rx["author_role"] == "doctor"
    assert [i["medication_name"] for i in rx["items"]] == ["Amoxicillin 500mg", "Ibuprofen"]
    assert rx["items"][1]["quantity"] == "10.50" and rx["items"][0]["dispensed_quantity"] == "0.00"
    assert doc.get(f"/api/v1/prescriptions/{rx['id']}").get_json()["id"] == rx["id"]
    items = doc.get("/api/v1/prescriptions", query_string={"patient_id": pt}).get_json()["items"]
    assert [x["id"] for x in items] == [rx["id"]]
    items = doc.get("/api/v1/prescriptions", query_string={"status": "pending"}).get_json()["items"]
    assert [x["id"] for x in items] == [rx["id"]] and items[0]["patient"]["full_name"] == "Rx Patient"
    # Summary section
    s = doc.get(f"/api/v1/patients/{pt}/summary").get_json()
    assert [x for x in s["sections"] if x["name"] == "prescriptions"][0]["data"]["items"][0]["id"] == rx["id"]


def test_validation_permission_scope(app, world, client_for):
    a, pt = _setup(world, client_for)
    u = a["users"]
    doc = client_for(u["dent_doc1"])
    _rx(doc, pt, a["clinics"]["dent1"], items=[], expect=422)
    _rx(doc, pt, a["clinics"]["dent1"], items=[{"dose": "x"}], expect=422)
    _rx(doc, pt, a["clinics"]["dent1"], items=[{"medication_name": "A", "quantity": -1}], expect=422)
    _rx(client_for(u["rec_dent1"]), pt, a["clinics"]["dent1"], expect=403)
    _rx(doc, pt, a["clinics"]["dent2"], expect=404)
    _rx(client_for(u["derm_doc"]), pt, a["clinics"]["derm1"], expect=404)  # patient not visible
    # Visit from another clinic is rejected.
    doc2 = client_for(u["dent_doc2"])
    doc2.post(f"/api/v1/patients/{pt}/link", json={"clinic_id": a["clinics"]["dent2"]})
    v2 = mk_visit(doc2, pt, a["clinics"]["dent2"])
    _rx(doc, pt, a["clinics"]["dent1"], visit_id=v2["id"], expect=404)
    rx2 = _rx(doc2, pt, a["clinics"]["dent2"], visit_id=v2["id"])
    # Clinic isolation and tenant isolation
    assert doc.get(f"/api/v1/prescriptions/{rx2['id']}").status_code == 404
    assert doc.get("/api/v1/prescriptions", query_string={"patient_id": pt}).get_json()["items"] == []
    assert client_for(u["dent_head"]).get(f"/api/v1/prescriptions/{rx2['id']}").status_code == 200
    assert client_for(u["derm_doc"]).get(f"/api/v1/prescriptions/{rx2['id']}").status_code == 404
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f"/api/v1/prescriptions/{rx2['id']}").status_code == 404
    assert b.put(f"/api/v1/prescriptions/{rx2['id']}", json={"version": 1, "notes": "x"}).status_code == 404
    assert b.get("/api/v1/prescriptions").get_json()["items"] == []


def test_edit_while_pending_conflict_cancel(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    rx = _rx(doc, pt, a["clinics"]["dent1"])
    url = f"/api/v1/prescriptions/{rx['id']}"
    r = doc.put(url, json={"version": 1, "items": [{"medication_name": "Paracetamol", "quantity": 10}]})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["version"] == 2 and [i["medication_name"] for i in body["items"]] == ["Paracetamol"]
    assert doc.put(url, json={"version": 1, "notes": "stale"}).status_code == 409
    assert client_for(a["users"]["rec_dent1"]).put(url, json={"version": 2, "notes": "x"}).status_code == 403
    r = doc.post(url + "/cancel", json={"version": 2})
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    r = doc.put(url, json={"version": 3, "notes": "after cancel"})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "prescription_not_pending"
    assert doc.post(url + "/cancel", json={"version": 3}).status_code == 422


def test_delete_undo_and_dispensed_protected(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    rx = _rx(doc, pt, a["clinics"]["dent1"])
    url = f"/api/v1/prescriptions/{rx['id']}"
    assert client_for(a["users"]["rec_dent1"]).delete(url).status_code == 403
    r = doc.delete(url)
    assert r.status_code == 202
    assert doc.get(url).status_code == 404
    assert undo(doc, r.get_json()["undo_token"]).status_code == 200
    assert doc.get(url).status_code == 200

    from backend.app.models import Prescription
    def mark(db):
        db.session.get(Prescription, rx["id"]).status = "dispensed"
    platform_exec(app, mark)
    r = doc.delete(url)
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "prescription_dispensed"

    rx2 = _rx(doc, pt, a["clinics"]["dent1"])
    assert doc.delete(f"/api/v1/prescriptions/{rx2['id']}").status_code == 202
    expire_and_purge(app)
    assert platform_exec(app, lambda db: db.session.get(Prescription, rx2["id"])) is None


def test_visit_purge_keeps_prescription(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    v = mk_visit(doc, pt, a["clinics"]["dent1"])
    rx = _rx(doc, pt, a["clinics"]["dent1"], visit_id=v["id"])
    assert doc.delete(f"/api/v1/visits/{v['id']}").status_code == 202
    expire_and_purge(app)
    got = doc.get(f"/api/v1/prescriptions/{rx['id']}").get_json()
    assert got["visit_id"] is None


def test_patient_purge_with_history(app, world, client_for):
    from backend.app.models import Patient, Prescription
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    v = mk_visit(doc, pt, a["clinics"]["dent1"])
    rx = _rx(doc, pt, a["clinics"]["dent1"], visit_id=v["id"])
    assert client_for(a["users"]["manager"]).delete(f"/api/v1/patients/{pt}").status_code == 202
    expire_and_purge(app)
    assert platform_exec(app, lambda db: db.session.get(Patient, pt)) is None
    assert platform_exec(app, lambda db: db.session.get(Prescription, rx["id"])) is None


def test_prescription_pdf(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    rx = _rx(doc, pt, a["clinics"]["dent1"], notes="بعد الطعام",
             items=[{"medication_name": "أموكسيسيلين", "dose": "500mg", "quantity": 21, "instructions": "x"}])
    for lang in ("en", "ar"):
        r = doc.get(f"/api/v1/prescriptions/{rx['id']}/pdf", query_string={"lang": lang})
        assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:4] == b"%PDF"
    assert client_for(a["users"]["dent_doc2"]).get(f"/api/v1/prescriptions/{rx['id']}/pdf").status_code == 404
    assert client_for(world["B"]["users"]["manager"]).get(f"/api/v1/prescriptions/{rx['id']}/pdf").status_code == 404
