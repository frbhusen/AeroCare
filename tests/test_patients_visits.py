from tests.test_patients_common import PNG, expire_and_purge, mk_patient, mk_visit, undo, upload


def _setup(world, client_for):
    a = world["A"]
    pt = mk_patient(client_for(a["users"]["manager"]), a["clinics"]["dent1"], "Visit Patient")
    return a, pt


def test_create_list_get_visits_scoped(app, world, client_for):
    a, pt = _setup(world, client_for)
    u = a["users"]
    doc1 = client_for(u["dent_doc1"])
    v = mk_visit(doc1, pt["id"], a["clinics"]["dent1"], visit_type="follow_up", title="Check",
                 visit_at="2026-10-01T10:00:00")
    assert v["author_name"] and v["clinic_name"] == "Dental Clinic 1" and v["environment"] == "dentistry"
    assert v["visit_at"].startswith("2026-10-01T07:00:00")  # Damascus local -> UTC
    # dent_doc2 links the patient to dent2 and creates a visit there.
    doc2 = client_for(u["dent_doc2"])
    doc2.post(f"/api/v1/patients/{pt['id']}/link", json={"clinic_id": a["clinics"]["dent2"]})
    v2 = mk_visit(doc2, pt["id"], a["clinics"]["dent2"], title="Other clinic")
    # Clinic isolation: each doctor sees only their clinic's visits.
    t1 = [x["title"] for x in doc1.get(f"/api/v1/patients/{pt['id']}/visits").get_json()["items"]]
    t2 = [x["title"] for x in doc2.get(f"/api/v1/patients/{pt['id']}/visits").get_json()["items"]]
    assert t1 == ["Check"] and t2 == ["Other clinic"]
    assert doc2.get(f"/api/v1/visits/{v['id']}").status_code == 404
    # Department manager and dentistry receptionist see both; derm doctor nothing.
    for k in ("dent_head", "rec_dent", "manager"):
        items = client_for(u[k]).get("/api/v1/visits", query_string={"patient_id": pt["id"]}).get_json()["items"]
        assert {x["id"] for x in items} == {v["id"], v2["id"]}, k
    rec1 = client_for(u["rec_dent1"])
    assert [x["id"] for x in rec1.get("/api/v1/visits").get_json()["items"]] == [v["id"]]
    assert client_for(u["derm_doc"]).get(f"/api/v1/visits/{v['id']}").status_code == 404
    assert client_for(u["derm_doc"]).get(f"/api/v1/patients/{pt['id']}/visits").status_code == 404
    # Filters
    r = client_for(u["manager"]).get("/api/v1/visits", query_string={"clinic_id": a["clinics"]["dent2"]})
    assert [x["id"] for x in r.get_json()["items"]] == [v2["id"]]
    assert r.get_json()["items"][0]["patient"]["full_name"] == "Visit Patient"
    r = client_for(u["manager"]).get("/api/v1/visits", query_string={"date_from": "2026-10-01",
                                                                     "date_to": "2026-10-01"})
    assert [x["id"] for x in r.get_json()["items"]] == [v["id"]]


def test_visit_permissions_and_tenancy(app, world, client_for):
    a, pt = _setup(world, client_for)
    u = a["users"]
    # Receptionists lack medical_records.create.
    mk_visit(client_for(u["rec_dent1"]), pt["id"], a["clinics"]["dent1"], expect=403)
    # Clinic outside scope -> 404 ; patient not visible -> 404.
    mk_visit(client_for(u["dent_doc1"]), pt["id"], a["clinics"]["dent2"], expect=404)
    mk_visit(client_for(u["derm_doc"]), pt["id"], a["clinics"]["derm1"], expect=404)
    v = mk_visit(client_for(u["dent_doc1"]), pt["id"], a["clinics"]["dent1"])
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f"/api/v1/visits/{v['id']}").status_code == 404
    assert b.patch(f"/api/v1/visits/{v['id']}", json={"version": 1, "title": "x"}).status_code == 404
    assert b.delete(f"/api/v1/visits/{v['id']}").status_code == 404
    mk_visit(b, pt["id"], world["B"]["clinics"]["dent1"], expect=404)
    assert client_for(u["dent_doc1"]).post("/api/v1/visits", json={"patient_id": pt["id"],
                                                                   "clinic_id": a["clinics"]["dent1"],
                                                                   "visit_type": "bogus"}).status_code == 422


def test_edit_complete_conflict(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    v = mk_visit(doc, pt["id"], a["clinics"]["dent1"])
    url = f"/api/v1/visits/{v['id']}"
    r = doc.patch(url, json={"version": 1, "notes": "updated", "visit_type": "treatment"})
    assert r.status_code == 200 and r.get_json()["version"] == 2 and r.get_json()["notes"] == "updated"
    assert doc.patch(url, json={"version": 1, "notes": "stale"}).status_code == 409
    r = doc.post(url + "/complete", json={"version": 2})
    assert r.status_code == 200 and r.get_json()["status"] == "completed"
    assert doc.post(url + "/reopen", json={"version": 2}).status_code == 409
    assert doc.post(url + "/reopen", json={"version": 3}).get_json()["status"] == "open"
    # Receptionist can view but not edit (no medical_records.edit).
    rec = client_for(a["users"]["rec_dent1"])
    assert rec.get(url).status_code == 200
    assert rec.patch(url, json={"version": 4, "notes": "x"}).status_code == 403


def test_delete_undo_and_purge_removes_attached_files(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    v = mk_visit(doc, pt["id"], a["clinics"]["dent1"])
    url = f"/api/v1/visits/{v['id']}"
    assert client_for(a["users"]["rec_dent1"]).delete(url).status_code == 403
    r = doc.delete(url)
    assert r.status_code == 202
    assert doc.get(url).status_code == 404
    assert undo(doc, r.get_json()["undo_token"]).status_code == 200
    assert doc.get(url).status_code == 200
    # Attach a file, delete, purge: visit and file gone, bytes removed.
    f = upload(doc, pt["id"], a["clinics"]["dent1"], files=[(PNG, "v.png")], visit_id=v["id"])["items"][0]
    from backend.app.core.storage import get_storage
    from backend.app.models import StoredFile
    from tests.test_patients_common import platform_exec
    key = platform_exec(app, lambda db: db.session.get(StoredFile, f["id"]).storage_key)
    with app.app_context():
        assert get_storage().exists(key)
    assert doc.delete(url).status_code == 202
    expire_and_purge(app)
    expire_and_purge(app)
    with app.app_context():
        assert not get_storage().exists(key)
    assert platform_exec(app, lambda db: db.session.get(StoredFile, f["id"])) is None
    assert doc.get(url).status_code == 404
