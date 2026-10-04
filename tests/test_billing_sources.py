from tests.test_billing_helpers import BASE, make_patient, new_invoice


def test_bill_dental_treatment(app, world, client_for):
    a, b = world["A"], world["B"]
    pid = make_patient(app, a, "dent1")
    doc = client_for(a["users"]["dent_doc1"])
    r = doc.post("/api/v1/dentistry/treatments", json={"patient_id": pid, "procedure": "Root canal",
                                                       "tooth_number": 14, "fee": "250.00"})
    assert r.status_code == 201, r.get_json()
    tid = r.get_json()["id"]
    pv = doc.get(f"{BASE}/sources/dental_treatment/{tid}").get_json()
    assert pv["lines"][0]["unit_price"] == "250.00" and pv["lines"][0]["reference_id"] == tid
    assert pv["default_clinic_id"] == a["clinics"]["dent1"] and pv["billed_in"] == []
    r = doc.post(f"{BASE}/invoices/from-source", json={"source_type": "dental_treatment", "source_id": tid,
                                                       "issue": True})
    assert r.status_code == 201, r.get_json()
    inv = r.get_json()
    assert inv["status"] == "issued" and inv["total"] == "250.00"
    assert inv["items"][0]["reference_type"] == "dental_treatment" and inv["items"][0]["kind"] == "treatment"
    # duplicate billing refused unless explicitly allowed
    r = doc.post(f"{BASE}/invoices/from-source", json={"source_type": "dental_treatment", "source_id": tid})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "already_billed"
    assert doc.get(f"{BASE}/sources/dental_treatment/{tid}").get_json()["billed_in"] == [inv["number"]]
    from backend.app.core import tenancy
    from backend.app.modules.billing.sources import is_referenced
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        assert is_referenced(a["center_id"], "dental_treatment", tid)
    # other clinic doctor / other tenant cannot see it
    assert client_for(a["users"]["dent_doc2"]).get(f"{BASE}/sources/dental_treatment/{tid}").status_code == 404
    assert client_for(b["users"]["manager"]).get(f"{BASE}/sources/dental_treatment/{tid}").status_code == 404
    assert doc.get(f"{BASE}/sources/bogus/{tid}").status_code == 422


def test_financial_summary_provider(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a, "dent1")
    mgr = client_for(a["users"]["manager"])
    new_invoice(mgr, a, pid, issue=True)
    s = mgr.get(f"/api/v1/patients/{pid}/summary").get_json()
    fin = next(x for x in s["sections"] if x["name"] == "financial")
    assert fin["data"]["totals"]["billed"] == "100.00" and len(fin["data"]["invoices"]) == 1
    # without billing.view the section is omitted
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import UserPermission
    u = a["users"]["rec_dent1"]
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        db.session.add(UserPermission(health_center_id=a["center_id"], user_id=u["id"], permission="billing.view",
                                      allowed=False))
        db.session.commit()
    s = client_for(u).get(f"/api/v1/patients/{pid}/summary").get_json()
    assert "financial" not in [x["name"] for x in s["sections"]]
