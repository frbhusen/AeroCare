import io

import pytest
from sqlalchemy import select

from backend.app.core import tenancy
from backend.app.core.errors import NotFound
from backend.app.extensions import db
from backend.app.models import FileShare
from backend.app.services.clinical import get_visit
from tests.test_laboratory_helpers import PNG, make_patient, make_visit, notifications, principal_for

BASE = "/api/v1/radiology"


@pytest.fixture()
def rad(app, world):
    a = world["A"]
    return {"a": a, "patient": make_patient(app, a, "gen1", "derm1", "dent1", name="Sara", gender="female")}


def _upload(client, sid):
    return client.c.post(f"{BASE}/studies/{sid}/images", data={"files": (io.BytesIO(PNG), "chest.png")},
                         headers=client._h(None), content_type="multipart/form-data")


def _to_finalized(client_for, rad):
    a = rad["a"]
    gen = client_for(a["users"]["gen_doc"])
    raddoc = client_for(a["users"]["rad_doc"])
    s = gen.post(f"{BASE}/studies", json={"patient_id": rad["patient"], "exam_type": "x_ray",
                                          "body_region": "Chest", "clinical_question": "Pneumonia?"}).get_json()
    s = raddoc.post(f"{BASE}/studies/{s['id']}/start", json={"version": s["version"]}).get_json()
    img = _upload(raddoc, s["id"]).get_json()["items"][0]
    s = raddoc.put(f"{BASE}/studies/{s['id']}/report", json={"version": s["version"], "findings": "Clear lungs",
                                                             "impression": "Normal"}).get_json()
    s = raddoc.post(f"{BASE}/studies/{s['id']}/finalize", json={"version": s["version"]}).get_json()
    return s, img, gen, raddoc


def test_full_radiology_workflow(app, world, client_for, rad):
    a = rad["a"]
    gen = client_for(a["users"]["gen_doc"])
    raddoc = client_for(a["users"]["rad_doc"])
    derm = client_for(a["users"]["derm_doc"])

    assert gen.post(f"{BASE}/studies", json={"patient_id": rad["patient"]}).status_code == 422
    r = gen.post(f"{BASE}/studies", json={"patient_id": rad["patient"], "exam_type": "ct", "body_region": "Head",
                                          "clinical_question": "Bleed?", "priority": "urgent"})
    assert r.status_code == 201, r.get_json()
    s = r.get_json()
    assert s["status"] == "requested" and s["radiology_clinic"]["id"] == a["clinics"]["rad1"]
    assert notifications(raddoc, "radiology_request")

    wl = raddoc.get(f"{BASE}/worklist").get_json()["items"]
    assert [x["id"] for x in wl] == [s["id"]] and wl[0]["patient"]["full_name"] == "Sara"
    # Radiology staff cannot browse unrelated specialty records.
    vid = make_visit(app, a, rad["patient"], "derm1")
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        with pytest.raises(NotFound):
            get_visit(principal_for(a, "rad_doc"), vid)
        db.session.rollback()
    # Requester cannot process; unrelated clinic cannot see.
    assert gen.post(f"{BASE}/studies/{s['id']}/start", json={"version": s["version"]}).status_code == 403
    assert derm.get(f"{BASE}/studies/{s['id']}").status_code == 404

    r = raddoc.post(f"{BASE}/studies/{s['id']}/schedule", json={"version": s["version"],
                                                                "scheduled_at": "2026-10-10T10:00"})
    assert r.status_code == 200 and r.get_json()["status"] == "scheduled"
    s = r.get_json()
    # Images only once started.
    assert _upload(raddoc, s["id"]).status_code == 409
    s = raddoc.post(f"{BASE}/studies/{s['id']}/start", json={"version": s["version"]}).get_json()
    assert s["status"] == "in_progress" and s["performed_at"]
    r = _upload(raddoc, s["id"])
    assert r.status_code == 201, r.get_json()
    img = r.get_json()["items"][0]
    assert img["category"] == "radiology_image" and img["clinic_id"] == a["clinics"]["rad1"]
    assert gen.post(f"{BASE}/studies/{s['id']}/images").status_code == 403
    # Report with version conflict.
    r = raddoc.put(f"{BASE}/studies/{s['id']}/report", json={"version": s["version"] - 1, "findings": "x"})
    assert r.status_code == 409
    r = raddoc.put(f"{BASE}/studies/{s['id']}/report", json={"version": s["version"], "findings": "No bleed",
                                                             "impression": "Normal CT"})
    assert r.status_code == 200 and r.get_json()["status"] == "reported"
    s = r.get_json()
    assert s["report"]["radiologist"]["name"].startswith("rad_doc")
    # Requester does not see the draft report or images, nor the image file.
    d = gen.get(f"{BASE}/studies/{s['id']}").get_json()
    assert d["report"] is None and d["images"] == []
    assert gen.get(f"/api/v1/files/{img['id']}/content").status_code == 404
    assert gen.get(f"{BASE}/studies/{s['id']}/report").status_code == 409
    assert gen.post(f"{BASE}/studies/{s['id']}/finalize", json={"version": s["version"]}).status_code == 403

    r = raddoc.post(f"{BASE}/studies/{s['id']}/finalize", json={"version": s["version"]})
    assert r.status_code == 200 and r.get_json()["status"] == "finalized"
    s = r.get_json()
    assert notifications(gen, "radiology_result_available")
    # Final report + images visible to requester; image shared with the requesting clinic.
    d = gen.get(f"{BASE}/studies/{s['id']}").get_json()
    assert d["report"]["impression"] == "Normal CT" and [i["id"] for i in d["images"]] == [img["id"]]
    assert gen.get(f"/api/v1/files/{img['id']}/content").status_code == 200
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        shares = db.session.execute(select(FileShare.file_id).where(
            FileShare.target_clinic_id == a["clinics"]["gen1"])).scalars().all()
        assert img["id"] in shares and d["report_file_id"] in shares
    assert gen.get(f"{BASE}/studies/{s['id']}/report?format=pdf").data.startswith(b"%PDF")
    # Not visible to unrelated clinics (even though they see the patient) nor in their patient list.
    assert derm.get(f"{BASE}/studies/{s['id']}").status_code == 404
    assert derm.get(f"{BASE}/patients/{rad['patient']}/studies").get_json()["items"] == []
    assert derm.get(f"/api/v1/files/{img['id']}/content").status_code == 404
    # Managers see it.
    assert client_for(a["users"]["manager"]).get(f"{BASE}/studies/{s['id']}").status_code == 200
    # Cross-tenant 404.
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f"{BASE}/studies/{s['id']}").status_code == 404
    assert client_for(world["B"]["users"]["rad_doc"]).get(f"{BASE}/worklist").get_json()["items"] == []


def test_explicit_share_and_revoke(app, world, client_for, rad):
    a = rad["a"]
    s, img, gen, raddoc = _to_finalized(client_for, rad)
    assert s["status"] == "finalized"
    derm = client_for(a["users"]["derm_doc"])
    assert derm.get(f"{BASE}/studies/{s['id']}").status_code == 404
    # Unrelated doctors cannot share; the requesting clinic doctor can.
    assert derm.post(f"{BASE}/studies/{s['id']}/shares",
                     json={"target_clinic_id": a["clinics"]["derm1"]}).status_code == 404
    assert gen.post(f"{BASE}/studies/{s['id']}/shares", json={"target_clinic_id": a["clinics"]["derm1"],
                                                              "target_user_id": 1}).status_code == 422
    r = gen.post(f"{BASE}/studies/{s['id']}/shares", json={"target_clinic_id": a["clinics"]["derm1"]})
    assert r.status_code == 201, r.get_json()
    share = r.get_json()
    d = derm.get(f"{BASE}/studies/{s['id']}")
    assert d.status_code == 200 and d.get_json()["access"] == "shared"
    assert d.get_json()["report"]["impression"] == "Normal"
    assert derm.get(f"/api/v1/files/{img['id']}/content").status_code == 200
    assert [x["id"] for x in derm.get(f"{BASE}/patients/{rad['patient']}/studies").get_json()["items"]] == [s["id"]]
    assert not any(d.get_json()["can"].values())
    # Revoke.
    assert gen.delete(f"{BASE}/studies/{s['id']}/shares/{share['id']}").status_code == 200
    assert derm.get(f"{BASE}/studies/{s['id']}").status_code == 404
    assert derm.get(f"/api/v1/files/{img['id']}/content").status_code == 404
    # Requester still sees it after revoking someone else's share.
    assert gen.get(f"/api/v1/files/{img['id']}/content").status_code == 200


def test_radiology_delete_undo_and_cancel(app, world, client_for, rad):
    a = rad["a"]
    gen = client_for(a["users"]["gen_doc"])
    raddoc = client_for(a["users"]["rad_doc"])
    s = gen.post(f"{BASE}/studies", json={"patient_id": rad["patient"], "exam_type": "mri"}).get_json()
    r = gen.patch(f"{BASE}/studies/{s['id']}", json={"version": s["version"], "body_region": "Knee"})
    assert r.status_code == 200
    assert gen.patch(f"{BASE}/studies/{s['id']}", json={"version": s["version"], "body_region": "x"}
                     ).status_code == 409
    assert raddoc.delete(f"{BASE}/studies/{s['id']}").status_code == 403
    r = gen.delete(f"{BASE}/studies/{s['id']}")
    assert r.status_code == 202
    assert raddoc.get(f"{BASE}/studies/{s['id']}").status_code == 404
    assert gen.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    s = gen.get(f"{BASE}/studies/{s['id']}").get_json()
    s = raddoc.post(f"{BASE}/studies/{s['id']}/schedule", json={"version": s["version"],
                                                                "scheduled_at": "2026-10-11T09:00"}).get_json()
    assert gen.delete(f"{BASE}/studies/{s['id']}").status_code == 409
    r = gen.post(f"{BASE}/studies/{s['id']}/cancel", json={"version": s["version"], "reason": "patient refused"})
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    assert raddoc.post(f"{BASE}/studies/{s['id']}/start", json={"version": r.get_json()["version"]}
                       ).status_code == 409
    # Unrelated clinic cannot request for a patient it cannot see.
    other = make_patient(app, a, "dent2", name="Other")
    assert gen.post(f"{BASE}/studies", json={"patient_id": other, "exam_type": "x_ray"}).status_code == 404
