"""Center settings, departments, clinics, plan limits, audit view (center module)."""
import io
import uuid

from sqlalchemy import text

from tests.conftest import PASSWORD, ApiClient
from tests.test_admin_portal import PNG


def _basic_center(app, client_for, world, modules=("dentistry", "dermatology", "laboratory")):
    """Fresh Basic-plan center created through the superadmin API; returns (manager client, info)."""
    sa = client_for(world["superadmin"])
    tag = uuid.uuid4().hex[:6]
    r = sa.post("/api/v1/admin/centers", json={"name": f"Basic {tag}", "plan_code": "basic", "modules": list(modules),
                                               "manager": {"username": f"m{tag}", "name": "Mgr", "password": PASSWORD}})
    assert r.status_code == 201, r.get_json()
    info = r.get_json()
    mgr = client_for(info["manager"]["email"])
    r_pw = mgr.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": f"New-{PASSWORD}-1"})
    assert r_pw.status_code == 200, r_pw.get_json()
    return mgr, info


def test_settings_update_version_and_permissions(world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    s = m.get("/api/v1/center/settings").get_json()
    assert s["can_edit"] is True
    r = m.patch("/api/v1/center/settings", json={"name": "Renamed", "currency": "usd", "primary_color": "#123456",
                                                 "version": s["version"]})
    assert r.status_code == 200 and r.get_json()["currency"] == "USD"
    stale = m.patch("/api/v1/center/settings", json={"name": "X", "version": s["version"]})
    assert stale.status_code == 409 and stale.get_json()["error"]["code"] == "version_conflict"
    assert m.patch("/api/v1/center/settings", json={"primary_color": "blue", "version": r.get_json()["version"]}
                   ).status_code == 422
    # Department manager can view but not edit center-wide settings; receptionist cannot view.
    head = client_for(a["users"]["dent_head"])
    assert head.get("/api/v1/center/settings").status_code == 200
    assert head.patch("/api/v1/center/settings", json={"name": "Y", "version": 99}).status_code == 403
    assert client_for(a["users"]["rec_dent"]).get("/api/v1/center/settings").status_code == 403


def test_logo_upload_storage_and_limits(world, client_for):
    m = client_for(world["A"]["users"]["manager"])
    r = m.post("/api/v1/center/settings/logo", data={"file": (io.BytesIO(PNG), "logo.png")},
               content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["logo_url"]
    logo = m.get("/api/v1/branding/logo")
    assert logo.status_code == 200 and logo.data == PNG
    logo.close()
    # Replacing keeps only one branding file.
    m.post("/api/v1/center/settings/logo", data={"file": (io.BytesIO(PNG), "logo2.png")},
           content_type="multipart/form-data")
    st = m.get("/api/v1/center/storage").get_json()
    assert st["used_bytes"] == len(PNG) and st["quota_bytes"] > 0
    bad = m.post("/api/v1/center/settings/logo", data={"file": (io.BytesIO(b"hello"), "notes.txt")},
                 content_type="multipart/form-data")
    assert bad.status_code == 422
    lim = m.get("/api/v1/center/limits").get_json()
    assert {l["key"] for l in lim["limits"]} >= {"max_doctors", "max_clinics"}
    assert m.delete("/api/v1/center/settings/logo").get_json()["logo_url"] is None


def test_department_rules_and_plan_limit(app, world, client_for):
    m, info = _basic_center(app, client_for, world)
    meta = m.get("/api/v1/center/departments/meta").get_json()
    types = {t["code"]: t for t in meta["types"]}
    assert set(types) == {"dentistry", "dermatology", "laboratory"}
    r = m.post("/api/v1/center/departments", json={"department_type_id": types["dentistry"]["id"]})
    assert r.status_code == 201
    dept = r.get_json()
    assert dept["environment"] == "dentistry"
    # one per type
    assert m.post("/api/v1/center/departments", json={"department_type_id": types["dentistry"]["id"]}
                  ).status_code == 409
    # Basic plan: max 1 department
    r = m.post("/api/v1/center/departments", json={"department_type_id": types["dermatology"]["id"]})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "plan_limit_reached"
    # Not-activated module type rejected
    sa = client_for(world["superadmin"])
    all_types = {t["code"]: t["id"] for t in sa.get("/api/v1/admin/department-types").get_json()["items"]}
    r = m.post("/api/v1/center/departments", json={"department_type_id": all_types["cardiology"]})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "module_not_active"
    # Edit with version
    r = m.patch(f"/api/v1/center/departments/{dept['id']}", json={"name": "Dental Dept", "color": "#aa00aa",
                                                                   "settings": {"slot_minutes": 30},
                                                                   "version": dept["version"]})
    assert r.status_code == 200 and r.get_json()["name"] == "Dental Dept"
    assert m.patch(f"/api/v1/center/departments/{dept['id']}", json={"name": "Z", "version": dept["version"]}
                   ).status_code == 409
    # Clinics: Basic plan max 3
    ids = []
    for i in range(3):
        r = m.post("/api/v1/center/clinics", json={"department_id": dept["id"], "name": f"Clinic {i}",
                                                   "location": f"Room {i}"})
        assert r.status_code == 201, r.get_json()
        ids.append(r.get_json()["id"])
    r = m.post("/api/v1/center/clinics", json={"department_id": dept["id"], "name": "Clinic 4"})
    assert r.get_json()["error"]["code"] == "plan_limit_reached"
    # Department with clinics cannot be deleted
    r = m.delete(f"/api/v1/center/departments/{dept['id']}")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "department_in_use"
    # Delete clinic + undo
    r = m.delete(f"/api/v1/center/clinics/{ids[0]}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert m.get(f"/api/v1/center/clinics/{ids[0]}").status_code == 404
    assert m.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert m.get(f"/api/v1/center/clinics/{ids[0]}").status_code == 200


def test_clinic_validation_and_scope(world, client_for):
    a, b = world["A"], world["B"]
    m = client_for(a["users"]["manager"])
    dent = a["departments"]["dentistry"]
    r = m.post("/api/v1/center/clinics", json={"department_id": dent, "name": "Hours",
                                               "working_hours": {"sat": [["17:00", "09:00"]]}})
    assert r.status_code == 422
    r = m.post("/api/v1/center/clinics", json={"department_id": dent, "name": "Hours",
                                               "working_hours": {"xyz": []}})
    assert r.status_code == 422
    r = m.post("/api/v1/center/clinics", json={"department_id": dent, "name": "Hours", "email": "bad",
                                               "working_hours": {"sat": [["09:00", "13:00"], ["16:00", "20:00"]]}})
    assert r.status_code == 422
    r = m.post("/api/v1/center/clinics", json={"department_id": dent, "name": "Hours",
                                               "working_hours": {"sat": [["09:00", "13:00"], ["16:00", "20:00"]]},
                                               "settings": {"default_duration_minutes": 20}})
    assert r.status_code == 201
    c = r.get_json()
    assert m.post("/api/v1/center/clinics", json={"department_id": dent, "name": "Hours"}).status_code == 409
    # Department manager: own department only
    head = client_for(a["users"]["dent_head"])
    assert head.patch(f"/api/v1/center/clinics/{c['id']}", json={"location": "Floor 2", "version": c["version"]}
                      ).status_code == 200
    assert head.get(f"/api/v1/center/clinics/{a['clinics']['derm1']}").status_code == 404
    assert head.post("/api/v1/center/clinics", json={"department_id": a["departments"]["dermatology"],
                                                     "name": "Nope"}).status_code == 404
    names = {x["department_id"] for x in head.get("/api/v1/center/clinics").get_json()["items"]}
    assert names == {dent}
    # Department manager cannot create departments or toggle activation
    assert head.patch(f"/api/v1/center/departments/{dent}", json={"is_active": False, "version": 1}
                      ).status_code in (409, 422)
    # Doctor cannot edit clinics (no settings.edit)
    doc = client_for(a["users"]["dent_doc1"])
    r = doc.patch(f"/api/v1/center/clinics/{a['clinics']['dent1']}", json={"name": "X", "version": 1})
    assert r.status_code == 403
    # Cross-tenant: center B manager sees nothing of A
    mb = client_for(b["users"]["manager"])
    assert mb.get(f"/api/v1/center/clinics/{c['id']}").status_code == 404
    assert mb.patch(f"/api/v1/center/clinics/{c['id']}", json={"name": "hack", "version": 1}).status_code == 404
    assert mb.delete(f"/api/v1/center/clinics/{c['id']}").status_code == 404
    assert mb.get(f"/api/v1/center/departments/{dent}").status_code == 404
    # Clinic with a doctor cannot be deleted (would orphan staff/history)
    r = m.delete(f"/api/v1/center/clinics/{a['clinics']['dent1']}")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "clinic_in_use"


def test_head_doctor_assignment(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    dent = a["departments"]["dentistry"]
    derm = a["departments"]["dermatology"]
    # a doctor cannot be head
    r = m.put(f"/api/v1/center/departments/{dent}/head", json={"user_id": a["users"]["dent_doc1"]["id"]})
    assert r.status_code == 422
    r = m.put(f"/api/v1/center/departments/{dent}/head", json={"user_id": None})
    assert r.status_code == 200 and r.get_json()["head"] is None
    r = m.put(f"/api/v1/center/departments/{dent}/head", json={"user_id": a["users"]["dent_head"]["id"]})
    assert r.get_json()["head"]["id"] == a["users"]["dent_head"]["id"]
    # create derm department manager -> becomes head automatically
    tag = uuid.uuid4().hex[:6]
    r = m.post("/api/v1/center/staff", json={"role": "department_manager", "username": f"dermhead{tag}",
                                             "name": "Derm Head", "password": PASSWORD, "department_id": derm})
    assert r.status_code == 201 and r.get_json()["is_head"]
    # second manager for the same department is refused
    r = m.post("/api/v1/center/staff", json={"role": "department_manager", "username": f"dermhead2{tag}",
                                             "name": "Derm Head 2", "password": PASSWORD, "department_id": derm})
    assert r.status_code == 409


def test_center_audit_view_scoped_and_immutable(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    dent = a["departments"]["dentistry"]
    m.post("/api/v1/center/clinics", json={"department_id": dent, "name": "Audited"})
    m.post("/api/v1/center/clinics", json={"department_id": a["departments"]["dermatology"], "name": "Audited D"})
    logs = m.get("/api/v1/center/audit?category=clinic").get_json()["items"]
    assert {l["target_label"] for l in logs} >= {"Audited", "Audited D"}
    head = client_for(a["users"]["dent_head"])
    hl = head.get("/api/v1/center/audit").get_json()["items"]
    assert hl and all(l["department_id"] == dent for l in hl)
    assert client_for(a["users"]["dent_doc1"]).get("/api/v1/center/audit").status_code == 403
    assert client_for(a["users"]["rec_center"]).get("/api/v1/center/audit").status_code == 403
    # Center B does not see A's entries
    bl = client_for(world["B"]["users"]["manager"]).get("/api/v1/center/audit").get_json()["items"]
    assert all(l["health_center_id"] == world["B"]["center_id"] for l in bl)
    # Immutable at the database level
    from backend.app.extensions import db
    from backend.app.core import tenancy
    import pytest
    from sqlalchemy.exc import DBAPIError
    with app.app_context(), tenancy.scoped("platform"):
        with pytest.raises(DBAPIError):
            db.session.execute(text("UPDATE audit_logs SET action = 'edit' WHERE id = :i"), {"i": logs[0]["id"]})
        db.session.rollback()
        with pytest.raises(DBAPIError):
            db.session.execute(text("DELETE FROM audit_logs WHERE id = :i"), {"i": logs[0]["id"]})
        db.session.rollback()
