"""Report numbers on the known fixture set (tests/test_reports_helpers.py)."""
from tests.test_reports_helpers import BASE, JAN, q, seed


def _get(c, key, **params):
    r = c.get(f"{BASE}/{key}?{q({**JAN, **params})}")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _by_group(rep):
    return {row["group"]: row for row in rep["rows"]}


def test_patients_report(app, world, client_for):
    a = world["A"]
    seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "patients")
    g = _by_group(rep)
    assert g["Dental Clinic 1"]["new_patients"] == 2  # P1 + P5 (P4 is Dec 31 local)
    assert g["Dental Clinic 2"]["new_patients"] == 1
    assert g["Dermatology Clinic 1"]["new_patients"] == 1
    assert rep["totals"]["new_patients"] == 4
    assert [c["key"] for c in rep["columns"]] == ["group", "new_patients"]
    rep = _get(m, "patients", group_by="gender")
    assert _by_group(rep)["female"]["new_patients"] == 1 and _by_group(rep)["unknown"]["new_patients"] == 1
    rep = _get(m, "patients", group_by="department")
    assert _by_group(rep)["Dentistry"]["new_patients"] == 3
    rep = _get(m, "patients", group_by="day")
    assert {r["group"] for r in rep["rows"]} == {"2026-01-10", "2026-01-15", "2026-01-20", "2026-01-31"}
    # date boundary: Dec 31 local only
    rep = _get(m, "patients", date_from="2025-12-31", date_to="2025-12-31")
    assert rep["totals"]["new_patients"] == 1


def test_appointments_report(app, world, client_for):
    a = world["A"]
    seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "appointments", group_by="none")
    row = rep["rows"][0]
    assert (row["total"], row["completed"], row["no_show"], row["cancelled"]) == (5, 2, 2, 1)
    assert row["no_show_rate"] == "50.0"
    rep = _get(m, "appointments", group_by="doctor")
    doc1 = next(r for r in rep["rows"] if r["key"] == a["users"]["dent_doc1"]["id"])
    assert doc1["total"] == 3 and doc1["no_show_rate"] == "50.0"
    assert rep["totals"]["total"] == 5 and rep["totals"]["no_show_rate"] == "50.0"
    rep = _get(m, "appointments", group_by="clinic", clinic_id=a["clinics"]["dent2"])
    assert [r["group"] for r in rep["rows"]] == ["Dental Clinic 2"]


def test_doctor_and_unit_activity(app, world, client_for):
    a = world["A"]
    seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "doctor_activity")
    doc1 = next(r for r in rep["rows"] if r["key"] == a["users"]["dent_doc1"]["id"])
    assert (doc1["appointments"], doc1["completed_appointments"], doc1["no_shows"], doc1["visits"],
            doc1["patients_seen"], doc1["completed_treatments"]) == (2, 1, 1, 3, 2, 1)
    assert doc1["role"] == "doctor"

    rep = _get(m, "clinic_activity")
    g = _by_group(rep)
    d1 = g["Dental Clinic 1"]
    assert (d1["appointments"], d1["visits"], d1["patients_seen"], d1["lab_requests"], d1["radiology_requests"]) \
        == (2, 3, 2, 2, 2)
    assert d1["revenue"] == "200.00" and d1["payments_received"] == "150.00"
    assert g["Eye Clinic 1"]["appointments"] == 0  # in-scope units without activity are listed
    assert rep["totals"]["revenue"] == "400.00"

    rep = _get(m, "department_activity")
    dent = _by_group(rep)["Dentistry"]
    assert dent["appointments"] == 3 and dent["revenue"] == "280.00" and dent["completed_treatments"] == 2


def test_financial_reports(app, world, client_for):
    a = world["A"]
    seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "revenue", group_by="clinic")
    d1 = _by_group(rep)["Dental Clinic 1"]
    assert (d1["revenue"], d1["payments_received"], d1["outstanding_total"]) == ("200.00", "150.00", "50.00")
    assert rep["totals"]["revenue"] == "400.00" and rep["totals"]["payments_received"] == "270.00"
    assert rep["meta"]["currency"] == "SYP"
    rep = _get(m, "revenue", group_by="none")
    assert rep["rows"][0]["outstanding_total"] == "130.00" and rep["totals"] is None

    rep = _get(m, "outstanding")
    assert [r["balance"] for r in rep["rows"]] == ["80.00", "50.00"]
    assert rep["rows"][0]["group"] == "Patient P2" and rep["totals"]["balance"] == "130.00"

    rep = _get(m, "services", group_by="kind")
    g = _by_group(rep)
    assert g["treatment"]["lines"] == 2 and g["treatment"]["net"] == "280.00"
    assert g["consultation"]["net"] == "120.00" and rep["totals"]["net"] == "400.00"
    rep = _get(m, "services")
    assert _by_group(rep)["Filling"]["gross"] == "200.00"


def test_treatments_report(app, world, client_for):
    a = world["A"]
    seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "treatments")
    g = _by_group(rep)
    assert (g["filling"]["total"], g["filling"]["completed"], g["filling"]["fees_completed"]) == (2, 2, "150.00")
    assert g["crown"]["planned"] == 1 and rep["totals"]["total"] == 3


def test_inventory_report(app, world, client_for):
    a = world["A"]
    ids = seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "inventory")
    assert {(r["location"], r["quantity"]) for r in rep["rows"]} == {("Dental Clinic 1", "5"),
                                                                     ("Dermatology Clinic 1", "50")}
    rep = _get(m, "inventory", view="low_stock")
    assert [(r["location"], r["low"]) for r in rep["rows"]] == [("Dental Clinic 1", "yes")]
    rep = _get(m, "inventory", view="expiry", days=30)
    assert [(r["lot_code"], r["days_left"], r["status"]) for r in rep["rows"]] == [("L-1", 10, "expiring")]
    rep = _get(m, "inventory", view="movements")
    row = rep["rows"][0]
    assert (row["received"], row["used"], row["net_change"], row["movements"]) == ("60", "-5", "55", 3)
    rep = _get(m, "inventory", view="movements", location_id=ids["locations"]["dent1"])
    assert rep["rows"][0]["net_change"] == "5"


def test_lab_and_radiology_reports(app, world, client_for):
    a = world["A"]
    seed(app, a)
    m = client_for(a["users"]["manager"])
    rep = _get(m, "laboratory")
    g = _by_group(rep)
    assert (g["Hemoglobin"]["ordered"], g["Hemoglobin"]["resulted"], g["Hemoglobin"]["abnormal"]) == (2, 1, 1)
    assert g["Glucose"]["abnormal"] == 0 and rep["totals"]["abnormal_rate"] == "50.0"
    rep = _get(m, "laboratory", group_by="status")
    assert rep["totals"]["total"] == 2 and rep["totals"]["urgent"] == 1
    assert rep["totals"]["avg_turnaround_hours"] == "5.0"
    rep = _get(m, "radiology")
    g = _by_group(rep)
    assert g["x_ray"]["finalized"] == 1 and g["x_ray"]["avg_turnaround_hours"] == "2.0"
    assert g["ct"]["requested"] == 1 and g["ct"]["avg_turnaround_hours"] is None
    # lab staff see lab-side requests; an unrelated clinic's doctor sees none
    lab = client_for(a["users"]["lab_doc"])
    assert _get(lab, "laboratory", group_by="status")["totals"]["total"] == 2
    derm = client_for(a["users"]["derm_doc"])
    assert _get(derm, "laboratory", group_by="status")["totals"]["total"] == 0
    assert _get(derm, "radiology")["rows"] == []
