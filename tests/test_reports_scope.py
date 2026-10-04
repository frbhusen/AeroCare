"""Report scope per role, permission denial, filter validation and cross-tenant isolation."""
from tests.test_reports_helpers import BASE, JAN, q, seed, set_perm


def _get(c, key, **params):
    return c.get(f"{BASE}/{key}?{q({**JAN, **params})}")


def _groups(r):
    assert r.status_code == 200, r.get_json()
    return {row["group"]: row for row in r.get_json()["rows"]}


def test_catalog_per_role(app, world, client_for):
    a = world["A"]
    keys = lambda c: {r["key"] for r in c.get(BASE).get_json()["reports"]}  # noqa: E731
    m = client_for(a["users"]["manager"])
    body = m.get(BASE).get_json()
    assert {r["key"] for r in body["reports"]} == {
        "patients", "appointments", "doctor_activity", "clinic_activity", "department_activity", "revenue",
        "outstanding", "services", "treatments", "inventory", "laboratory", "radiology"}
    assert body["formats"] == ["xlsx", "pdf"] and len(body["clinics"]) == 8
    doc = client_for(a["users"]["dent_doc1"])
    body = doc.get(BASE).get_json()
    assert "department_activity" not in {r["key"] for r in body["reports"]}
    assert "treatments" in {r["key"] for r in body["reports"]}
    assert body["formats"] == []  # doctors cannot export by default
    assert [c["name"] for c in body["clinics"]] == ["Dental Clinic 1"]
    assert "treatments" not in keys(client_for(a["users"]["derm_doc"]))  # no dentistry in scope
    assert "department_activity" in keys(client_for(a["users"]["rec_dent"]))
    assert "department_activity" not in keys(client_for(a["users"]["rec_dent1"]))
    set_perm(app, a, "rec_dent1", "billing.view", False)
    assert not {"revenue", "outstanding", "services"} & keys(client_for(a["users"]["rec_dent1"]))


def test_department_manager_scope(app, world, client_for):
    a = world["A"]
    seed(app, a)
    h = client_for(a["users"]["dent_head"])
    g = _groups(_get(h, "patients"))
    assert set(g) == {"Dental Clinic 1", "Dental Clinic 2"}
    assert _get(h, "patients").get_json()["totals"]["new_patients"] == 3
    g = _groups(_get(h, "department_activity"))
    assert set(g) == {"Dentistry"}
    r = _get(h, "revenue", group_by="none")
    assert r.get_json()["rows"][0]["revenue"] == "280.00"
    assert {row["group"] for row in _get(h, "outstanding").get_json()["rows"]} == {"Patient P1", "Patient P2"}
    # filters may not widen scope
    assert _get(h, "patients", department_id=a["departments"]["dermatology"]).status_code == 404
    assert _get(h, "appointments", clinic_id=a["clinics"]["derm1"]).status_code == 404
    assert _get(h, "appointments", doctor_id=a["users"]["derm_doc"]["id"]).status_code == 404
    # inventory: own department locations only
    g = _get(h, "inventory").get_json()["rows"]
    assert {r["location"] for r in g} == {"Dental Clinic 1"}


def test_doctor_scope(app, world, client_for):
    a = world["A"]
    seed(app, a)
    d = client_for(a["users"]["dent_doc1"])
    assert set(_groups(_get(d, "patients"))) == {"Dental Clinic 1"}
    rows = _get(d, "doctor_activity").get_json()["rows"]
    assert {r["key"] for r in rows} == {a["users"]["dent_doc1"]["id"]}
    assert set(_groups(_get(d, "clinic_activity"))) == {"Dental Clinic 1"}
    assert _get(d, "revenue", group_by="none").get_json()["rows"][0]["revenue"] == "200.00"
    assert _get(d, "department_activity").status_code == 403
    assert _get(d, "patients", clinic_id=a["clinics"]["dent2"]).status_code == 404
    # receptionist limited to dent1
    rc = client_for(a["users"]["rec_dent1"])
    assert set(_groups(_get(rc, "appointments"))) == {"Dental Clinic 1"}


def test_permission_denial_and_validation(app, world, client_for):
    a = world["A"]
    seed(app, a)
    set_perm(app, a, "dent_doc2", "reports.view", False)
    d2 = client_for(a["users"]["dent_doc2"])
    assert d2.get(BASE).status_code == 403
    assert _get(d2, "patients").status_code == 403
    set_perm(app, a, "rec_dent1", "billing.view", False)
    rc = client_for(a["users"]["rec_dent1"])
    r = _get(rc, "revenue")
    assert r.status_code == 403 and r.get_json()["error"]["details"]["permission"] == "billing.view"
    assert _get(rc, "appointments").status_code == 200
    # doctors lack reports.export by default
    d = client_for(a["users"]["dent_doc1"])
    assert d.get(f"{BASE}/patients/export?{q(JAN)}&format=xlsx").status_code == 403
    m = client_for(a["users"]["manager"])
    assert _get(m, "nope").status_code == 404
    assert _get(m, "patients", group_by="doctor").status_code == 422
    assert _get(m, "patients", date_from="2026-02-01").status_code == 422  # from > to
    assert _get(m, "patients", date_from="2010-01-01").status_code == 422  # range too long
    assert _get(m, "patients", columns="group,bogus").status_code == 422
    r = _get(m, "patients", columns="new_patients")
    assert [c["key"] for c in r.get_json()["columns"]] == ["new_patients"]
    assert m.get(f"{BASE}/patients/export?{q(JAN)}&format=csv").status_code == 422
    assert m.get(f"{BASE}/patients").status_code == 200  # default range works


def test_cross_tenant_isolation(app, world, client_for):
    a, b = world["A"], world["B"]
    seed(app, a)
    seed(app, b, names={"P1": "Bravo One", "P2": "Bravo Two", "P3": "Bravo Three"})
    mb = client_for(b["users"]["manager"])
    rep = _get(mb, "outstanding").get_json()
    assert {r["group"] for r in rep["rows"]} == {"Bravo One", "Bravo Two"}
    assert _get(mb, "patients").get_json()["totals"]["new_patients"] == 4
    assert _get(mb, "revenue", group_by="none").get_json()["rows"][0]["revenue"] == "400.00"
    # A's ids are not usable as filters from B
    assert _get(mb, "patients", clinic_id=a["clinics"]["dent1"]).status_code == 404
    assert _get(mb, "patients", department_id=a["departments"]["dentistry"]).status_code == 404
    assert _get(mb, "appointments", doctor_id=a["users"]["dent_doc1"]["id"]).status_code == 404
    assert _get(mb, "inventory", view="movements", location_id=999999).status_code == 404
    ma = client_for(a["users"]["manager"])
    assert {r["group"] for r in _get(ma, "outstanding").get_json()["rows"]} == {"Patient P1", "Patient P2"}
    # superadmin without a center context cannot run reports
    sa = client_for(world["superadmin"])
    assert sa.get(BASE).status_code in (401, 403)
