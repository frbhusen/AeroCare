"""Dermatology visits: environment, scope, validation, versioning, delete/undo, photos."""
import pytest
from sqlalchemy import select

from tests.test_dermatology_support import expire_and_purge, make_patient, platform_rows, png_upload, upload

BASE = "/api/v1/dermatology"


def _create(client, a, pid, **kw):
    body = {"patient_id": pid, "clinic_id": a["clinics"]["derm1"], "condition": "Acne vulgaris",
            "severity": "moderate", "affected_areas": ["face", "upper_back", "face"], "symptoms": "Papules",
            "diagnosis": "Acne", "treatment": "Topical retinoid", "extra": {"fitzpatrick": "III"}}
    body.update(kw)
    return client.post(f"{BASE}/visits", json=body)


@pytest.fixture()
def derm(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    doc = client_for(a["users"]["derm_doc"])
    r = _create(doc, a, pid)
    assert r.status_code == 201, r.get_json()
    return {"a": a, "pid": pid, "doc": doc, "rec": r.get_json()}


def test_meta_and_regions(world, client_for):
    c = client_for(world["A"]["users"]["derm_doc"])
    m = c.get(f"{BASE}/meta").get_json()
    assert m["severities"] == ["mild", "moderate", "severe"]
    codes = {r["code"] for r in m["body_regions"]["regions"]}
    assert {"face", "underarm_left", "full_legs", "bikini", "upper_back"} <= codes
    face = next(r for r in m["body_regions"]["regions"] if r["code"] == "face")
    assert face["ar"] and face["views"] == ["front"] and face["group"] == "head_neck"
    assert c.get(f"{BASE}/body-regions").status_code == 200


def test_create_get_list(derm, client_for):
    rec, a, doc = derm["rec"], derm["a"], derm["doc"]
    assert rec["affected_areas"] == ["face", "upper_back"]  # de-duplicated
    assert rec["clinic_id"] == a["clinics"]["derm1"] and rec["owns_visit"] is True
    assert rec["author_role"] == "doctor" and rec["version"] == 1 and rec["visit_type"] == "consultation"
    assert rec["extra"] == {"fitzpatrick": "III"}
    got = doc.get(f"{BASE}/visits/{rec['id']}").get_json()
    assert got["diagnosis"] == "Acne" and got["photo_count"] == 0
    lst = doc.get(f"{BASE}/patients/{derm['pid']}/visits").get_json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == rec["id"]
    lst = doc.get(f"{BASE}/patients/{derm['pid']}/visits?clinic_id={a['clinics']['derm1']}").get_json()
    assert lst["total"] == 1
    # Manager (center-wide) sees it too.
    m = client_for(a["users"]["manager"])
    assert m.get(f"{BASE}/visits/{rec['id']}").status_code == 200


def test_environment_enforced(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    m = client_for(a["users"]["manager"])
    r = _create(m, a, pid, clinic_id=a["clinics"]["dent1"])
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "wrong_environment"
    # List filtered by a non-dermatology clinic is rejected too.
    r = m.get(f"{BASE}/patients/{pid}/visits?clinic_id={a['clinics']['dent1']}")
    assert r.status_code == 422
    # A derm doctor cannot target a clinic outside their scope (404, not revealed).
    d = client_for(a["users"]["derm_doc"])
    assert _create(d, a, pid, clinic_id=a["clinics"]["dent1"]).status_code == 404


def test_clinic_and_department_isolation(derm, client_for):
    a, rid, pid = derm["a"], derm["rec"]["id"], derm["pid"]
    dent = client_for(a["users"]["dent_doc1"])
    assert dent.get(f"{BASE}/visits/{rid}").status_code == 404
    assert dent.get(f"{BASE}/patients/{pid}/visits").status_code == 404
    assert dent.patch(f"{BASE}/visits/{rid}", json={"version": 1, "notes": "x"}).status_code == 404
    assert dent.delete(f"{BASE}/visits/{rid}").status_code == 404
    rec_dent1 = client_for(a["users"]["rec_dent1"])
    assert rec_dent1.get(f"{BASE}/visits/{rid}").status_code == 404
    # Receptionist scoped to derm1: may view, may not edit/delete/create (no grant).
    rec = client_for(a["users"]["rec_multi"])
    assert rec.get(f"{BASE}/visits/{rid}").status_code == 200
    assert rec.patch(f"{BASE}/visits/{rid}", json={"version": 1, "notes": "x"}).status_code == 403
    assert rec.delete(f"{BASE}/visits/{rid}").status_code == 403
    assert _create(rec, a, pid).status_code == 403


def test_cross_tenant_404(derm, world, client_for):
    b = client_for(world["B"]["users"]["manager"])
    rid, pid = derm["rec"]["id"], derm["pid"]
    assert b.get(f"{BASE}/visits/{rid}").status_code == 404
    assert b.get(f"{BASE}/patients/{pid}/visits").status_code == 404
    assert b.patch(f"{BASE}/visits/{rid}", json={"version": 1, "notes": "x"}).status_code == 404
    assert b.get(f"{BASE}/visits/{rid}/photos").status_code == 404
    # Center B cannot create a record for a center A patient in its own clinic.
    r = b.post(f"{BASE}/visits", json={"patient_id": pid, "clinic_id": world["B"]["clinics"]["derm1"]})
    assert r.status_code == 404


def test_validation(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    r = _create(d, a, pid, severity="extreme", affected_areas=["face", "tail"])
    assert r.status_code == 422
    det = r.get_json()["error"]["details"]
    assert "severity" in det and "affected_areas" in det
    r = d.post(f"{BASE}/visits", json={"condition": "x"})
    assert r.status_code == 422 and set(r.get_json()["error"]["details"]) == {"patient_id", "clinic_id"}


def test_update_and_version_conflict(derm):
    doc, rid = derm["doc"], derm["rec"]["id"]
    r = doc.patch(f"{BASE}/visits/{rid}", json={"version": 1, "severity": "severe", "title": "Review",
                                                "affected_areas": ["chest"]})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["severity"] == "severe" and body["title"] == "Review" and body["version"] == 2
    assert body["diagnosis"] == "Acne"  # untouched
    r = doc.patch(f"{BASE}/visits/{rid}", json={"version": 1, "severity": "mild"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    assert doc.patch(f"{BASE}/visits/{rid}", json={"severity": "mild"}).status_code == 422


def test_delete_undo_and_purge(derm, app):
    from backend.app.models import Visit
    from backend.app.modules.dermatology.models import DermVisitRecord
    doc, rid, pid = derm["doc"], derm["rec"]["id"], derm["pid"]
    vid = derm["rec"]["visit_id"]
    r = doc.delete(f"{BASE}/visits/{rid}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert doc.get(f"{BASE}/visits/{rid}").status_code == 404
    assert doc.get(f"{BASE}/patients/{pid}/visits").get_json()["total"] == 0
    assert doc.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert doc.get(f"{BASE}/visits/{rid}").status_code == 200
    # Delete for real: the owned visit (and the record via cascade) are permanently removed.
    token = doc.delete(f"{BASE}/visits/{rid}").get_json()["undo_token"]
    assert upload(doc, f"{BASE}/visits/{rid}/photos", png_upload()).status_code == 404
    expire_and_purge(app, token)
    assert platform_rows(app, select(DermVisitRecord.id).where(DermVisitRecord.id == rid)) == []
    assert platform_rows(app, select(Visit.id).where(Visit.id == vid)) == []


def test_attach_to_existing_visit(derm, client_for, app):
    from backend.app.models import Visit
    doc, a, pid = derm["doc"], derm["a"], derm["pid"]
    # A laser session creates a 'session' visit; attach a dermatology record to it.
    s = doc.post(f"{BASE}/laser/sessions", json={"patient_id": pid, "clinic_id": a["clinics"]["derm1"],
                                                  "areas": [{"region": "face", "side": "front"}]}).get_json()
    vid = s["visit_id"]
    r = doc.post(f"{BASE}/visits", json={"visit_id": vid, "condition": "Folliculitis"})
    assert r.status_code == 201, r.get_json()
    rec = r.get_json()
    assert rec["owns_visit"] is False and rec["visit_id"] == vid and rec["patient_id"] == pid
    r = doc.post(f"{BASE}/visits", json={"visit_id": vid})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "already_exists"
    # Visit fields can't be edited through a non-owning record.
    r = doc.patch(f"{BASE}/visits/{rec['id']}", json={"version": 1, "title": "x"})
    assert r.status_code == 422
    # Deleting a non-owning record keeps the visit (and the laser session).
    token = doc.delete(f"{BASE}/visits/{rec['id']}").get_json()["undo_token"]
    expire_and_purge(app, token)
    assert platform_rows(app, select(Visit.id).where(Visit.id == vid)) != []
    assert doc.get(f"{BASE}/laser/sessions/{s['id']}").status_code == 200
    # Another clinic's visit cannot be attached.
    dent_visit = derm_visit_in(app, a, pid, "dent1")
    m = client_for(a["users"]["manager"])
    r = m.post(f"{BASE}/visits", json={"visit_id": dent_visit})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "wrong_environment"


def derm_visit_in(app, a, pid, clinic_key):
    from backend.app.core import tenancy
    from backend.app.core.timeutil import utcnow
    from backend.app.extensions import db
    from backend.app.models import Clinic, Visit
    with app.app_context(), tenancy.scoped("platform"):
        c = db.session.get(Clinic, a["clinics"][clinic_key])
        v = Visit(health_center_id=a["center_id"], patient_id=pid, department_id=c.department_id, clinic_id=c.id,
                  visit_at=utcnow(), visit_type="consultation", author_name="x")
        db.session.add(v)
        db.session.commit()
        return v.id


def test_photos_visible_only_to_clinic(derm, client_for, app):
    from backend.app.core import tenancy
    from backend.app.core.errors import NotFound
    from backend.app.core.storage import get_storage
    from backend.app.extensions import db
    from backend.app.models import StoredFile
    from backend.app.services import files as file_service
    from tests.test_dermatology_support import principal_for
    a, doc, rid = derm["a"], derm["doc"], derm["rec"]["id"]
    r = upload(doc, f"{BASE}/visits/{rid}/photos", png_upload())
    assert r.status_code == 201, r.get_json()
    f = r.get_json()["items"][0]
    assert f["category"] == "photo" and f["owner_type"] == "derm_visit" and f["owner_id"] == rid
    assert f["clinic_id"] == a["clinics"]["derm1"] and f["visit_id"] == derm["rec"]["visit_id"]
    bad = upload(doc, f"{BASE}/visits/{rid}/photos", {"files": (png_upload()["files"][0], "x.png"),
                                                       "category": "xray"})
    assert bad.status_code == 422
    assert doc.get(f"{BASE}/visits/{rid}/photos").get_json()["items"][0]["id"] == f["id"]
    assert doc.get(f"{BASE}/visits/{rid}").get_json()["photo_count"] == 1
    assert client_for(a["users"]["rec_multi"]).get(f"{BASE}/visits/{rid}/photos").status_code == 200
    assert client_for(a["users"]["dent_doc1"]).get(f"{BASE}/visits/{rid}/photos").status_code == 404
    assert upload(client_for(a["users"]["dent_doc1"]), f"{BASE}/visits/{rid}/photos",
                  png_upload()).status_code == 404
    with app.app_context():
        with tenancy.scoped("tenant", a["center_id"]):
            p_dent = principal_for(app, a["users"]["dent_doc1"]["id"])
            with pytest.raises(NotFound):
                file_service.get_visible(p_dent, f["id"])
            p_derm = principal_for(app, a["users"]["derm_doc"]["id"])
            assert file_service.get_visible(p_derm, f["id"]).id == f["id"]
            key = db.session.get(StoredFile, f["id"]).storage_key
        db.session.rollback()
    # Purging the visit removes the file row and its bytes.
    token = doc.delete(f"{BASE}/visits/{rid}").get_json()["undo_token"]
    expire_and_purge(app, token)
    assert platform_rows(app, select(StoredFile.id).where(StoredFile.id == f["id"])) == []
    with app.app_context():
        assert not get_storage().path(key).exists()


def test_summary_provider(derm, app, client_for):
    from backend.app.core import tenancy
    from backend.app.modules.dermatology import service
    from tests.test_dermatology_support import principal_for
    a = derm["a"]
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        s = service.patient_summary(principal_for(app, a["users"]["derm_doc"]["id"]), derm["pid"])
        assert s["visit_count"] == 1 and s["recent"][0]["condition"] == "Acne vulgaris"
        assert service.patient_summary(principal_for(app, a["users"]["dent_doc1"]["id"]), derm["pid"]) is None


def test_department_list(derm, world, client_for):
    a, doc = derm["a"], derm["doc"]
    dept = a["departments"]["dermatology"]
    r = doc.get(f"{BASE}/visits?department_id={dept}").get_json()
    assert r["total"] == 1 and r["items"][0]["patient"]["full_name"] == "Ali Hassan"
    assert r["items"][0]["patient"]["display_code"].startswith("PAT-")
    assert doc.get(f"{BASE}/visits?q=ali").get_json()["total"] == 1
    assert doc.get(f"{BASE}/visits?q=zzz").get_json()["total"] == 0
    assert doc.get(f"{BASE}/visits?severity=moderate").get_json()["total"] == 1
    assert doc.get(f"{BASE}/visits?severity=mild").get_json()["total"] == 0
    # Other department / other center: nothing leaks.
    assert doc.get(f"{BASE}/visits?department_id={a['departments']['dentistry']}").status_code == 404
    assert client_for(a["users"]["dent_doc1"]).get(f"{BASE}/visits").get_json()["total"] == 0
    assert client_for(world["B"]["users"]["manager"]).get(f"{BASE}/visits").get_json()["total"] == 0
