import pytest

from backend.app.core import tenancy
from backend.app.core.errors import NotFound
from backend.app.extensions import db
from backend.app.services.clinical import get_visit
from tests.test_laboratory_helpers import make_patient, make_visit, notifications, principal_for

BASE = "/api/v1/lab"


@pytest.fixture()
def lab(app, world, client_for):
    """Center A with a small catalog, a patient seen in dermatology + general medicine + dentistry."""
    a = world["A"]
    mgr = client_for(a["users"]["manager"])
    tests = {}
    for body in ({"code": "GLU", "name": "Glucose", "unit": "mg/dL", "ref_low": "70", "ref_high": "110",
                  "price": "5.00"},
                 {"code": "HB", "name": "Hemoglobin", "unit": "g/dL", "ref_low": "11", "ref_high": "16",
                  "ref_low_male": "13.5", "ref_high_male": "17.5"},
                 {"code": "UPR", "name": "Urine protein", "result_type": "choice", "choices": ["Negative", "+", "++"],
                  "normal_choices": ["Negative"]},
                 {"code": "CUL", "name": "Culture", "result_type": "text"}):
        r = mgr.post(f"{BASE}/tests", json=body)
        assert r.status_code == 201, r.get_json()
        tests[body["code"]] = r.get_json()["id"]
    patient = make_patient(app, a, "derm1", "gen1", "dent1", gender="male")
    return {"a": a, "tests": tests, "patient": patient}


def _request(client, lab, tests=("GLU", "HB", "UPR", "CUL"), **kw):
    body = {"patient_id": lab["patient"], "test_ids": [lab["tests"][t] for t in tests], **kw}
    return client.post(f"{BASE}/requests", json=body)


def test_full_lab_workflow_and_visibility(app, world, client_for, lab):
    a = lab["a"]
    derm = client_for(a["users"]["derm_doc"])
    labdoc = client_for(a["users"]["lab_doc"])
    gen = client_for(a["users"]["gen_doc"])
    dent2 = client_for(a["users"]["dent_doc2"])

    r = _request(derm, lab, priority="urgent", clinical_notes="r/o diabetes")
    assert r.status_code == 201, r.get_json()
    req = r.get_json()
    assert req["status"] == "requested" and req["access"] == "requester"
    assert req["requesting_clinic"]["id"] == a["clinics"]["derm1"]
    assert req["lab_clinic"]["id"] == a["clinics"]["lab1"]
    assert req["requested_by"]["name"].startswith("derm_doc")
    # gender-specific range snapshotted for a male patient
    hb = next(i for i in req["items"] if i["test_code"] == "HB")
    assert hb["ref_low"] == "13.5" and "result_value" not in hb
    assert notifications(labdoc, "lab_request")

    # Lab queue shows it (urgent first); lab staff now see the patient's basic profile only.
    q = labdoc.get(f"{BASE}/queue").get_json()
    assert [x["id"] for x in q["items"]] == [req["id"]]
    assert q["items"][0]["patient"]["full_name"] == "Ali Hasan"
    # Lab staff cannot read the patient's dental visits.
    visit_id = make_visit(app, a, lab["patient"], "dent1")
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        p = principal_for(a, "lab_doc")
        with pytest.raises(NotFound):
            get_visit(p, visit_id)
        db.session.rollback()
    # Other doctors who see the patient cannot see a non-finalized request.
    assert gen.get(f"{BASE}/requests/{req['id']}").status_code == 404
    assert gen.get(f"{BASE}/patients/{lab['patient']}/requests").get_json()["items"] == []
    # Requester cannot process.
    assert derm.post(f"{BASE}/requests/{req['id']}/start", json={"version": req["version"]}).status_code == 403
    # Other non-lab doctors have lab.process by default but no laboratory clinic: not visible.
    assert dent2.get(f"{BASE}/queue").get_json()["items"] == []

    r = labdoc.post(f"{BASE}/requests/{req['id']}/start", json={"version": req["version"]})
    assert r.status_code == 200 and r.get_json()["status"] == "in_progress"
    cur = r.get_json()
    ids = {i["test_code"]: i["id"] for i in cur["items"]}
    # Version conflict on results.
    r = labdoc.put(f"{BASE}/requests/{req['id']}/results",
                   json={"version": req["version"], "items": [{"id": ids["GLU"], "result_value": "150"}]})
    assert r.status_code == 409
    # Invalid values are rejected.
    r = labdoc.put(f"{BASE}/requests/{req['id']}/results",
                   json={"version": cur["version"], "items": [{"id": ids["GLU"], "result_value": "high"},
                                                              {"id": ids["UPR"], "result_value": "+++"}]})
    assert r.status_code == 422
    r = labdoc.put(f"{BASE}/requests/{req['id']}/results",
                   json={"version": cur["version"], "items": [{"id": ids["GLU"], "result_value": "150"},
                                                              {"id": ids["HB"], "result_value": "14"}]})
    assert r.status_code == 200, r.get_json()
    cur = r.get_json()
    flags = {i["test_code"]: i["abnormal_flag"] for i in cur["items"]}
    assert flags["GLU"] == "H" and flags["HB"] == "N"
    # Finalizing with missing results fails.
    r = labdoc.post(f"{BASE}/requests/{req['id']}/finalize", json={"version": cur["version"]})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "missing_results"
    # Requester sees status but no draft results.
    d = derm.get(f"{BASE}/requests/{req['id']}").get_json()
    assert d["status"] == "in_progress" and "result_value" not in d["items"][0]
    r = labdoc.put(f"{BASE}/requests/{req['id']}/results",
                   json={"version": cur["version"], "result_notes": "Fasting sample",
                         "items": [{"id": ids["UPR"], "result_value": "+"},
                                   {"id": ids["CUL"], "result_value": "Staph aureus", "abnormal": True,
                                    "comment": "sensitive to X"}]})
    assert r.status_code == 200
    cur = r.get_json()
    r = labdoc.post(f"{BASE}/requests/{req['id']}/finalize", json={"version": cur["version"]})
    assert r.status_code == 200, r.get_json()
    fin = r.get_json()
    assert fin["status"] == "completed" and fin["finalized_by"]["name"].startswith("lab_doc")
    assert fin["abnormal_count"] == 3
    assert notifications(derm, "lab_result_available")
    # No further edits after finalization.
    r = labdoc.put(f"{BASE}/requests/{req['id']}/results",
                   json={"version": fin["version"], "items": [{"id": ids["GLU"], "result_value": "90"}]})
    assert r.status_code == 409

    # Requester now sees results.
    d = derm.get(f"{BASE}/requests/{req['id']}").get_json()
    assert {i["test_code"]: i["result_value"] for i in d["items"]}["GLU"] == "150"
    # Finalized results are center-wide for staff who can see the patient (no workflow access).
    g = gen.get(f"{BASE}/requests/{req['id']}")
    assert g.status_code == 200 and g.get_json()["access"] == "result"
    assert not any(g.get_json()["can"].values())
    assert gen.post(f"{BASE}/requests/{req['id']}/cancel", json={"version": fin["version"]}).status_code == 403
    assert [x["id"] for x in gen.get(f"{BASE}/patients/{lab['patient']}/requests").get_json()["items"]] == [req["id"]]
    assert gen.get(f"{BASE}/queue").get_json()["items"] == []
    # ... but not for staff who cannot see the patient.
    assert dent2.get(f"{BASE}/requests/{req['id']}").status_code == 404

    # Report JSON + PDF.
    rep = gen.get(f"{BASE}/requests/{req['id']}/report")
    assert rep.status_code == 200 and rep.get_json()["items"][0]["reference_range"]
    pdf = gen.get(f"{BASE}/requests/{req['id']}/report?format=pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    file_id = derm.get(f"{BASE}/requests/{req['id']}").get_json()["report_file_id"]
    assert file_id
    assert gen.get(f"/api/v1/files/{file_id}/content").status_code == 200

    # Cross-tenant: center B staff never see center A requests.
    b_mgr = client_for(world["B"]["users"]["manager"])
    assert b_mgr.get(f"{BASE}/requests/{req['id']}").status_code == 404
    assert b_mgr.get(f"{BASE}/requests/{req['id']}/report").status_code == 404
    assert b_mgr.get(f"{BASE}/queue").get_json()["items"] == []
    assert client_for(world["B"]["users"]["lab_doc"]).post(
        f"{BASE}/requests/{req['id']}/cancel", json={"version": fin["version"]}).status_code == 404


def test_request_rules_delete_undo_cancel(app, world, client_for, lab):
    a = lab["a"]
    derm = client_for(a["users"]["derm_doc"])
    labdoc = client_for(a["users"]["lab_doc"])
    # Patient must be visible to the requester.
    other = make_patient(app, a, "dent2", name="Other")
    assert derm.post(f"{BASE}/requests", json={"patient_id": other, "test_ids": [lab["tests"]["GLU"]]}
                     ).status_code == 404
    # Validation.
    assert derm.post(f"{BASE}/requests", json={"patient_id": lab["patient"], "test_ids": []}).status_code == 422
    assert derm.post(f"{BASE}/requests", json={"patient_id": lab["patient"], "test_ids": [999999]}).status_code == 422
    # Requesting clinic must be in scope.
    r = _request(derm, lab, requesting_clinic_id=a["clinics"]["gen1"])
    assert r.status_code == 404
    # A center-wide receptionist can request on behalf of a clinic.
    r = _request(client_for(a["users"]["rec_center"]), lab, requesting_clinic_id=a["clinics"]["gen1"])
    assert r.status_code == 201, r.get_json()

    req = _request(derm, lab, tests=("GLU",)).get_json()
    # Edit (requester, while requested) with version check.
    r = derm.patch(f"{BASE}/requests/{req['id']}", json={"version": req["version"], "priority": "urgent"})
    assert r.status_code == 200
    assert derm.patch(f"{BASE}/requests/{req['id']}", json={"version": req["version"], "priority": "routine"}
                      ).status_code == 409
    # Lab staff cannot delete; requester can, with undo.
    assert labdoc.delete(f"{BASE}/requests/{req['id']}").status_code == 403
    r = derm.delete(f"{BASE}/requests/{req['id']}")
    assert r.status_code == 202
    assert derm.get(f"{BASE}/requests/{req['id']}").status_code == 404
    assert req["id"] not in [x["id"] for x in labdoc.get(f"{BASE}/queue").get_json()["items"]]
    assert derm.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    cur = derm.get(f"{BASE}/requests/{req['id']}").get_json()

    # Once in progress: requester cannot delete or cancel; lab can cancel.
    cur = labdoc.post(f"{BASE}/requests/{req['id']}/start", json={"version": cur["version"]}).get_json()
    assert derm.delete(f"{BASE}/requests/{req['id']}").status_code == 409
    assert derm.post(f"{BASE}/requests/{req['id']}/cancel", json={"version": cur["version"]}).status_code == 409
    r = labdoc.post(f"{BASE}/requests/{req['id']}/cancel", json={"version": cur["version"], "reason": "hemolysed"})
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    # Cancelled results are not center-wide.
    assert client_for(a["users"]["gen_doc"]).get(f"{BASE}/requests/{req['id']}").status_code == 404

    # Requester can cancel while still requested.
    req2 = _request(derm, lab, tests=("GLU",)).get_json()
    r = derm.post(f"{BASE}/requests/{req2['id']}/cancel", json={"version": req2["version"]})
    assert r.status_code == 200
