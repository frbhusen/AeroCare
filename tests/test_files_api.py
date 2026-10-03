from tests.test_patients_common import PDF, PNG, expire_and_purge, mk_patient, platform_exec, undo, upload


def _setup(world, client_for):
    a = world["A"]
    pt = mk_patient(client_for(a["users"]["manager"]), a["clinics"]["dent1"], "File Patient")
    return a, pt["id"]


def test_upload_list_content(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    out = upload(doc, pt, a["clinics"]["dent1"], files=[(PNG, "xray 1.png"), (PDF, "report.pdf"),
                                                        (b"plain notes", "notes.txt")], category="xray")
    items = out["items"]
    assert [f["mime_type"] for f in items] == ["image/png", "application/pdf", "text/plain"]
    assert out["storage"]["used_bytes"] >= len(PNG) + len(PDF)
    lst = doc.get("/api/v1/files", query_string={"patient_id": pt}).get_json()
    assert lst["total"] == 3 and lst["items"][0]["clinic_name"] == "Dental Clinic 1"
    assert doc.get("/api/v1/files", query_string={"patient_id": pt, "images_only": "1"}).get_json()["total"] == 1
    png, pdf, txt = items
    r = doc.get(png["url"])
    assert r.status_code == 200 and r.data == PNG and r.mimetype == "image/png"
    assert r.headers["Content-Disposition"].startswith("inline")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    r = doc.get(txt["url"])
    assert r.headers["Content-Disposition"].startswith("attachment") and r.data == b"plain notes"
    assert doc.get(pdf["url"], query_string={"download": "1"}).headers["Content-Disposition"].startswith("attachment")
    # Receptionist in scope can view and upload.
    rec = client_for(a["users"]["rec_dent1"])
    assert rec.get(png["url"]).status_code == 200
    upload(rec, pt, a["clinics"]["dent1"])
    assert doc.get("/api/v1/files/storage").get_json()["quota_bytes"] > 0
    s = doc.get(f"/api/v1/patients/{pt}/summary").get_json()
    assert len([x for x in s["sections"] if x["name"] == "files"][0]["data"]["items"]) == 4


def test_rejects_spoofed_and_disallowed_types(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    r = upload(doc, pt, a["clinics"]["dent1"], files=[(b"<html><script>alert(1)</script></html>", "x.png")],
               expect=422)
    assert r["error"]["code"] == "file_content_mismatch"
    r = upload(doc, pt, a["clinics"]["dent1"], files=[(b"<script>alert(1)</script>", "x.txt")], expect=422)
    assert r["error"]["code"] == "file_content_mismatch"
    r = upload(doc, pt, a["clinics"]["dent1"], files=[(b"MZ\x90\x00", "tool.exe")], expect=422)
    assert r["error"]["code"] == "file_type_not_allowed"
    r = upload(doc, pt, a["clinics"]["dent1"], files=[(b"<svg onload=alert(1)>", "a.svg")], expect=422)
    # A batch with one bad file stores nothing.
    upload(doc, pt, a["clinics"]["dent1"], files=[(PNG, "ok.png"), (b"MZ", "bad.exe")], expect=422)
    assert doc.get("/api/v1/files", query_string={"patient_id": pt}).get_json()["total"] == 0
    r = doc.post("/api/v1/files", data={"patient_id": str(pt), "clinic_id": str(a["clinics"]["dent1"])},
                 content_type="multipart/form-data")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "no_files"


def test_quota_exceeded(app, world, client_for):
    from backend.app.models import HealthCenter
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    upload(doc, pt, a["clinics"]["dent1"])

    def shrink(db):
        db.session.get(HealthCenter, a["center_id"]).storage_quota_bytes = len(PNG) + 10
    platform_exec(app, shrink)
    r = upload(doc, pt, a["clinics"]["dent1"], expect=422)
    assert r["error"]["code"] == "quota_exceeded"
    assert doc.get("/api/v1/files", query_string={"patient_id": pt}).get_json()["total"] == 1


def test_unauthorized_access_rejected(app, world, client_for):
    a, pt = _setup(world, client_for)
    u = a["users"]
    doc = client_for(u["dent_doc1"])
    f = upload(doc, pt, a["clinics"]["dent1"])["items"][0]
    # Upload target checks: clinic out of scope, patient not visible, other tenant.
    upload(doc, pt, a["clinics"]["dent2"], expect=404)
    upload(client_for(u["derm_doc"]), pt, a["clinics"]["derm1"], expect=404)
    upload(client_for(world["B"]["users"]["manager"]), pt, world["B"]["clinics"]["dent1"], expect=404)
    for k in ("dent_doc2", "derm_doc", "gen_doc"):
        c = client_for(u[k])
        assert c.get(f["url"]).status_code == 404, k
        assert c.get(f"/api/v1/files/{f['id']}").status_code == 404, k
        assert c.get("/api/v1/files", query_string={"patient_id": pt}).get_json()["total"] == 0, k
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f["url"]).status_code == 404
    assert b.patch(f"/api/v1/files/{f['id']}", json={"version": 1, "display_name": "x"}).status_code == 404
    assert b.delete(f"/api/v1/files/{f['id']}").status_code == 404
    assert b.get("/api/v1/files").get_json()["total"] == 0
    for k in ("dent_head", "manager", "rec_dent"):
        assert client_for(u[k]).get(f["url"]).status_code == 200, k
    # Unauthenticated
    from tests.conftest import ApiClient
    assert ApiClient(app).get(f["url"]).status_code == 401


def test_share_and_unshare(app, world, client_for):
    a, pt = _setup(world, client_for)
    u = a["users"]
    doc = client_for(u["dent_doc1"])
    f = upload(doc, pt, a["clinics"]["dent1"])["items"][0]
    doc2 = client_for(u["dent_doc2"])
    derm = client_for(u["derm_doc"])
    # Receptionist (no files.share) cannot share; dent_doc2 (not owner) cannot.
    assert client_for(u["rec_dent1"]).post(f"/api/v1/files/{f['id']}/shares",
                                           json={"target_type": "clinic", "target_id": 1}).status_code == 403
    assert doc2.post(f"/api/v1/files/{f['id']}/shares",
                     json={"target_type": "clinic", "target_id": a["clinics"]["dent2"]}).status_code == 404
    # Other-tenant target rejected.
    assert doc.post(f"/api/v1/files/{f['id']}/shares", json={"target_type": "clinic",
                                                             "target_id": world["B"]["clinics"]["dent1"]}
                    ).status_code == 404
    r = doc.post(f"/api/v1/files/{f['id']}/shares", json={"target_type": "clinic", "target_id": a["clinics"]["dent2"]})
    assert r.status_code == 201 and r.get_json()["target_name"] == "Dental Clinic 2"
    share_id = r.get_json()["id"]
    r2 = doc.post(f"/api/v1/files/{f['id']}/shares", json={"target_type": "user", "target_id": u["derm_doc"]["id"]})
    assert r2.status_code == 201
    assert doc2.get(f["url"]).status_code == 200 and derm.get(f["url"]).status_code == 200
    # Shared viewers cannot manage the file.
    r = doc2.patch(f"/api/v1/files/{f['id']}", json={"version": 1, "display_name": "mine"})
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "file_not_managed"
    assert doc2.delete(f"/api/v1/files/{f['id']}").status_code == 403
    assert len(doc.get(f"/api/v1/files/{f['id']}/shares").get_json()["items"]) == 2
    assert doc.delete(f"/api/v1/files/{f['id']}/shares/{share_id}").status_code == 200
    assert doc2.get(f["url"]).status_code == 404
    assert derm.get(f["url"]).status_code == 200
    t = doc.get("/api/v1/files/share-targets").get_json()
    assert {c["id"] for c in t["clinics"]} >= {a["clinics"]["dent2"], a["clinics"]["derm1"]}


def test_rename_annotate_conflict(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    f = upload(doc, pt, a["clinics"]["dent1"])["items"][0]
    url = f"/api/v1/files/{f['id']}"
    r = doc.patch(url, json={"version": 1, "display_name": "../../etc/passwd"})
    assert r.status_code == 200 and r.get_json()["display_name"] == "passwd.png"
    assert doc.patch(url, json={"version": 1, "display_name": "stale"}).status_code == 409
    ann = [{"type": "arrow", "points": [1, 2, 30, 40], "color": "#ff0000", "text": "caries"}]
    r = doc.put(url + "/annotations", json={"version": 2, "annotations": ann})
    assert r.status_code == 200 and r.get_json()["annotations"] == ann and r.get_json()["version"] == 3
    assert doc.put(url + "/annotations", json={"version": 3, "annotations": [{"type": "script"}]}).status_code == 422
    assert doc.put(url + "/annotations", json={"version": 3,
                                               "annotations": [{"type": "text", "color": "red"}]}).status_code == 422
    assert doc.put(url + "/annotations", json={"version": 2, "annotations": []}).status_code == 409
    rec = client_for(a["users"]["rec_dent1"])
    assert rec.patch(url, json={"version": 3, "display_name": "x"}).status_code == 403
    r = doc.get(f["url"])
    assert "passwd.png" in r.headers["Content-Disposition"]


def test_delete_undo_and_purge(app, world, client_for):
    from backend.app.core.storage import get_storage
    from backend.app.models import StoredFile
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    f = upload(doc, pt, a["clinics"]["dent1"])["items"][0]
    url = f"/api/v1/files/{f['id']}"
    assert client_for(a["users"]["rec_dent1"]).delete(url).status_code == 403
    r = doc.delete(url)
    assert r.status_code == 202
    assert doc.get(f["url"]).status_code == 404
    assert doc.get("/api/v1/files", query_string={"patient_id": pt}).get_json()["total"] == 0
    assert undo(doc, r.get_json()["undo_token"]).status_code == 200
    resp = doc.get(f["url"])
    assert resp.status_code == 200
    resp.close()  # release the file handle (Windows cannot unlink open files)
    key = platform_exec(app, lambda db: db.session.get(StoredFile, f["id"]).storage_key)
    assert doc.delete(url).status_code == 202
    expire_and_purge(app)
    with app.app_context():
        assert not get_storage().exists(key)
    assert platform_exec(app, lambda db: db.session.get(StoredFile, f["id"])) is None


def test_patient_purge_removes_file_bytes(app, world, client_for):
    from backend.app.core.storage import get_storage
    from backend.app.models import StoredFile
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["dent_doc1"])
    v = doc.post("/api/v1/visits", json={"patient_id": pt, "clinic_id": a["clinics"]["dent1"]}).get_json()
    f = upload(doc, pt, a["clinics"]["dent1"], visit_id=v["id"])["items"][0]
    key = platform_exec(app, lambda db: db.session.get(StoredFile, f["id"]).storage_key)
    assert client_for(a["users"]["manager"]).delete(f"/api/v1/patients/{pt}").status_code == 202
    expire_and_purge(app)
    with app.app_context():
        assert not get_storage().exists(key)
    assert platform_exec(app, lambda db: db.session.get(StoredFile, f["id"])) is None
