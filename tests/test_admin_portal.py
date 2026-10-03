"""Superadmin portal: centers lifecycle, plans/limits, modules, users, audit, branding, backups."""
import io
import uuid

import pytest
from sqlalchemy import select, text

from tests.conftest import PASSWORD, ApiClient

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _sa(world, client_for):
    return client_for(world["superadmin"])


def _new_center(sa, **extra):
    tag = uuid.uuid4().hex[:6]
    body = {"name": f"New Center {tag}", "plan_code": "basic", "modules": ["dentistry", "dermatology"],
            "manager": {"username": f"boss{tag}", "name": "Boss", "password": PASSWORD}}
    body.update(extra)
    r = sa.post("/api/v1/admin/centers", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_non_superadmin_forbidden(world, client_for):
    c = client_for(world["A"]["users"]["manager"])
    assert c.get("/api/v1/admin/centers").status_code == 403
    assert c.post("/api/v1/admin/centers", json={"name": "x"}).status_code == 403
    assert c.post(f"/api/v1/admin/users/{world['A']['users']['dent_doc1']['id']}/password",
                  json={"password": "Another-Pass-1"}).status_code == 403


def test_create_center_trial_with_manager(app, world, client_for):
    sa = _sa(world, client_for)
    out = _new_center(sa)
    assert out["status"] == "trial" and out["plan"]["code"] == "basic"
    assert out["modules"] == ["dentistry", "dermatology"]
    assert out["limits"]["max_doctors"] == 3
    # The new manager can log in and lands in the center portal.
    mgr = ApiClient(app)
    r = mgr.login(out["manager"]["email"])
    assert r.status_code == 200 and r.get_json()["portal"] == "center"
    # Audit entry for the manager creation is visible platform-wide.
    logs = sa.get(f"/api/v1/admin/audit?center_id={out['id']}&category=user").get_json()["items"]
    assert any(l["action"] == "create" and l["target_id"] == out["manager"]["id"] for l in logs)
    assert sa.get("/api/v1/admin/centers?q=" + out["slug"]).get_json()["total"] == 1


def test_status_changes_block_and_restore_access(app, world, client_for):
    sa = _sa(world, client_for)
    cid = world["B"]["center_id"]
    email = world["B"]["users"]["manager"]["email"]
    r = sa.post(f"/api/v1/admin/centers/{cid}/status", json={"action": "suspend"})
    assert r.status_code == 200 and r.get_json()["status"] == "suspended"
    assert ApiClient(app).login(email).status_code == 403
    r = sa.post(f"/api/v1/admin/centers/{cid}/status", json={"action": "activate"})
    assert r.status_code == 422
    r = sa.post(f"/api/v1/admin/centers/{cid}/status", json={"action": "activate", "subscription_ends_at": "2099-01-01"})
    assert r.get_json()["status"] == "active"
    assert ApiClient(app).login(email).status_code == 200
    sa.post(f"/api/v1/admin/centers/{cid}/status", json={"action": "expire"})
    assert ApiClient(app).login(email).status_code == 403
    r = sa.post(f"/api/v1/admin/centers/{cid}/status", json={"action": "extend_trial", "days": 7})
    assert r.get_json()["status"] == "trial"
    assert ApiClient(app).login(email).status_code == 200


def test_plan_limits_and_overrides(world, client_for):
    sa = _sa(world, client_for)
    out = _new_center(sa)
    cid = out["id"]
    plans = sa.get("/api/v1/admin/plans").get_json()["items"]
    pro = next(p for p in plans if p["code"] == "professional")
    r = sa.put(f"/api/v1/admin/centers/{cid}/plan", json={"plan_id": pro["id"]})
    assert r.get_json()["limits"]["max_doctors"] == 6
    r = sa.put(f"/api/v1/admin/centers/{cid}/limits", json={"max_doctors": None, "max_clinics": 10,
                                                           "storage_quota_bytes": 5 * 1024 ** 3})
    body = r.get_json()
    assert body["limits"]["max_doctors"] is None and body["limits"]["max_clinics"] == 10
    assert body["storage_quota_bytes"] == 5 * 1024 ** 3
    assert sa.put(f"/api/v1/admin/centers/{cid}/limits", json={"max_clinics": -1}).status_code == 422
    # plans CRUD
    r = sa.post("/api/v1/admin/plans", json={"code": f"custom{uuid.uuid4().hex[:4]}", "name": "Custom",
                                             "max_doctors": 20})
    assert r.status_code == 201
    pid = r.get_json()["id"]
    assert sa.patch(f"/api/v1/admin/plans/{pid}", json={"max_doctors": 25}).get_json()["max_doctors"] == 25
    assert sa.delete(f"/api/v1/admin/plans/{pro['id']}").status_code == 409  # in use
    assert sa.delete(f"/api/v1/admin/plans/{pid}").status_code == 200


def test_modules_and_custom_department_type(world, client_for):
    sa = _sa(world, client_for)
    r = sa.post("/api/v1/admin/department-types", json={"name_en": "Physiotherapy", "name_ar": "العلاج الفيزيائي"})
    assert r.status_code == 201
    t = r.get_json()
    assert t["environment"] == "generic" and t["is_custom"] and t["code"].startswith("custom_")
    out = _new_center(sa)
    r = sa.put(f"/api/v1/admin/centers/{out['id']}/modules", json={"modules": ["dentistry", t["code"]]})
    assert sorted(r.get_json()["modules"]) == sorted(["dentistry", t["code"]])
    assert sa.put(f"/api/v1/admin/centers/{out['id']}/modules", json={"modules": ["nope"]}).status_code == 422
    r = sa.patch(f"/api/v1/admin/department-types/{t['id']}", json={"name_en": "Physio", "is_active": False})
    assert r.get_json()["name_en"] == "Physio" and r.get_json()["is_active"] is False


def test_user_management_and_password_reset(app, world, client_for):
    sa = _sa(world, client_for)
    doc = world["A"]["users"]["gen_doc"]
    victim = client_for(doc)
    r = sa.post(f"/api/v1/admin/users/{doc['id']}/password", json={"password": "Brand-New-Pass-9"})
    assert r.status_code == 200
    assert victim.get("/api/v1/auth/me").status_code == 401  # sessions revoked
    assert ApiClient(app).login(doc["email"], "Brand-New-Pass-9").status_code == 200
    r = sa.post(f"/api/v1/admin/users/{doc['id']}/archive")
    assert r.get_json()["status"] == "archived"
    assert ApiClient(app).login(doc["email"], "Brand-New-Pass-9").status_code == 401
    assert sa.post(f"/api/v1/admin/users/{doc['id']}/reactivate").get_json()["status"] == "active"
    users = sa.get(f"/api/v1/admin/users?center_id={world['A']['center_id']}&role=doctor").get_json()
    assert users["total"] == 8
    # additional superadmin
    tag = uuid.uuid4().hex[:6]
    r = sa.post("/api/v1/admin/superadmins", json={"username": f"ops{tag}", "name": "Ops", "password": PASSWORD})
    assert r.status_code == 201 and r.get_json()["role"] == "superadmin"
    assert ApiClient(app).login(r.get_json()["email"]).get_json()["portal"] == "superadmin"
    # cannot archive yourself
    assert sa.post(f"/api/v1/admin/users/{world['superadmin']['id']}/archive").status_code == 403


def test_branding_public_and_logo(app, world, client_for):
    sa = _sa(world, client_for)
    r = sa.put("/api/v1/admin/settings", json={"platform_name": "Shifa Cloud", "primary_color": "#112233"})
    assert r.status_code == 200
    pub = ApiClient(app).c.get("/api/v1/platform/branding").get_json()
    assert pub["platform_name"] == "Shifa Cloud" and pub["primary_color"] == "#112233"
    r = sa.post("/api/v1/admin/settings/logo", data={"file": (io.BytesIO(PNG), "logo.png")},
                content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["logo_url"]
    r = ApiClient(app).c.get("/api/v1/platform/branding/logo")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data == PNG
    bad = sa.post("/api/v1/admin/settings/logo", data={"file": (io.BytesIO(b"<svg></svg>"), "x.svg")},
                  content_type="multipart/form-data")
    assert bad.status_code == 422
    assert sa.put("/api/v1/admin/settings", json={"primary_color": "red"}).status_code == 422


def test_dashboard_storage_and_meta(world, client_for):
    sa = _sa(world, client_for)
    d = sa.get("/api/v1/admin/dashboard").get_json()
    assert d["centers_total"] >= 2 and "trial" in d["centers_by_status"]
    s = sa.get("/api/v1/admin/storage").get_json()
    assert any(i["id"] == world["A"]["center_id"] for i in s["items"])
    m = sa.get("/api/v1/admin/meta").get_json()
    assert "plans" in m and "department_types" in m


def test_permanent_delete_requires_slug_and_keeps_audit(app, world, client_for):
    sa = _sa(world, client_for)
    out = _new_center(sa, modules=["dentistry"])
    cid = out["id"]
    # produce a login audit entry inside that center
    assert ApiClient(app).login(out["manager"]["email"]).status_code == 200
    assert sa.delete(f"/api/v1/admin/centers/{cid}", json={"confirm": "wrong"}).status_code == 422
    r = sa.delete(f"/api/v1/admin/centers/{cid}", json={"confirm": out["slug"]})
    assert r.status_code == 200, r.get_json()
    assert sa.get(f"/api/v1/admin/centers/{cid}").status_code == 404
    assert ApiClient(app).login(out["manager"]["email"]).status_code == 401
    # Audit entries survive, detached from the deleted center.
    logs = sa.get("/api/v1/admin/audit?platform_only=1&category=user").get_json()["items"]
    assert any(l["target_id"] == out["manager"]["id"] for l in logs)


def test_full_backup_pg_dump(app, world, client_for):
    from backend.app.services.backup import BackupError, find_pg_dump
    try:
        find_pg_dump()
    except BackupError:
        pytest.skip("pg_dump not installed")
    sa = _sa(world, client_for)
    r = sa.post("/api/v1/admin/backups")
    assert r.status_code == 201, r.get_json()
    item = r.get_json()
    assert item["complete"] and {f["name"] for f in item["files"]} == {"database.dump", "files.zip", "manifest.json"}
    assert any(b["name"] == item["name"] for b in sa.get("/api/v1/admin/backups").get_json()["items"])
    r = sa.get(f"/api/v1/admin/backups/{item['name']}/database.dump")
    assert r.status_code == 200 and r.data[:5] == b"PGDMP"
    assert sa.get(f"/api/v1/admin/backups/..%2F..%2Fetc/database.dump").status_code == 404
    assert sa.get(f"/api/v1/admin/backups/{item['name']}/secret.txt").status_code == 404


def test_seed_demo_center(app):
    from backend.app.services.demo import seed_demo_center
    with app.app_context():
        lines = seed_demo_center(PASSWORD, name=f"Demo {uuid.uuid4().hex[:6]}")
    emails = [l.split()[-1] for l in lines if "@" in l]
    roles = {l.split()[0] for l in lines if "@" in l}
    assert roles == {"center_manager", "department_manager", "doctor", "receptionist"}
    c = ApiClient(app)
    me = c.login(emails[0]).get_json()
    assert me["portal"] == "center" and len(me["departments"]) == 11
