"""Ophthalmology exams: structured OD/OS data, numeric validation, scope, versioning, delete/undo."""
import pytest
from sqlalchemy import select

from tests.test_dermatology_support import expire_and_purge, make_patient, platform_rows

BASE = "/api/v1/ophthalmology"

EYE = {
    "visual_acuity": {"uncorrected": "6/18", "best_corrected": "6/6", "pinhole": "0.8"},
    "refraction": {"sphere": -2.25, "cylinder": -0.75, "axis": 180, "add": 0},
    "iop": {"value": 16.5, "method": "goldmann"},
    "pupils": {"size_mm": 3, "reaction": "brisk", "rapd": "absent"},
    "motility": {"status": "full"},
    "slit_lamp": {"lids": "Normal", "conjunctiva": "Quiet", "cornea": "Clear", "anterior_chamber": "Deep and quiet",
                  "iris": "Normal", "lens": "Clear"},
    "fundus": {"dilated": True, "optic_disc": "Pink, sharp", "cup_disc_ratio": 0.3, "macula": "Normal",
               "vessels": "Normal", "periphery": "Flat"},
    "unknown_field": "dropped",
}


def _create(client, a, pid, **kw):
    body = {"patient_id": pid, "clinic_id": a["clinics"]["oph1"], "chief_complaint": "Blurred vision",
            "right_eye": EYE, "left_eye": {"visual_acuity": {"uncorrected": "CF 1m"}, "iop": {"value": 21}},
            "diagnosis": "Myopic astigmatism", "treatment": "Glasses",
            "glasses": {"right": {"sphere": -2.25, "cylinder": -0.75, "axis": 180}, "left": {"sphere": -2},
                        "pd_mm": 62, "lens_type": "single_vision"}}
    body.update(kw)
    return client.post(f"{BASE}/exams", json=body)


@pytest.fixture()
def oph(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    doc = client_for(a["users"]["oph_doc"])
    r = _create(doc, a, pid)
    assert r.status_code == 201, r.get_json()
    return {"a": a, "pid": pid, "doc": doc, "exam": r.get_json()}


def test_meta(world, client_for):
    m = client_for(world["A"]["users"]["oph_doc"]).get(f"{BASE}/meta").get_json()
    assert m["eye_fields"]["iop"]["value"] == {"type": "number", "min": 0, "max": 80, "step": 0.1}
    assert m["eye_fields"]["refraction"]["axis"]["max"] == 180
    assert [e["abbr"] for e in m["eyes"]] == ["OD", "OS"]


def test_create_structured(oph):
    e = oph["exam"]
    od = e["right_eye"]
    assert od["refraction"] == {"sphere": -2.25, "cylinder": -0.75, "axis": 180, "add": 0}
    assert od["iop"] == {"value": 16.5, "method": "goldmann"}
    assert od["fundus"]["cup_disc_ratio"] == 0.3 and od["fundus"]["dilated"] is True
    assert "unknown_field" not in od
    assert e["left_eye"]["visual_acuity"]["uncorrected"] == "CF 1M"
    assert e["glasses"]["pd_mm"] == 62 and e["visit_type"] == "examination"
    lst = oph["doc"].get(f"{BASE}/patients/{oph['pid']}/exams").get_json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == e["id"]


@pytest.mark.parametrize("bad, key", [
    ({"right_eye": {"iop": {"value": 81}}}, "right_eye.iop.value"),
    ({"right_eye": {"iop": {"value": -1}}}, "right_eye.iop.value"),
    ({"left_eye": {"refraction": {"axis": 181}}}, "left_eye.refraction.axis"),
    ({"left_eye": {"refraction": {"sphere": -2, "cylinder": -1}}}, "left_eye.refraction.axis"),
    ({"right_eye": {"fundus": {"cup_disc_ratio": 1.2}}}, "right_eye.fundus.cup_disc_ratio"),
    ({"right_eye": {"visual_acuity": {"uncorrected": "excellent"}}}, "right_eye.visual_acuity.uncorrected"),
    ({"right_eye": {"visual_acuity": {"best_corrected": "3.5"}}}, "right_eye.visual_acuity.best_corrected"),
    ({"right_eye": {"pupils": {"reaction": "fast"}}}, "right_eye.pupils.reaction"),
    ({"right_eye": {"refraction": {"sphere": "abc"}}}, "right_eye.refraction.sphere"),
    ({"right_eye": {"refraction": {"sphere": -2.125}}}, "right_eye.refraction.sphere"),
    ({"glasses": {"pd_mm": 20}}, "glasses.pd_mm"),
    ({"right_eye": {"iop": "high"}}, "right_eye.iop"),
])
def test_numeric_validation(world, client_for, app, bad, key):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["oph_doc"])
    body = {"patient_id": pid, "clinic_id": a["clinics"]["oph1"], **bad}
    r = d.post(f"{BASE}/exams", json=body)
    assert r.status_code == 422, r.get_json()
    assert key in r.get_json()["error"]["details"]


def test_environment_and_isolation(oph, world, client_for):
    a, eid, pid = oph["a"], oph["exam"]["id"], oph["pid"]
    m = client_for(a["users"]["manager"])
    r = _create(m, a, pid, clinic_id=a["clinics"]["derm1"])
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "wrong_environment"
    derm = client_for(a["users"]["derm_doc"])
    assert derm.get(f"{BASE}/exams/{eid}").status_code == 404
    assert derm.get(f"{BASE}/patients/{pid}/exams").status_code == 404
    assert _create(derm, a, pid).status_code == 404
    assert m.get(f"{BASE}/exams/{eid}").status_code == 200
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f"{BASE}/exams/{eid}").status_code == 404
    assert b.delete(f"{BASE}/exams/{eid}").status_code == 404
    assert b.get(f"{BASE}/patients/{pid}/exams").status_code == 404
    rec = client_for(a["users"]["rec_center"])
    assert rec.get(f"{BASE}/exams/{eid}").status_code == 200
    assert rec.patch(f"{BASE}/exams/{eid}", json={"version": 1, "notes": "x"}).status_code == 403


def test_update_version_conflict(oph):
    d, eid = oph["doc"], oph["exam"]["id"]
    r = d.patch(f"{BASE}/exams/{eid}", json={"version": 1, "left_eye": {"iop": {"value": 30, "method": "icare"}},
                                             "notes": "Recheck IOP"})
    assert r.status_code == 200, r.get_json()
    e = r.get_json()
    assert e["left_eye"] == {"iop": {"value": 30, "method": "icare"}} and e["version"] == 2
    assert e["right_eye"]["iop"]["value"] == 16.5
    r = d.patch(f"{BASE}/exams/{eid}", json={"version": 1, "notes": "stale"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    r = d.patch(f"{BASE}/exams/{eid}", json={"version": 2, "right_eye": {"iop": {"value": 99}}})
    assert r.status_code == 422


def test_delete_undo_purge(oph, app):
    from backend.app.models import Visit
    from backend.app.modules.ophthalmology.models import OphthalmologyExam
    d, eid = oph["doc"], oph["exam"]["id"]
    r = d.delete(f"{BASE}/exams/{eid}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert d.get(f"{BASE}/exams/{eid}").status_code == 404
    assert d.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert d.get(f"{BASE}/exams/{eid}").status_code == 200
    token = d.delete(f"{BASE}/exams/{eid}").get_json()["undo_token"]
    expire_and_purge(app, token)
    assert platform_rows(app, select(OphthalmologyExam.id).where(OphthalmologyExam.id == eid)) == []
    assert platform_rows(app, select(Visit.id).where(Visit.id == oph["exam"]["visit_id"])) == []


def test_summary(oph, app):
    from backend.app.core import tenancy
    from backend.app.modules.ophthalmology import service
    from tests.test_dermatology_support import principal_for
    a = oph["a"]
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        s = service.patient_summary(principal_for(app, a["users"]["oph_doc"]["id"]), oph["pid"])
        assert s["exam_count"] == 1 and s["recent"][0]["od"] == {"va": "6/6", "iop": 16.5}
        assert service.patient_summary(principal_for(app, a["users"]["derm_doc"]["id"]), oph["pid"]) is None


def test_department_list_and_glasses_pdf(oph, world, client_for):
    a, d, eid = oph["a"], oph["doc"], oph["exam"]["id"]
    r = d.get(f"{BASE}/exams?department_id={a['departments']['ophthalmology']}").get_json()
    assert r["total"] == 1 and r["items"][0]["patient"]["id"] == oph["pid"]
    for lang in ("en", "ar"):
        r = d.get(f"{BASE}/exams/{eid}/glasses.pdf?lang={lang}")
        assert r.status_code == 200 and r.data.startswith(b"%PDF") and r.mimetype == "application/pdf"
    assert client_for(a["users"]["derm_doc"]).get(f"{BASE}/exams/{eid}/glasses.pdf").status_code == 404
    assert client_for(world["B"]["users"]["manager"]).get(f"{BASE}/exams/{eid}/glasses.pdf").status_code == 404
    d.patch(f"{BASE}/exams/{eid}", json={"version": 1, "glasses": {}})
    assert d.get(f"{BASE}/exams/{eid}/glasses.pdf").status_code == 422
