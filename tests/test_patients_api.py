import threading

from tests.conftest import ApiClient
from tests.test_patients_common import mk_patient, mk_visit, undo


def test_create_get_and_sequential_codes(app, world, client_for):
    a = world["A"]
    rec = client_for(a["users"]["rec_dent1"])
    p1 = mk_patient(rec, a["clinics"]["dent1"], "Ali Ahmad", phone="+963 944 123 456", gender="male",
                    date_of_birth="1990-05-01", blood_type="A+", allergies="Penicillin")
    p2 = mk_patient(rec, a["clinics"]["dent1"], "Sara Ali")
    assert p1["display_code"] == "PAT-000001" and p2["code"] == 2
    assert p1["version"] == 1 and p1["allergies"] == "Penicillin"
    assert [d["environment"] for d in p1["departments"]] == ["dentistry"]
    assert p1["departments"][0]["accessible"] is True
    r = rec.get(f"/api/v1/patients/{p1['id']}")
    assert r.status_code == 200 and r.get_json()["phone"] == "+963 944 123 456"
    # Codes are per center: center B starts at 1 again.
    b = client_for(world["B"]["users"]["manager"])
    assert mk_patient(b, world["B"]["clinics"]["gen1"], "Other")["code"] == 1


def test_create_validation_and_scope(app, world, client_for):
    a = world["A"]
    rec = client_for(a["users"]["rec_dent1"])
    r = rec.post("/api/v1/patients", json={"clinic_id": a["clinics"]["dent1"]})
    assert r.status_code == 422 and "full_name" in r.get_json()["error"]["details"]
    r = rec.post("/api/v1/patients", json={"full_name": "X Y", "clinic_id": a["clinics"]["dent1"], "gender": "x"})
    assert r.status_code == 422
    r = rec.post("/api/v1/patients", json={"full_name": "X Y", "clinic_id": a["clinics"]["dent1"],
                                           "date_of_birth": "2999-01-01"})
    assert r.status_code == 422
    r = rec.post("/api/v1/patients", json={"full_name": "X Y", "clinic_id": a["clinics"]["dent1"],
                                           "phone": "<script>"})
    assert r.status_code == 422
    # Clinic outside the receptionist's scope -> 404; other center's clinic -> 404.
    mk_patient(rec, a["clinics"]["dent2"], expect=404)
    mk_patient(rec, world["B"]["clinics"]["dent1"], expect=404)


def test_search_name_phone_and_arabic_normalization(app, world, client_for):
    a = world["A"]
    mgr = client_for(a["users"]["manager"])
    mk_patient(mgr, a["clinics"]["gen1"], "أحمد علي", phone="0944-111-222")
    mk_patient(mgr, a["clinics"]["gen1"], "Ahmad Kassem", phone="0933 555 666")
    mk_patient(mgr, a["clinics"]["gen1"], "Kassem Ahmad")
    names = lambda r: [i["full_name"] for i in r.get_json()["items"]]  # noqa: E731
    r = mgr.get("/api/v1/patients", query_string={"q": "احمد"})  # hamza folding
    assert r.status_code == 200 and names(r) == ["أحمد علي"]
    assert names(mgr.get("/api/v1/patients", query_string={"q": "111222"})) == ["أحمد علي"]
    assert names(mgr.get("/api/v1/patients", query_string={"q": "0944"})) == ["أحمد علي"]
    r = mgr.get("/api/v1/patients", query_string={"q": "ahmad"})
    assert names(r)[0] == "Ahmad Kassem" and set(names(r)) == {"Ahmad Kassem", "Kassem Ahmad"}  # prefix first
    assert set(names(mgr.get("/api/v1/patients", query_string={"q": "kassem ahm"}))) == {"Ahmad Kassem",
                                                                                         "Kassem Ahmad"}
    assert names(mgr.get("/api/v1/patients", query_string={"q": "ka"}))[0] in ("Ahmad Kassem", "Kassem Ahmad")
    # LIKE wildcards are literal.
    assert names(mgr.get("/api/v1/patients", query_string={"q": "%"})) == []
    r = mgr.get("/api/v1/patients", query_string={"per_page": 2})
    body = r.get_json()
    assert len(body["items"]) == 2 and body["has_more"] is True


def test_tenant_isolation(app, world, client_for):
    a, b = world["A"], world["B"]
    pa = mk_patient(client_for(a["users"]["manager"]), a["clinics"]["dent1"], "Tenant Secret")
    bm = client_for(b["users"]["manager"])
    assert bm.get(f"/api/v1/patients/{pa['id']}").status_code == 404
    assert bm.patch(f"/api/v1/patients/{pa['id']}", json={"version": 1, "full_name": "Hacked"}).status_code == 404
    assert bm.delete(f"/api/v1/patients/{pa['id']}").status_code == 404
    assert bm.get(f"/api/v1/patients/{pa['id']}/summary").status_code == 404
    assert bm.get("/api/v1/patients", query_string={"q": "Tenant Secret"}).get_json()["items"] == []
    assert bm.get("/api/v1/patients/lookup", query_string={"q": "Tenant Secret"}).get_json()["items"] == []
    assert bm.post(f"/api/v1/patients/{pa['id']}/link",
                   json={"clinic_id": b["clinics"]["dent1"]}).status_code == 404


def test_clinic_department_and_receptionist_scopes(app, world, client_for):
    a = world["A"]
    u = a["users"]
    pt = mk_patient(client_for(u["rec_dent1"]), a["clinics"]["dent1"], "Scoped Patient")
    url = f"/api/v1/patients/{pt['id']}"
    allowed = ["dent_doc1", "dent_head", "manager", "rec_dent1", "rec_dent", "rec_multi", "rec_center"]
    denied = ["dent_doc2", "derm_doc", "gen_doc", "lab_doc"]
    for key in allowed:
        assert client_for(u[key]).get(url).status_code == 200, key
    for key in denied:
        c = client_for(u[key])
        assert c.get(url).status_code == 404, key
        assert c.get("/api/v1/patients", query_string={"q": "Scoped"}).get_json()["items"] == [], key
    # Department manager of dentistry lists only dentistry patients.
    mk_patient(client_for(u["derm_doc"]), a["clinics"]["derm1"], "Derm Only")
    head = client_for(u["dent_head"])
    listed = [i["full_name"] for i in head.get("/api/v1/patients").get_json()["items"]]
    assert "Scoped Patient" in listed and "Derm Only" not in listed
    # rec_dent1 cannot filter by a clinic outside scope.
    assert client_for(u["rec_dent1"]).get("/api/v1/patients",
                                           query_string={"clinic_id": a["clinics"]["dent2"]}).status_code == 404


def test_lookup_and_link_existing_patient(app, world, client_for):
    a = world["A"]
    pt = mk_patient(client_for(a["users"]["rec_dent1"]), a["clinics"]["dent1"], "Lina Haddad",
                    phone="0944 987 654", date_of_birth="1985-02-03")
    derm = client_for(a["users"]["derm_doc"])
    r = derm.get("/api/v1/patients/lookup", query_string={"q": "lina"})
    items = r.get_json()["items"]
    assert len(items) == 1 and items[0]["phone_masked"] == "*******654" and items[0]["accessible"] is False
    assert set(items[0]) == {"id", "code", "display_code", "full_name", "date_of_birth", "gender", "phone_masked",
                             "accessible"}
    assert derm.get(f"/api/v1/patients/{pt['id']}").status_code == 404
    # Link into a clinic outside scope is rejected; into own clinic works.
    assert derm.post(f"/api/v1/patients/{pt['id']}/link", json={"clinic_id": a["clinics"]["dent1"]}).status_code == 404
    r = derm.post(f"/api/v1/patients/{pt['id']}/link", json={"clinic_id": a["clinics"]["derm1"]})
    assert r.status_code == 200
    assert derm.get(f"/api/v1/patients/{pt['id']}").status_code == 200
    # Lookup requires patients.create.
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import UserPermission
    with app.app_context(), tenancy.scoped("platform"):
        db.session.add(UserPermission(health_center_id=a["center_id"], user_id=a["users"]["gen_doc"]["id"],
                                      permission="patients.create", allowed=False))
        db.session.commit()
    gen = client_for(a["users"]["gen_doc"])
    assert gen.get("/api/v1/patients/lookup", query_string={"q": "lina"}).status_code == 403
    mk_patient(gen, a["clinics"]["gen1"], expect=403)


def test_edit_with_version_conflict(app, world, client_for):
    a = world["A"]
    rec = client_for(a["users"]["rec_dent"])
    pt = mk_patient(rec, a["clinics"]["dent2"], "Old Name", phone="111")
    url = f"/api/v1/patients/{pt['id']}"
    r = rec.patch(url, json={"version": 1, "full_name": "New Name", "phone": "0999 000 111"})
    assert r.status_code == 200 and r.get_json()["version"] == 2
    assert rec.get("/api/v1/patients", query_string={"q": "new name"}).get_json()["items"][0]["id"] == pt["id"]
    assert rec.get("/api/v1/patients", query_string={"q": "000111"}).get_json()["items"][0]["id"] == pt["id"]
    r = rec.patch(url, json={"version": 1, "full_name": "Stale"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    assert rec.patch(url, json={"full_name": "No version"}).status_code == 422
    assert rec.patch(url, json={"version": 2, "full_name": ""}).status_code == 422
    assert rec.get(url).get_json()["full_name"] == "New Name"
    # Out of scope edit
    assert client_for(a["users"]["derm_doc"]).patch(url, json={"version": 2, "full_name": "X"}).status_code == 404


def test_delete_and_undo_without_history(app, world, client_for):
    a = world["A"]
    rec = client_for(a["users"]["rec_dent1"])
    pt = mk_patient(rec, a["clinics"]["dent1"], "Mistake Patient")
    r = rec.delete(f"/api/v1/patients/{pt['id']}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert rec.get(f"/api/v1/patients/{pt['id']}").status_code == 404
    assert rec.get("/api/v1/patients", query_string={"q": "Mistake"}).get_json()["items"] == []
    # Another user cannot undo someone else's deletion.
    assert undo(client_for(a["users"]["manager"]), token).status_code == 404
    assert undo(rec, token).status_code == 200
    assert rec.get(f"/api/v1/patients/{pt['id']}").status_code == 200


def test_delete_with_history_requires_higher_permission(app, world, client_for):
    a = world["A"]
    u = a["users"]
    pt = mk_patient(client_for(u["rec_dent1"]), a["clinics"]["dent1"], "History Patient")
    mk_visit(client_for(u["dent_doc1"]), pt["id"], a["clinics"]["dent1"])
    r = client_for(u["rec_dent1"]).delete(f"/api/v1/patients/{pt['id']}")
    assert r.status_code == 403 and r.get_json()["error"]["details"]["permission"] == "patients.delete_with_history"
    assert client_for(u["dent_doc1"]).delete(f"/api/v1/patients/{pt['id']}").status_code == 403
    assert client_for(u["dent_head"]).delete(f"/api/v1/patients/{pt['id']}").status_code == 202


def test_delete_patient_registered_outside_scope(app, world, client_for):
    a = world["A"]
    u = a["users"]
    pt = mk_patient(client_for(u["rec_dent1"]), a["clinics"]["dent1"], "Shared Patient")
    client_for(u["derm_doc"]).post(f"/api/v1/patients/{pt['id']}/link", json={"clinic_id": a["clinics"]["derm1"]})
    r = client_for(u["rec_dent1"]).delete(f"/api/v1/patients/{pt['id']}")
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "patient_outside_scope"
    assert client_for(u["manager"]).delete(f"/api/v1/patients/{pt['id']}").status_code == 202


def test_concurrent_creation_unique_sequential_codes(app, world):
    a = world["A"]
    keys = ["manager", "rec_center", "rec_dent", "rec_multi", "dent_doc1", "dent_doc2", "dent_head", "rec_dent1"]
    clinic_for = {"dent_doc2": a["clinics"]["dent2"]}
    clients = {}
    for k in keys:
        c = ApiClient(app)
        assert c.login(a["users"][k]["email"]).status_code == 200
        clients[k] = c
    codes, errors = [], []
    barrier = threading.Barrier(len(keys))

    def worker(k):
        barrier.wait()
        for n in range(3):
            r = clients[k].post("/api/v1/patients", json={"full_name": f"Concurrent {k} {n}",
                                                         "clinic_id": clinic_for.get(k, a["clinics"]["dent1"])})
            if r.status_code == 201:
                codes.append(r.get_json()["code"])
            else:
                errors.append(r.get_json())

    threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert sorted(codes) == list(range(1, len(keys) * 3 + 1))


def test_departments_indicator_and_summary_hide_restricted(app, world, client_for):
    a = world["A"]
    u = a["users"]
    mgr = client_for(u["manager"])
    pt = mk_patient(mgr, a["clinics"]["dent1"], "Multi Dept")
    dent = client_for(u["dent_doc1"])
    derm = client_for(u["derm_doc"])
    mk_visit(dent, pt["id"], a["clinics"]["dent1"], title="Dental check")
    derm.post(f"/api/v1/patients/{pt['id']}/link", json={"clinic_id": a["clinics"]["derm1"]})
    mk_visit(derm, pt["id"], a["clinics"]["derm1"], title="Derm secret")
    deps = {d["environment"]: d for d in dent.get(f"/api/v1/patients/{pt['id']}/departments").get_json()["items"]}
    assert deps["dentistry"]["accessible"] is True and deps["dentistry"]["visit_count"] == 1
    assert deps["dermatology"]["accessible"] is False
    assert "clinics" not in deps["dermatology"] and "visit_count" not in deps["dermatology"]

    s = dent.get(f"/api/v1/patients/{pt['id']}/summary").get_json()
    sections = {x["name"]: x["data"] for x in s["sections"]}
    assert sections["profile"]["full_name"] == "Multi Dept"
    titles = [v["title"] for c in sections["visits"]["clinics"] for v in c["visits"]]
    assert titles == ["Dental check"]
    assert "Derm secret" not in str(s)

    s = mgr.get(f"/api/v1/patients/{pt['id']}/summary").get_json()
    titles = {v["title"] for x in s["sections"] if x["name"] == "visits"
              for c in x["data"]["clinics"] for v in c["visits"]}
    assert titles == {"Dental check", "Derm secret"}
    # A dentistry doctor of another clinic cannot see the patient at all.
    assert client_for(u["dent_doc2"]).get(f"/api/v1/patients/{pt['id']}/summary").status_code == 404


def test_summary_provider_registry(app, world, client_for):
    from backend.app.modules.patients import summary
    calls = []

    def provider(p, patient):
        calls.append(patient.id)
        return {"hello": patient.display_code} if p.role == "center_manager" else None

    summary.register_summary_provider("zz_test", provider, order=999)
    try:
        a = world["A"]
        pt = mk_patient(client_for(a["users"]["manager"]), a["clinics"]["dent1"], "Registry")
        s = client_for(a["users"]["manager"]).get(f"/api/v1/patients/{pt['id']}/summary").get_json()
        assert s["sections"][-1] == {"name": "zz_test", "data": {"hello": "PAT-000001"}}
        s = client_for(a["users"]["dent_doc1"]).get(f"/api/v1/patients/{pt['id']}/summary").get_json()
        assert "zz_test" not in [x["name"] for x in s["sections"]]
    finally:
        summary._PROVIDERS.pop("zz_test", None)


def test_meta(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["rec_multi"]).get("/api/v1/patients/meta").get_json()
    assert {c["id"] for c in m["clinics"]} == {a["clinics"]["dent1"], a["clinics"]["dent2"], a["clinics"]["derm1"]}
    assert m["permissions"]["patients.create"] is True and m["permissions"]["patients.delete_with_history"] is False
