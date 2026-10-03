from decimal import Decimal

import pytest

from backend.app.modules.laboratory.flags import compute_flag, ranges_for
from tests.conftest import ApiClient
from tests.test_laboratory_helpers import make_dept_manager

GLU = {"code": "GLU", "name": "Glucose", "unit": "mg/dL", "result_type": "numeric", "ref_low": "70",
       "ref_high": "110", "price": "5.00"}


def test_catalog_management_permissions(app, world, client_for):
    a = world["A"]
    mgr = client_for(a["users"]["manager"])
    r = mgr.post("/api/v1/lab/categories", json={"name": "Biochemistry"})
    assert r.status_code == 201, r.get_json()
    cat = r.get_json()["id"]
    r = mgr.post("/api/v1/lab/tests", json=dict(GLU, category_id=cat))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["price"] == "5.00" and r.get_json()["ref_high"] == "110"

    # Laboratory department manager may manage tests.
    lab_head = client_for(make_dept_manager(app, a, "laboratory", "labhead"))
    r = lab_head.post("/api/v1/lab/tests", json={"code": "HB", "name": "Hemoglobin", "ref_low_male": "13.5",
                                                  "ref_high_male": "17.5", "ref_low_female": "12",
                                                  "ref_high_female": "15.5"})
    assert r.status_code == 201, r.get_json()
    assert lab_head.get("/api/v1/lab/meta").get_json()["can"]["manage_tests"] is True

    # Dentistry department manager has the permission code but not a laboratory department.
    dent_head = client_for(a["users"]["dent_head"])
    assert dent_head.post("/api/v1/lab/tests", json=dict(GLU, code="X1")).status_code == 403
    assert dent_head.get("/api/v1/lab/meta").get_json()["can"]["manage_tests"] is False
    # Doctors (even in the lab) and receptionists cannot manage tests.
    assert client_for(a["users"]["lab_doc"]).post("/api/v1/lab/tests", json=dict(GLU, code="X2")).status_code == 403
    assert client_for(a["users"]["rec_center"]).post("/api/v1/lab/categories",
                                                     json={"name": "X"}).status_code == 403
    # Everyone who can request may read the catalog.
    r = client_for(a["users"]["dent_doc1"]).get("/api/v1/lab/tests")
    assert r.status_code == 200 and {t["code"] for t in r.get_json()["items"]} == {"GLU", "HB"}

    # Superadmin in support mode must NOT manage lab tests.
    sa = ApiClient(app)
    assert sa.login(world["superadmin"]["email"]).status_code == 200
    assert sa.post("/api/v1/auth/support/enter", json={"center_id": a["center_id"]}).status_code == 200
    assert sa.post("/api/v1/lab/tests", json=dict(GLU, code="SA")).status_code == 403
    tid = r.get_json()["items"][0]["id"]
    assert sa.patch(f"/api/v1/lab/tests/{tid}", json={"version": 1, "name": "x"}).status_code == 403

    # Cross-tenant: center B manager cannot see or edit center A tests.
    b_mgr = client_for(world["B"]["users"]["manager"])
    assert b_mgr.get(f"/api/v1/lab/tests/{tid}").status_code == 404
    assert b_mgr.patch(f"/api/v1/lab/tests/{tid}", json={"version": 1, "name": "x"}).status_code == 404
    assert b_mgr.get("/api/v1/lab/tests").get_json()["items"] == []


def test_catalog_validation_version_and_delete_undo(app, world, client_for):
    mgr = client_for(world["A"]["users"]["manager"])
    r = mgr.post("/api/v1/lab/tests", json={"code": "UR", "name": "Urine protein", "result_type": "choice"})
    assert r.status_code == 422 and "choices" in r.get_json()["error"]["details"]
    r = mgr.post("/api/v1/lab/tests", json={"code": "UR", "name": "Urine protein", "result_type": "choice",
                                            "choices": ["Negative", "+"], "normal_choices": ["Trace"]})
    assert r.status_code == 422 and "normal_choices" in r.get_json()["error"]["details"]
    r = mgr.post("/api/v1/lab/tests", json=dict(GLU, ref_low="200"))
    assert r.status_code == 422 and "ref_high" in r.get_json()["error"]["details"]
    r = mgr.post("/api/v1/lab/tests", json=GLU)
    assert r.status_code == 201
    t = r.get_json()
    assert mgr.post("/api/v1/lab/tests", json=GLU).status_code == 422  # duplicate code

    r = mgr.patch(f"/api/v1/lab/tests/{t['id']}", json={"version": t["version"], "ref_high": "120"})
    assert r.status_code == 200 and r.get_json()["ref_high"] == "120"
    r = mgr.patch(f"/api/v1/lab/tests/{t['id']}", json={"version": t["version"], "ref_high": "130"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"

    r = mgr.delete(f"/api/v1/lab/tests/{t['id']}")
    assert r.status_code == 202
    assert mgr.get(f"/api/v1/lab/tests/{t['id']}").status_code == 404
    assert mgr.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    assert mgr.get(f"/api/v1/lab/tests/{t['id']}").status_code == 200


class _T:
    def __init__(self, **kw):
        for k in ("ref_low", "ref_high", "ref_low_male", "ref_high_male", "ref_low_female", "ref_high_female"):
            setattr(self, k, kw.get(k))


def test_abnormal_flag_computation():
    assert compute_flag("numeric", "65", low=70, high=110) == (Decimal("65"), "L")
    assert compute_flag("numeric", "110", low=70, high=110) == (Decimal("110"), "N")
    assert compute_flag("numeric", "110,5", low=70, high=110) == (Decimal("110.5"), "H")
    assert compute_flag("numeric", "5", low=None, high=None) == (Decimal("5"), None)
    assert compute_flag("numeric", "3", low=None, high=10) == (Decimal("3"), "N")
    assert compute_flag("numeric", "", low=1, high=2) == (None, None)
    with pytest.raises(ValueError):
        compute_flag("numeric", "abc", low=1, high=2)
    assert compute_flag("choice", "+", choices=["Negative", "+"], normal_choices=["Negative"]) == (None, "A")
    assert compute_flag("choice", "Negative", choices=["Negative", "+"], normal_choices=["Negative"]) == (None, "N")
    with pytest.raises(ValueError):
        compute_flag("choice", "??", choices=["Negative", "+"])
    assert compute_flag("text", "Gram positive cocci", abnormal=True) == (None, "A")
    assert compute_flag("text", "No growth") == (None, None)
    t = _T(ref_low=1, ref_high=2, ref_low_male=13, ref_high_male=17)
    assert ranges_for(t, "male") == (13, 17)
    assert ranges_for(t, "female") == (1, 2)
    assert ranges_for(t, None) == (1, 2)
