"""Tests for vital signs, internal referrals, visit orders, and billing packages/installments."""
from tests.conftest import ApiClient

V = "/api/v1"


def test_vitals_flowsheet_and_bmi(world, client_for):
    a = world["A"]
    doc = client_for(a["users"]["dent_doc1"])
    mgr = client_for(a["users"]["manager"])

    # Create a patient
    r = mgr.post(f"{V}/patients", json={"full_name": "Vital Signs Patient", "clinic_id": a["clinics"]["dent1"]})
    assert r.status_code == 201
    pid = r.get_json()["id"]

    # Record vitals
    v_data = {
        "bp_systolic": 120,
        "bp_diastolic": 80,
        "heart_rate": 72,
        "temperature": 36.8,
        "weight": 70.0,
        "height": 175.0,
        "spo2": 98,
        "notes": "Patient resting comfortably"
    }
    r = doc.post(f"{V}/patients/{pid}/vitals", json=v_data)
    assert r.status_code == 201
    v = r.get_json()
    assert v["bp_systolic"] == 120
    assert v["bp_diastolic"] == 80
    assert v["bmi"] == 22.9  # 70 / (1.75^2) = 22.86 -> 22.9

    # List vitals and check trends
    res = doc.get(f"{V}/patients/{pid}/vitals").get_json()
    assert len(res["items"]) == 1
    assert res["latest"]["bp_systolic"] == 120
    assert len(res["trends"]["bp_systolic"]) == 1

    # Delete vital
    vid = v["id"]
    assert doc.delete(f"{V}/vitals/{vid}").status_code == 202


def test_internal_referrals(world, client_for):
    a = world["A"]
    dent_doc = client_for(a["users"]["dent_doc1"])
    derm_doc = client_for(a["users"]["derm_doc"])
    mgr = client_for(a["users"]["manager"])

    r = mgr.post(f"{V}/patients", json={"full_name": "Referral Patient", "clinic_id": a["clinics"]["dent1"]})
    pid = r.get_json()["id"]

    # Create referral from dentistry to dermatology
    ref_body = {
        "from_department_id": a["departments"]["dentistry"],
        "from_clinic_id": a["clinics"]["dent1"],
        "to_department_id": a["departments"]["dermatology"],
        "reason": "Suspicious lesion on lower lip, please evaluate for dermatological consultation.",
        "urgency": "urgent"
    }
    r = dent_doc.post(f"{V}/patients/{pid}/referrals", json=ref_body)
    assert r.status_code == 201
    ref = r.get_json()
    assert ref["status"] == "pending"
    assert ref["urgency"] == "urgent"
    assert ref["from_department_name"] is not None
    assert ref["to_department_name"] is not None

    # Receiving department checks incoming referrals
    inc = derm_doc.get(f"{V}/referrals/incoming").get_json()
    assert any(x["id"] == ref["id"] for x in inc["items"])

    # Accept referral
    acc = derm_doc.post(f"{V}/referrals/{ref['id']}/status", json={"status": "accepted", "notes": "Scheduled for Thursday"}).get_json()
    assert acc["status"] == "accepted"
    assert acc["accepted_at"] is not None


def test_billing_packages_and_installments(world, client_for):
    a = world["A"]
    mgr = client_for(a["users"]["manager"])

    r = mgr.post(f"{V}/patients", json={"full_name": "Package Patient", "clinic_id": a["clinics"]["derm1"]})
    pid = r.get_json()["id"]

    pkg_body = {
        "patient_id": pid,
        "department_id": a["departments"]["dermatology"],
        "clinic_id": a["clinics"]["derm1"],
        "title": "Laser Hair Removal 6 Sessions Package",
        "total_price": "600.00",
        "total_sessions": 6,
        "installments": [
            {"due_date": "2026-10-10", "amount": "200.00", "label": "Initial down payment", "paid": True},
            {"due_date": "2026-11-10", "amount": "200.00", "label": "Session 3 milestone", "paid": False},
            {"due_date": "2026-12-10", "amount": "200.00", "label": "Final milestone", "paid": False}
        ]
    }
    r = mgr.post(f"{V}/billing/packages", json=pkg_body)
    assert r.status_code == 201
    pkg = r.get_json()
    assert pkg["total_sessions"] == 6
    assert pkg["completed_sessions"] == 0
    assert pkg["remaining_sessions"] == 6
    assert pkg["status"] == "active"

    # Record 1 session
    r2 = mgr.post(f"{V}/billing/packages/{pkg['id']}/session", json={"delta": 1})
    assert r2.status_code == 200
    updated = r2.get_json()
    assert updated["completed_sessions"] == 1
    assert updated["remaining_sessions"] == 5

    # List packages for this patient
    pkgs = mgr.get(f"{V}/billing/packages?patient_id={pid}").get_json()
    assert len(pkgs["items"]) == 1
    assert pkgs["items"][0]["id"] == pkg["id"]


def test_visit_investigation_orders(world, client_for):
    a = world["A"]
    doc = client_for(a["users"]["dent_doc1"])
    mgr = client_for(a["users"]["manager"])

    r = mgr.post(f"{V}/patients", json={"full_name": "Orders Patient", "clinic_id": a["clinics"]["dent1"]})
    pid = r.get_json()["id"]

    # Create a visit
    r_v = doc.post(f"{V}/visits", json={"patient_id": pid, "clinic_id": a["clinics"]["dent1"], "title": "Checkup"})
    assert r_v.status_code == 201
    vid = r_v.get_json()["id"]

    # Get visit orders
    r_ord = doc.get(f"{V}/visits/{vid}/orders")
    assert r_ord.status_code == 200
    orders = r_ord.get_json()
    assert orders["visit_id"] == vid
    assert "lab_requests" in orders
    assert "radiology_studies" in orders

