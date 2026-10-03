from tests.test_patients_common import mk_patient, mk_visit

VITALS = {"bp_systolic": 120, "bp_diastolic": 80, "heart_rate": 72, "temperature": 37.2, "resp_rate": 16,
          "spo2": 98, "weight": 70, "height": 175}


def _setup(world, client_for):
    a = world["A"]
    pt = mk_patient(client_for(a["users"]["manager"]), a["clinics"]["gen1"], "Generic Patient")
    return a, pt["id"]


def _create(client, pt, clinic, expect=201, **record):
    r = client.post("/api/v1/generic/visits", json={"patient_id": pt, "clinic_id": clinic,
                                                    "visit_type": "consultation", "record": record})
    assert r.status_code == expect, r.get_json()
    return r.get_json()


def test_create_get_update(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["gen_doc"])
    out = _create(doc, pt, a["clinics"]["gen1"], chief_complaint="Headache", diagnosis="Migraine",
                  vitals=VITALS, extra={"custom_scale": 3})
    rec = out["record"]
    assert out["environment"] == "generic" and rec["chief_complaint"] == "Headache"
    assert rec["vitals"]["temperature"] == 37.2 and rec["vitals"]["heart_rate"] == 72 and rec["bmi"] == 22.9
    assert rec["extra"] == {"custom_scale": 3} and rec["version"] == 1
    url = f"/api/v1/generic/visits/{out['id']}"
    assert doc.get(url).get_json()["record"]["diagnosis"] == "Migraine"
    r = doc.put(url + "/record", json={"version": 1, "treatment_plan": "Rest", "vitals": {"spo2": 97}})
    assert r.status_code == 200
    rec = r.get_json()["record"]
    assert rec["version"] == 2 and rec["treatment_plan"] == "Rest" and rec["vitals"] == {"spo2": 97}
    assert rec["diagnosis"] == "Migraine"
    assert doc.put(url + "/record", json={"version": 1, "notes": "stale"}).status_code == 409
    assert doc.put(url + "/record", json={"notes": "no version"}).status_code == 422
    # Listing + summary
    items = doc.get(f"/api/v1/generic/patients/{pt}/visits").get_json()["items"]
    assert items[0]["record"]["treatment_plan"] == "Rest"
    s = doc.get(f"/api/v1/patients/{pt}/summary").get_json()
    gen = [x for x in s["sections"] if x["name"] == "generic"][0]["data"]["items"]
    assert gen[0]["diagnosis"] == "Migraine"
    meta = doc.get("/api/v1/generic/meta").get_json()
    assert [c["id"] for c in meta["clinics"]] == [a["clinics"]["gen1"]]


def test_record_for_plain_visit_and_validation(app, world, client_for):
    a, pt = _setup(world, client_for)
    doc = client_for(a["users"]["gen_doc"])
    v = mk_visit(doc, pt, a["clinics"]["gen1"])
    url = f"/api/v1/generic/visits/{v['id']}"
    assert doc.get(url).get_json()["record"] is None
    r = doc.put(url + "/record", json={"symptoms": "cough"})
    assert r.status_code == 200 and r.get_json()["record"]["symptoms"] == "cough"
    _create(doc, pt, a["clinics"]["gen1"], vitals={"heart_rate": 900}, expect=422)
    _create(doc, pt, a["clinics"]["gen1"], vitals={"temperature": 37.25}, expect=422)
    _create(doc, pt, a["clinics"]["gen1"], extra="nope", expect=422)


def test_environment_and_scope(app, world, client_for):
    a, pt = _setup(world, client_for)
    u = a["users"]
    # Dentistry clinic is not a generic environment.
    dent = client_for(u["dent_doc1"])
    dent.post(f"/api/v1/patients/{pt}/link", json={"clinic_id": a["clinics"]["dent1"]})
    r = dent.post("/api/v1/generic/visits", json={"patient_id": pt, "clinic_id": a["clinics"]["dent1"]})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "wrong_environment"
    dv = mk_visit(dent, pt, a["clinics"]["dent1"])
    assert dent.get(f"/api/v1/generic/visits/{dv['id']}").status_code == 422
    # Out-of-scope clinic, receptionist, other tenant.
    _create(dent, pt, a["clinics"]["gen1"], expect=404)
    rec = client_for(u["rec_center"])
    _create(rec, pt, a["clinics"]["gen1"], expect=403)
    out = _create(client_for(u["gen_doc"]), pt, a["clinics"]["gen1"], diagnosis="Secret dx")
    assert rec.get(f"/api/v1/generic/visits/{out['id']}").status_code == 200
    assert rec.put(f"/api/v1/generic/visits/{out['id']}/record", json={"version": 1}).status_code == 403
    assert dent.get(f"/api/v1/generic/visits/{out['id']}").status_code == 404
    s = dent.get(f"/api/v1/patients/{pt}/summary").get_json()
    assert "Secret dx" not in str(s) and "generic" not in [x["name"] for x in s["sections"]]
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f"/api/v1/generic/visits/{out['id']}").status_code == 404
    assert b.put(f"/api/v1/generic/visits/{out['id']}/record", json={"version": 1}).status_code == 404
