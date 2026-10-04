"""Dental X-rays: upload validation, metadata, clinic-only file visibility, delete + undo + purge."""
import io

import pytest

from backend.app.core import tenancy
from backend.app.extensions import db
from tests.test_dentistry import BASE, expire_and_purge, make_patient

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 64
PDF = b"%PDF-1.4\n%test\n" + b"0" * 64


@pytest.fixture()
def dent(app, world, client_for):
    a = world["A"]
    return {"A": a, "B": world["B"], "pid": make_patient(app, a), "c": client_for}


def _upload(c, pid, content=PNG, name="bitewing.png", **form):
    data = {"file": (io.BytesIO(content), name), "type": "bitewing", "tooth_tag": "14"} | form
    return c.post(f"{BASE}/patients/{pid}/xrays", data=data, content_type="multipart/form-data")


def _principal(app, center, key):
    from backend.app.authz.principal import build_principal
    from backend.app.models import User
    u = db.session.get(User, center["users"][key]["id"])
    return build_principal(u)


def test_upload_metadata_and_file_record(app, dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    r = _upload(c, pid, notes="pre-op", date="2026-09-01", time="10:30")
    assert r.status_code == 201, r.get_json()
    x = r.get_json()
    assert x["type"] == "bitewing" and x["tooth_tag"] == "14" and x["date"] == "2026-09-01" and x["time"] == "10:30"
    assert x["filename"] == "bitewing.png" and x["file"]["mime_type"] == "image/png"
    assert x["file"]["url"] == f"/api/v1/files/{x['file']['id']}/content"
    from backend.app.models import StoredFile
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        f = db.session.get(StoredFile, x["file"]["id"])
        assert (f.category, f.owner_type, f.owner_id) == ("xray", "dental_xray", x["id"])
        assert (f.clinic_id, f.department_id, f.patient_id) == (a["clinics"]["dent1"], a["departments"]["dentistry"],
                                                                pid)
    lst = c.get(f"{BASE}/patients/{pid}/xrays?type=bitewing").get_json()["items"]
    assert [i["id"] for i in lst] == [x["id"]]
    assert c.get(f"{BASE}/patients/{pid}/xrays?type=panoramic").get_json()["items"] == []
    assert c.get(f"{BASE}/xrays/{x['id']}/verify").get_json()["verified"] is True
    # metadata edit with optimistic locking
    r = c.patch(f"{BASE}/xrays/{x['id']}", json={"type": "panoramic", "filename": "pano.png", "version": 1})
    assert r.status_code == 200 and r.get_json()["type"] == "panoramic" and r.get_json()["version"] == 2
    r = c.patch(f"{BASE}/xrays/{x['id']}", json={"notes": "late edit", "version": 1})
    assert r.status_code == 409
    assert c.patch(f"{BASE}/xrays/{x['id']}", json={"type": "mri", "version": 2}).status_code == 422
    ev = c.get(f"{BASE}/patients/{pid}/timeline").get_json()["events"]
    assert any(e["type"] == "xray" and e["file_id"] == x["file"]["id"] for e in ev)
    # visit link is mirrored on the stored file
    vid = c.post(f"{BASE}/treatments", json={"patient_id": pid, "procedure": "rct", "create_visit": True}
                 ).get_json()["visit_id"]
    x2 = _upload(c, pid, visit_id=str(vid)).get_json()
    assert x2["visit_id"] == vid
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        assert db.session.get(StoredFile, x2["file"]["id"]).visit_id == vid


def test_upload_validation(dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    r = _upload(c, pid, PDF, "report.pdf")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "xray_type_not_allowed"
    r = _upload(c, pid, PDF, "fake.png")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "file_content_mismatch"
    r = _upload(c, pid, b"MZ\x90\x00" + b"\x00" * 64, "evil.exe")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "file_type_not_allowed"
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (15 * 1024 * 1024)
    r = _upload(c, pid, big, "huge.png")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "file_too_large"
    r = c.post(f"{BASE}/patients/{pid}/xrays", data={"type": "bitewing"}, content_type="multipart/form-data")
    assert r.status_code == 422
    assert _upload(c, pid, type="mri").status_code == 422
    assert c.get(f"{BASE}/patients/{pid}/xrays").get_json()["items"] == []


def test_xray_scope_and_permissions(app, dent):
    a, b, pid = dent["A"], dent["B"], dent["pid"]
    x = _upload(dent["c"](a["users"]["dent_doc1"]), pid).get_json()
    doc2, derm = dent["c"](a["users"]["dent_doc2"]), dent["c"](a["users"]["derm_doc"])
    mb = dent["c"](b["users"]["manager"])
    for cl in (doc2, derm, mb):
        assert cl.get(f"{BASE}/xrays/{x['id']}").status_code == 404
        assert cl.patch(f"{BASE}/xrays/{x['id']}", json={"notes": "x", "version": 1}).status_code == 404
        assert cl.delete(f"{BASE}/xrays/{x['id']}").status_code == 404
    assert _upload(mb, pid, clinic_id=str(b["clinics"]["dent1"])).status_code == 404
    rec = dent["c"](a["users"]["rec_dent1"])
    assert rec.get(f"{BASE}/xrays/{x['id']}").status_code == 200
    assert _upload(rec, pid).status_code == 403
    assert rec.delete(f"{BASE}/xrays/{x['id']}").status_code == 403
    assert dent["c"](a["users"]["dent_head"]).get(f"{BASE}/xrays/{x['id']}").status_code == 200
    # the stored file itself is only visible to the owning clinic's scope
    from backend.app.core.errors import NotFound
    from backend.app.services import files
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        assert files.get_visible(_principal(app, a, "dent_doc1"), x["file"]["id"]).id == x["file"]["id"]
        assert files.get_visible(_principal(app, a, "dent_head"), x["file"]["id"])
        for key in ("dent_doc2", "derm_doc"):
            with pytest.raises(NotFound):
                files.get_visible(_principal(app, a, key), x["file"]["id"])
    content_url = x["file"]["url"]
    if any(r.rule == "/api/v1/files/<int:file_id>/content" for r in app.url_map.iter_rules()):
        assert doc2.get(content_url).status_code == 404
        assert mb.get(content_url).status_code == 404
        r = dent["c"](a["users"]["dent_doc1"]).get(content_url)
        assert r.status_code == 200 and r.data == PNG


def test_xray_delete_undo_and_purge_removes_bytes(app, dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    x = _upload(c, pid).get_json()
    def generic_ids():
        return [f["id"] for f in c.get(f"/api/v1/files?patient_id={pid}").get_json()["items"]]
    assert x["file"]["id"] in generic_ids()
    r = c.delete(f"{BASE}/xrays/{x['id']}")
    assert r.status_code == 202
    assert c.get(f"{BASE}/xrays/{x['id']}").status_code == 404
    assert c.get(f"{BASE}/patients/{pid}/xrays").get_json()["items"] == []
    assert x["file"]["id"] not in generic_ids()  # hidden from generic file lists during the undo window
    assert c.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    assert c.get(f"{BASE}/xrays/{x['id']}").status_code == 200
    assert x["file"]["id"] in generic_ids()
    from backend.app.core.storage import get_storage
    from backend.app.models import StoredFile
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        key = db.session.get(StoredFile, x["file"]["id"]).storage_key
        assert get_storage().exists(key)
    assert c.delete(f"{BASE}/xrays/{x['id']}").status_code == 202
    expire_and_purge(app)
    from backend.app.modules.dentistry.models import XRay
    with app.app_context(), tenancy.scoped("platform"):
        assert db.session.get(XRay, x["id"]) is None
        assert db.session.get(StoredFile, x["file"]["id"]) is None
        assert not get_storage().exists(key)
