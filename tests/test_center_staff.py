"""Staff management, username/email rules, scope, plan limits, permissions, center export."""
import io
import json
import uuid
import zipfile

from tests.conftest import PASSWORD, ApiClient
from tests.test_center_org import _basic_center


def _tag():
    return uuid.uuid4().hex[:6]


def _doctor(client, clinic_id, username=None, **extra):
    body = {"role": "doctor", "username": username or f"doc{_tag()}", "name": "Dr. Test", "password": PASSWORD,
            "clinic_id": clinic_id}
    body.update(extra)
    return client.post("/api/v1/center/staff", json=body)


def test_create_doctor_generated_email_and_login(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    r = _doctor(m, a["clinics"]["dent2"], username="Dr.Ahmad" + _tag())
    assert r.status_code == 201, r.get_json()
    d = r.get_json()
    assert d["email"] == f"{d['username'].lower()}_{d['id']}@aerodent.com" and d["email_is_generated"]
    assert d["department_id"] == a["departments"]["dentistry"]
    c = ApiClient(app)
    assert c.login(d["email"]).get_json()["principal"]["clinic_ids"] == [a["clinics"]["dent2"]]
    # validation: doctor without clinic, bad username, short password
    assert m.post("/api/v1/center/staff", json={"role": "doctor", "username": f"x{_tag()}", "name": "X",
                                                "password": PASSWORD}).status_code == 422
    assert _doctor(m, a["clinics"]["dent1"], username="has space").status_code == 422
    assert _doctor(m, a["clinics"]["dent1"], password="short").status_code == 422
    # audit entry with the department of the doctor
    logs = m.get("/api/v1/center/audit?category=user&action=create").get_json()["items"]
    assert any(l["target_id"] == d["id"] and l["department_id"] == a["departments"]["dentistry"] for l in logs)


def test_username_and_email_rules(world, client_for):
    a, b = world["A"], world["B"]
    ma, mb = client_for(a["users"]["manager"]), client_for(b["users"]["manager"])
    uname = f"samir{_tag()}"
    assert _doctor(ma, a["clinics"]["dent1"], username=uname).status_code == 201
    # same username in another center: allowed
    assert _doctor(mb, b["clinics"]["dent1"], username=uname).status_code == 201
    # same username (case-insensitive) in the same center: conflict
    r = _doctor(ma, a["clinics"]["dent2"], username=uname.upper())
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "username_taken"
    # custom email is globally unique
    email = f"{_tag()}@example.com"
    assert _doctor(ma, a["clinics"]["dent1"], email=email).status_code == 201
    r = _doctor(mb, b["clinics"]["dent1"], email=email.upper())
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "email_taken"


def test_rename_regenerates_generated_email_only(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    d = _doctor(m, a["clinics"]["dent1"]).get_json()
    new = f"omar{_tag()}"
    r = m.patch(f"/api/v1/center/staff/{d['id']}", json={"username": new, "name": "Dr. Omar", "version": d["version"]})
    assert r.status_code == 200
    u = r.get_json()
    assert u["email"] == f"{new}_{d['id']}@aerodent.com" and u["name"] == "Dr. Omar"
    assert ApiClient(app).login(u["email"]).status_code == 200
    u = m.get(f"/api/v1/center/staff/{d['id']}").get_json()  # login touched the row (version bump)
    # custom email survives a rename
    custom = f"omar.{_tag()}@clinic.example"
    u = m.patch(f"/api/v1/center/staff/{d['id']}", json={"email": custom, "version": u["version"]}).get_json()
    assert u["email"] == custom and not u["email_is_generated"]
    u = m.patch(f"/api/v1/center/staff/{d['id']}", json={"username": f"o{_tag()}", "version": u["version"]}).get_json()
    assert u["email"] == custom
    u2 = m.patch(f"/api/v1/center/staff/{d['id']}", json={"reset_email": True, "version": u["version"]}).get_json()
    assert u2["email"] == f"{u['username'].lower()}_{d['id']}@aerodent.com"
    # stale version
    assert m.patch(f"/api/v1/center/staff/{d['id']}", json={"name": "x", "version": u["version"]}).status_code == 409


def test_department_manager_scope(world, client_for):
    a = world["A"]
    head = client_for(a["users"]["dent_head"])
    assert _doctor(head, a["clinics"]["dent2"]).status_code == 201
    assert _doctor(head, a["clinics"]["derm1"]).status_code == 422  # clinic outside own department
    r = head.post("/api/v1/center/staff", json={"role": "department_manager", "username": f"x{_tag()}", "name": "X",
                                                "password": PASSWORD, "department_id": a["departments"]["dentistry"]})
    assert r.status_code == 403
    r = head.post("/api/v1/center/staff", json={"role": "receptionist", "username": f"r{_tag()}", "name": "R",
                                                "password": PASSWORD, "scopes": [{"type": "center"}]})
    assert r.status_code == 422
    r = head.post("/api/v1/center/staff", json={"role": "receptionist", "username": f"r{_tag()}", "name": "R",
                                                "password": PASSWORD,
                                                "scopes": [{"type": "clinic", "id": a["clinics"]["dent1"]}]})
    assert r.status_code == 201 and r.get_json()["scopes"][0]["type"] == "clinic"
    listed = {u["id"] for u in head.get("/api/v1/center/staff?per_page=100").get_json()["items"]}
    assert a["users"]["dent_doc1"]["id"] in listed and a["users"]["rec_multi"]["id"] in listed
    assert a["users"]["derm_doc"]["id"] not in listed and a["users"]["manager"]["id"] not in listed
    assert head.get(f"/api/v1/center/staff/{a['users']['derm_doc']['id']}").status_code == 404
    # receptionist spanning another department: visible but not manageable
    rm = head.get(f"/api/v1/center/staff/{a['users']['rec_multi']['id']}").get_json()
    assert rm["can_manage"] is False
    assert head.post(f"/api/v1/center/staff/{rm['id']}/archive").status_code == 403
    rd = head.get(f"/api/v1/center/staff/{a['users']['rec_dent']['id']}").get_json()
    assert head.patch(f"/api/v1/center/staff/{rd['id']}",
                      json={"phone": "+963 11 222", "version": rd["version"]}).status_code == 200
    # department managers cannot reset passwords (spec §7)
    assert head.post(f"/api/v1/center/staff/{a['users']['dent_doc1']['id']}/password",
                     json={"password": "Another-Pass-1"}).status_code == 403
    # doctors only view staff, cannot create
    doc = client_for(a["users"]["dent_doc1"])
    assert doc.get("/api/v1/center/staff").status_code == 200
    assert _doctor(doc, a["clinics"]["dent1"]).status_code == 403
    assert client_for(a["users"]["rec_dent"]).get("/api/v1/center/staff").status_code == 403


def test_cross_tenant_staff_404(world, client_for):
    a, b = world["A"], world["B"]
    mb = client_for(b["users"]["manager"])
    target = a["users"]["dent_doc1"]["id"]
    assert mb.get(f"/api/v1/center/staff/{target}").status_code == 404
    assert mb.patch(f"/api/v1/center/staff/{target}", json={"name": "x", "version": 1}).status_code == 404
    assert mb.post(f"/api/v1/center/staff/{target}/password", json={"password": "Another-Pass-1"}).status_code == 404
    assert mb.delete(f"/api/v1/center/staff/{target}").status_code == 404
    assert mb.get(f"/api/v1/center/staff/{target}/permissions").status_code == 404
    # cannot assign another center's clinic
    assert _doctor(mb, a["clinics"]["dent1"]).status_code == 422
    ids = {u["id"] for u in mb.get("/api/v1/center/staff?per_page=100").get_json()["items"]}
    assert target not in ids


def test_archive_blocks_login_and_password_reset(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    doc = a["users"]["oph_doc"]
    session = client_for(doc)
    r = m.post(f"/api/v1/center/staff/{doc['id']}/password", json={"password": "Reset-Pass-123"})
    assert r.status_code == 200
    assert session.get("/api/v1/auth/me").status_code == 401
    assert ApiClient(app).login(doc["email"], "Reset-Pass-123").status_code == 200
    assert m.post(f"/api/v1/center/staff/{a['users']['manager']['id']}/password",
                  json={"password": "Reset-Pass-123"}).status_code in (403, 404)
    r = m.post(f"/api/v1/center/staff/{doc['id']}/archive")
    assert r.get_json()["status"] == "archived"
    assert ApiClient(app).login(doc["email"], "Reset-Pass-123").status_code == 401
    assert m.post(f"/api/v1/center/staff/{doc['id']}/reactivate").get_json()["status"] == "active"
    assert ApiClient(app).login(doc["email"], "Reset-Pass-123").status_code == 200


def test_doctor_reassignment_switches_access(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    doc = a["users"]["dent_doc1"]
    old = client_for(doc)
    assert old.get("/api/v1/auth/me").get_json()["principal"]["clinic_ids"] == [a["clinics"]["dent1"]]
    r = m.post(f"/api/v1/center/staff/{doc['id']}/reassign", json={"clinic_id": a["clinics"]["derm1"]})
    assert r.status_code == 200 and r.get_json()["clinic_id"] == a["clinics"]["derm1"]
    assert old.get("/api/v1/auth/me").status_code == 401
    me = client_for(doc).get("/api/v1/auth/me").get_json()
    assert me["principal"]["clinic_ids"] == [a["clinics"]["derm1"]]
    assert [d["environment"] for d in me["departments"]] == ["dermatology"]
    # department manager may not move a doctor out of their department
    head = client_for(a["users"]["dent_head"])
    r = head.post(f"/api/v1/center/staff/{a['users']['dent_doc2']['id']}/reassign",
                  json={"clinic_id": a["clinics"]["gen1"]})
    assert r.status_code == 422
    assert head.post(f"/api/v1/center/staff/{a['users']['dent_doc2']['id']}/reassign",
                     json={"clinic_id": a["clinics"]["dent1"]}).status_code == 200


def test_receptionist_scope_change(world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    rec = a["users"]["rec_dent1"]
    r = m.put(f"/api/v1/center/staff/{rec['id']}/scopes",
              json={"scopes": [{"type": "department", "id": a["departments"]["dermatology"]},
                               {"type": "clinic", "id": a["clinics"]["gen1"]}]})
    assert r.status_code == 200
    assert {(s["type"], s["id"]) for s in r.get_json()["scopes"]} == {
        ("department", a["departments"]["dermatology"]), ("clinic", a["clinics"]["gen1"])}
    me = client_for(rec).get("/api/v1/auth/me").get_json()
    assert set(me["principal"]["clinic_ids"]) == {a["clinics"]["derm1"], a["clinics"]["gen1"]}
    assert m.put(f"/api/v1/center/staff/{rec['id']}/scopes", json={"scopes": []}).status_code == 422


def test_plan_limits_on_create_and_reactivate(app, world, client_for):
    m, info = _basic_center(app, client_for, world, modules=("general_medicine",))
    types = m.get("/api/v1/center/departments/meta").get_json()["types"]
    dept = m.post("/api/v1/center/departments", json={"department_type_id": types[0]["id"]}).get_json()
    clinic = m.post("/api/v1/center/clinics", json={"department_id": dept["id"], "name": "C1"}).get_json()
    docs = [_doctor(m, clinic["id"]).get_json() for _ in range(3)]
    r = _doctor(m, clinic["id"])
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "plan_limit_reached"
    assert m.post(f"/api/v1/center/staff/{docs[0]['id']}/archive").status_code == 200
    assert _doctor(m, clinic["id"]).status_code == 201  # slot freed by archiving
    r = m.post(f"/api/v1/center/staff/{docs[0]['id']}/reactivate")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "plan_limit_reached"
    # 1 receptionist max
    body = {"role": "receptionist", "name": "R", "password": PASSWORD, "scopes": [{"type": "center"}]}
    assert m.post("/api/v1/center/staff", json={**body, "username": f"r{_tag()}"}).status_code == 201
    assert m.post("/api/v1/center/staff", json={**body, "username": f"r{_tag()}"}).status_code == 422


def test_delete_unreferenced_vs_referenced(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    fresh = _doctor(m, a["clinics"]["gen1"]).get_json()
    r = m.delete(f"/api/v1/center/staff/{fresh['id']}")
    assert r.status_code == 200 and r.get_json()["deleted"] is True
    assert m.get(f"/api/v1/center/staff/{fresh['id']}").status_code == 404
    # A doctor who authored a visit is archived instead.
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import Patient, User, Visit
    from backend.app.core.timeutil import utcnow
    doc_id = a["users"]["gen_doc"]["id"]
    with app.app_context(), tenancy.scoped("platform"):
        pt = Patient(health_center_id=a["center_id"], code=900000 + doc_id % 1000, full_name="P", search_name="p")
        db.session.add(pt)
        db.session.flush()
        v = Visit(health_center_id=a["center_id"], patient_id=pt.id, department_id=a["departments"]["general_medicine"],
                  clinic_id=a["clinics"]["gen1"], visit_at=utcnow())
        v.set_author(db.session.get(User, doc_id))
        db.session.add(v)
        db.session.commit()
    r = m.delete(f"/api/v1/center/staff/{doc_id}")
    assert r.status_code == 200 and r.get_json()["archived"] is True and r.get_json()["deleted"] is False
    assert m.get(f"/api/v1/center/staff/{doc_id}").get_json()["status"] == "archived"


def test_permissions_role_and_user_overrides(app, world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    cat = m.get("/api/v1/center/permissions").get_json()
    assert "medical_records.edit" in {p["code"] for p in cat["permissions"]}
    rec = a["users"]["rec_dent"]
    r = m.put(f"/api/v1/center/staff/{rec['id']}/permissions", json={"changes": {"medical_records.edit": True}})
    assert r.status_code == 200 and "medical_records.edit" in r.get_json()["effective"]
    rc = client_for(rec)
    assert "medical_records.edit" in rc.get("/api/v1/auth/me").get_json()["principal"]["permissions"]
    notes = rc.get("/api/v1/notifications").get_json()["items"]
    assert any(n["type"] == "permission_changed" for n in notes)
    # structurally forbidden permission
    r = m.put(f"/api/v1/center/staff/{rec['id']}/permissions", json={"changes": {"audit.view": True}})
    assert r.status_code == 422
    assert m.put(f"/api/v1/center/staff/{rec['id']}/permissions", json={"changes": {"nope.x": True}}).status_code == 422
    # revoke override
    r = m.put(f"/api/v1/center/staff/{rec['id']}/permissions", json={"changes": {"medical_records.edit": None}})
    assert "medical_records.edit" not in r.get_json()["effective"]
    # role override for doctors in this center: remove billing.edit
    r = m.put("/api/v1/center/permissions/roles/doctor", json={"changes": {"billing.edit": False}})
    assert r.status_code == 200 and "billing.edit" not in r.get_json()["effective"]
    me = client_for(a["users"]["gen_doc"]).get("/api/v1/auth/me").get_json()
    assert "billing.edit" not in me["principal"]["permissions"]
    # not in center B
    meb = client_for(world["B"]["users"]["gen_doc"]).get("/api/v1/auth/me").get_json()
    assert "billing.edit" in meb["principal"]["permissions"]
    assert m.put("/api/v1/center/permissions/roles/center_manager",
                 json={"changes": {"billing.edit": False}}).status_code == 422
    # department manager: own department users only, no role overrides
    head = client_for(a["users"]["dent_head"])
    assert head.put(f"/api/v1/center/staff/{a['users']['dent_doc2']['id']}/permissions",
                    json={"changes": {"billing.delete": True}}).status_code == 200
    assert head.put(f"/api/v1/center/staff/{a['users']['derm_doc']['id']}/permissions",
                    json={"changes": {"billing.delete": True}}).status_code == 404
    assert head.put("/api/v1/center/permissions/roles/doctor",
                    json={"changes": {"billing.edit": True}}).status_code == 403
    # doctors cannot manage permissions
    assert client_for(a["users"]["dent_doc1"]).get("/api/v1/center/permissions").status_code == 403


def test_center_export_zip(world, client_for):
    a = world["A"]
    m = client_for(a["users"]["manager"])
    r = m.get("/api/v1/center/backup/export")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["center"]["id"] == a["center_id"]
    users = json.loads(z.read("tables/users.json"))
    assert users and all(u["health_center_id"] == a["center_id"] for u in users)
    assert all("password_hash" not in u for u in users)
    clinics = json.loads(z.read("tables/clinics.json"))
    assert {c["id"] for c in clinics} >= set(a["clinics"].values())
    assert "tables/user_sessions.json" not in z.namelist()
    r.close()
    assert client_for(a["users"]["dent_head"]).get("/api/v1/center/backup/export").status_code == 403


def test_support_mode_superadmin_can_manage_staff(world, client_for):
    sa = client_for(world["superadmin"])
    assert sa.get("/api/v1/center/staff").status_code == 403  # no center context yet
    assert sa.post("/api/v1/auth/support/enter", json={"center_id": world["A"]["center_id"]}).status_code == 200
    items = sa.get("/api/v1/center/staff?role=doctor&per_page=100").get_json()["items"]
    assert len(items) == 8
    assert _doctor(sa, world["A"]["clinics"]["gen1"]).status_code == 201
