"""Dentistry module: odontogram, treatments, treatment plans, timeline, scope and permissions."""
import itertools
from datetime import timedelta

import pytest

from backend.app.core import tenancy
from backend.app.extensions import db

BASE = "/api/v1/dentistry"
_codes = itertools.count(900000)


def make_patient(app, center, name="Ali Dental", clinics=("dent1",)):
    from backend.app.models import Patient
    from backend.app.services.clinical import link_patient_to_clinic
    with app.app_context(), tenancy.scoped("tenant", center["center_id"]):
        p = Patient(health_center_id=center["center_id"], code=next(_codes), full_name=name,
                    search_name=name.lower())
        db.session.add(p)
        db.session.flush()
        for k in clinics:
            link_patient_to_clinic(center["center_id"], p.id, center["clinics"][k])
        db.session.commit()
        return p.id


def grant(app, center, user_key, perm, allowed=True):
    from backend.app.models import UserPermission
    with app.app_context(), tenancy.scoped("tenant", center["center_id"]):
        db.session.add(UserPermission(health_center_id=center["center_id"], user_id=center["users"][user_key]["id"],
                                      permission=perm, allowed=allowed))
        db.session.commit()


def expire_and_purge(app):
    from backend.app.core.timeutil import utcnow
    from backend.app.models import DeletionStage
    from backend.app.services import deletion
    with app.app_context():
        with tenancy.scoped("platform"):
            for st in db.session.query(DeletionStage).all():
                st.expires_at = utcnow() - timedelta(seconds=1)
            db.session.commit()
        n = deletion.purge_expired()
        db.session.remove()
        return n


@pytest.fixture()
def dent(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a)
    pid2 = make_patient(app, a, "Sara Dental", clinics=("dent2",))
    return {"A": a, "B": world["B"], "pid": pid, "pid2": pid2, "c": client_for}


def _treat(c, pid, **kw):
    body = {"patient_id": pid, "procedure": "filling", "tooth_number": 14, "fee": "25.50"} | kw
    return c.post(f"{BASE}/treatments", json=body)


# ---------------------------------------------------------------------------- meta
def test_meta_numbering_and_clinics(dent):
    a = dent["A"]
    m = dent["c"](a["users"]["dent_doc1"]).get(f"{BASE}/meta").get_json()
    assert [c["id"] for c in m["clinics"]] == [a["clinics"]["dent1"]]
    assert m["numbering"]["scheme"] == "universal"
    assert m["numbering"]["permanent"]["fdi"]["1"] == 18 and m["numbering"]["permanent"]["fdi"]["32"] == 48
    assert m["numbering"]["primary"]["labels"]["1"] == "A" and m["numbering"]["primary"]["fdi"]["20"] == 85
    assert "rct" in m["conditions"] and "clear" in m["chart_actions"]
    assert "in-progress" in m["statuses"] and "panoramic" in m["xray_types"]
    head = dent["c"](a["users"]["dent_head"]).get(f"{BASE}/meta").get_json()
    assert sorted(c["id"] for c in head["clinics"]) == sorted([a["clinics"]["dent1"], a["clinics"]["dent2"]])
    assert dent["c"](a["users"]["derm_doc"]).get(f"{BASE}/meta").get_json()["clinics"] == []


# ---------------------------------------------------------------------------- odontogram
def test_odontogram_update_history_and_versions(dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    url = f"{BASE}/patients/{pid}/odontogram/permanent/3"
    r = c.put(url, json={"condition": "decay", "notes": "deep", "surfaces": ["O", "M", "O"]})
    assert r.status_code == 201, r.get_json()
    t = r.get_json()
    assert t["version"] == 1 and t["surfaces"] == ["M", "O"] and t["clinic_id"] == a["clinics"]["dent1"]
    # existing row: version required, stale version -> 409
    assert c.put(url, json={"condition": "filling"}).status_code == 422
    r = c.put(url, json={"condition": "filling", "procedure": "Composite filling", "version": 1})
    assert r.status_code == 200 and r.get_json()["version"] == 2 and r.get_json()["notes"] == "deep"
    r = c.put(url, json={"condition": "crown", "version": 1})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    r = c.put(url, json={"condition": "clear", "version": 2})
    assert r.status_code == 200 and r.get_json()["condition"] is None and r.get_json()["notes"] is None
    # history preserved (newest first)
    h = c.get(f"{BASE}/patients/{pid}/odontogram/history?tooth_number=3").get_json()["items"]
    assert [(e["action"], e["condition"]) for e in h] == [("clear", None), ("set", "filling"), ("set", "decay")]
    assert h[-1]["notes"] == "deep" and h[0]["author_name"]
    # validation
    assert c.put(f"{BASE}/patients/{pid}/odontogram/primary/21", json={"condition": "decay"}).status_code == 422
    assert c.put(f"{BASE}/patients/{pid}/odontogram/adult/2", json={"condition": "decay"}).status_code == 422
    assert c.put(f"{BASE}/patients/{pid}/odontogram/primary/5", json={"condition": "melted"}).status_code == 422
    r = c.put(f"{BASE}/patients/{pid}/odontogram/primary/5", json={"condition": "decay"})
    assert r.status_code == 201 and r.get_json()["label"] == "E"
    chart = c.get(f"{BASE}/patients/{pid}/odontogram").get_json()
    assert {(t["tooth_mode"], t["tooth_number"]) for t in chart["teeth"]} == {("permanent", 3), ("primary", 5)}
    assert [t["tooth_number"] for t in c.get(f"{BASE}/patients/{pid}/odontogram?mode=primary").get_json()["teeth"]] \
        == [5]


def test_odontogram_bulk_is_atomic(dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    url = f"{BASE}/patients/{pid}/odontogram/bulk"
    r = c.post(url, json={"teeth": [{"tooth_mode": "permanent", "tooth_number": 1, "condition": "implant"},
                                    {"tooth_mode": "permanent", "tooth_number": 2, "condition": "rct"}]})
    assert r.status_code == 200, r.get_json()
    assert [t["version"] for t in r.get_json()["teeth"]] == [1, 1]
    # second item has a stale version -> nothing saved
    r = c.post(url, json={"teeth": [{"tooth_mode": "permanent", "tooth_number": 4, "condition": "decay"},
                                    {"tooth_mode": "permanent", "tooth_number": 1, "condition": "crown",
                                     "version": 7}]})
    assert r.status_code == 409
    teeth = c.get(f"{BASE}/patients/{pid}/odontogram").get_json()["teeth"]
    assert sorted(t["tooth_number"] for t in teeth) == [1, 2]
    dup = [{"tooth_mode": "permanent", "tooth_number": 9, "condition": "decay"}] * 2
    assert c.post(url, json={"teeth": dup}).status_code == 422
    assert c.post(url, json={"teeth": []}).status_code == 422


# ---------------------------------------------------------------------------- scope
def test_clinic_isolation(dent):
    a, pid = dent["A"], dent["pid"]
    doc1, doc2 = dent["c"](a["users"]["dent_doc1"]), dent["c"](a["users"]["dent_doc2"])
    tid = _treat(doc1, pid).get_json()["id"]
    doc1.put(f"{BASE}/patients/{pid}/odontogram/permanent/8", json={"condition": "decay"})
    assert doc2.get(f"{BASE}/treatments/{tid}").status_code == 404
    assert doc2.patch(f"{BASE}/treatments/{tid}", json={"status": "completed", "version": 1}).status_code == 404
    assert doc2.delete(f"{BASE}/treatments/{tid}").status_code == 404
    assert tid not in [t["id"] for t in doc2.get(f"{BASE}/treatments").get_json()["items"]]
    assert doc2.get(f"{BASE}/treatments?clinic_id={a['clinics']['dent1']}").status_code == 404
    assert doc2.get(f"{BASE}/patients/{pid}/odontogram?clinic_id={a['clinics']['dent1']}").status_code == 404
    assert doc2.put(f"{BASE}/patients/{pid}/odontogram/permanent/8",
                    json={"clinic_id": a["clinics"]["dent1"], "condition": "crown", "version": 1}).status_code == 404
    # doc2 cannot see dent1's patient at all (not linked to dent2)
    assert doc2.get(f"{BASE}/patients/{pid}/timeline").status_code == 404


def test_department_isolation(dent):
    a, pid = dent["A"], dent["pid"]
    tid = _treat(dent["c"](a["users"]["dent_doc1"]), pid).get_json()["id"]
    derm = dent["c"](a["users"]["derm_doc"])
    assert derm.get(f"{BASE}/treatments/{tid}").status_code == 404
    assert derm.get(f"{BASE}/treatments").get_json()["items"] == []
    assert derm.get(f"{BASE}/patients/{pid}/odontogram?clinic_id={a['clinics']['dent1']}").status_code == 404
    assert _treat(derm, pid, clinic_id=a["clinics"]["dent1"]).status_code == 404
    # own (non-dental) clinic: not a dental clinic
    r = derm.get(f"{BASE}/patients/{pid}/odontogram?clinic_id={a['clinics']['derm1']}")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "wrong_environment"
    # center manager: dental endpoints refuse non-dental clinics too
    mgr = dent["c"](a["users"]["manager"])
    assert _treat(mgr, pid, clinic_id=a["clinics"]["gen1"]).status_code == 422


def test_department_head_sees_both_clinics(dent):
    a = dent["A"]
    t1 = _treat(dent["c"](a["users"]["dent_doc1"]), dent["pid"]).get_json()["id"]
    t2 = _treat(dent["c"](a["users"]["dent_doc2"]), dent["pid2"]).get_json()["id"]
    head = dent["c"](a["users"]["dent_head"])
    ids = {t["id"] for t in head.get(f"{BASE}/treatments").get_json()["items"]}
    assert {t1, t2} <= ids
    assert head.get(f"{BASE}/treatments/{t2}").status_code == 200
    # head with two clinics must choose one when charting
    r = head.put(f"{BASE}/patients/{dent['pid2']}/odontogram/permanent/1", json={"condition": "decay"})
    assert r.status_code == 422
    r = head.put(f"{BASE}/patients/{dent['pid2']}/odontogram/permanent/1",
                 json={"condition": "decay", "clinic_id": a["clinics"]["dent2"]})
    assert r.status_code == 201
    # the head's own name is a valid doctor in both clinics
    r = head.patch(f"{BASE}/treatments/{t2}", json={"doctor_user_id": a["users"]["dent_head"]["id"], "version": 1})
    assert r.status_code == 200 and r.get_json()["doctor_name"].startswith("dent_head")


def test_receptionist_read_only_unless_granted(app, dent):
    a, pid = dent["A"], dent["pid"]
    tid = _treat(dent["c"](a["users"]["dent_doc1"]), pid).get_json()["id"]
    rec = dent["c"](a["users"]["rec_dent1"])
    assert rec.get(f"{BASE}/patients/{pid}/odontogram").status_code == 200
    assert rec.get(f"{BASE}/treatments/{tid}").status_code == 200
    assert rec.put(f"{BASE}/patients/{pid}/odontogram/permanent/2", json={"condition": "decay"}).status_code == 403
    assert rec.patch(f"{BASE}/treatments/{tid}", json={"status": "completed", "version": 1}).status_code == 403
    assert _treat(rec, pid).status_code == 403
    assert rec.delete(f"{BASE}/treatments/{tid}").status_code == 403
    grant(app, a, "rec_dent1", "medical_records.edit")
    assert rec.put(f"{BASE}/patients/{pid}/odontogram/permanent/2", json={"condition": "decay"}).status_code == 201
    r = rec.patch(f"{BASE}/treatments/{tid}", json={"status": "completed", "version": 1})
    assert r.status_code == 200 and r.get_json()["status"] == "completed"
    assert _treat(rec, pid).status_code == 403  # create not granted
    # out-of-scope receptionist (dentistry clinic 1 only) still gets 404 for clinic 2
    tid2 = _treat(dent["c"](a["users"]["dent_doc2"]), dent["pid2"]).get_json()["id"]
    assert rec.get(f"{BASE}/treatments/{tid2}").status_code == 404


def test_cross_tenant_404(dent):
    a, b, pid = dent["A"], dent["B"], dent["pid"]
    tid = _treat(dent["c"](a["users"]["dent_doc1"]), pid).get_json()["id"]
    mb = dent["c"](b["users"]["manager"])
    assert mb.get(f"{BASE}/treatments/{tid}").status_code == 404
    assert mb.patch(f"{BASE}/treatments/{tid}", json={"version": 1, "status": "completed"}).status_code == 404
    assert mb.delete(f"{BASE}/treatments/{tid}").status_code == 404
    assert mb.get(f"{BASE}/patients/{pid}/odontogram?clinic_id={a['clinics']['dent1']}").status_code == 404
    assert mb.get(f"{BASE}/patients/{pid}/odontogram?clinic_id={b['clinics']['dent1']}").status_code == 404
    assert mb.put(f"{BASE}/patients/{pid}/odontogram/permanent/2",
                  json={"clinic_id": b["clinics"]["dent1"], "condition": "decay"}).status_code == 404
    assert _treat(mb, pid, clinic_id=b["clinics"]["dent1"]).status_code == 404
    assert tid not in [t["id"] for t in mb.get(f"{BASE}/treatments").get_json()["items"]]


# ---------------------------------------------------------------------------- treatments
def test_treatment_crud_validation_and_visit(dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    for bad in ({"tooth_number": 40}, {"fee": "-1"}, {"status": "done"}, {"procedure": None, "description": None},
                {"doctor_user_id": a["users"]["derm_doc"]["id"]}, {"tooth_mode": "primary", "tooth_number": 25}):
        r = _treat(c, pid, **bad)
        assert r.status_code == 422, (bad, r.get_json())
    r = _treat(c, pid, create_visit=True, status="in-progress")
    assert r.status_code == 201, r.get_json()
    t = r.get_json()
    assert t["visit_id"] and t["fee"] == "25.50" and t["status"] == "in-progress"
    assert t["doctor_user_id"] == a["users"]["dent_doc1"]["id"] and t["author_name"]
    # existing visit of another clinic is rejected (manager can see it but it does not match)
    mgr = dent["c"](a["users"]["manager"])
    other = _treat(dent["c"](a["users"]["dent_doc2"]), dent["pid2"], create_visit=True).get_json()
    r = _treat(mgr, pid, clinic_id=a["clinics"]["dent1"], visit_id=other["visit_id"])
    assert r.status_code == 422
    assert _treat(c, pid, visit_id=other["visit_id"]).status_code == 404  # not visible to doc1
    r = _treat(c, pid, visit_id=t["visit_id"])
    assert r.status_code == 201 and r.get_json()["visit_id"] == t["visit_id"]
    # update + version conflict
    r = c.patch(f"{BASE}/treatments/{t['id']}", json={"status": "completed", "fee": "30", "version": 1})
    assert r.status_code == 200 and r.get_json()["version"] == 2 and r.get_json()["fee"] == "30.00"
    r = c.patch(f"{BASE}/treatments/{t['id']}", json={"status": "cancelled", "version": 1})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    assert c.patch(f"{BASE}/treatments/{t['id']}", json={"status": "cancelled"}).status_code == 422
    # list filters
    items = c.get(f"{BASE}/treatments?patient_id={pid}&status=completed").get_json()["items"]
    assert [i["id"] for i in items] == [t["id"]]
    assert c.get(f"{BASE}/treatments?status=bogus").status_code == 422


def test_treatment_delete_undo_and_purge(app, dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    tid = _treat(c, pid).get_json()["id"]
    r = c.delete(f"{BASE}/treatments/{tid}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert c.get(f"{BASE}/treatments/{tid}").status_code == 404
    assert tid not in [t["id"] for t in c.get(f"{BASE}/treatments").get_json()["items"]]
    assert c.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert c.get(f"{BASE}/treatments/{tid}").status_code == 200
    assert c.delete(f"{BASE}/treatments/{tid}").status_code == 202
    assert expire_and_purge(app) >= 1
    from backend.app.modules.dentistry.models import Treatment
    with app.app_context(), tenancy.scoped("platform"):
        assert db.session.get(Treatment, tid) is None


# ---------------------------------------------------------------------------- plans
def test_treatment_plan_crud_and_convert(app, dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    body = {"patient_id": pid, "tooth_number": 30, "diagnosis": "Caries", "procedure": "rct", "fee": "120",
            "priority": "high"}
    assert c.post(f"{BASE}/treatment-plans", json=body | {"priority": "urgent"}).status_code == 422
    r = c.post(f"{BASE}/treatment-plans", json=body)
    assert r.status_code == 201, r.get_json()
    plan = r.get_json()
    assert plan["status"] == "planned" and plan["priority"] == "high" and plan["fee"] == "120.00"
    r = c.patch(f"{BASE}/treatment-plans/{plan['id']}", json={"notes": "after cleaning", "version": 1})
    assert r.status_code == 200
    assert c.patch(f"{BASE}/treatment-plans/{plan['id']}", json={"notes": "x", "version": 1}).status_code == 409
    r = c.post(f"{BASE}/treatment-plans/{plan['id']}/convert", json={"version": 2, "create_visit": True})
    assert r.status_code == 201, r.get_json()
    out = r.get_json()
    assert out["treatment"]["plan_id"] == plan["id"] and out["treatment"]["tooth_number"] == 30
    assert out["treatment"]["fee"] == "120.00" and out["treatment"]["visit_id"]
    assert "Caries" in out["treatment"]["description"]
    assert out["plan"]["status"] == "accepted" and out["plan"]["converted_treatment_id"] == out["treatment"]["id"]
    r = c.post(f"{BASE}/treatment-plans/{plan['id']}/convert", json={"version": out["plan"]["version"]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "already_converted"
    lst = c.get(f"{BASE}/treatment-plans?patient_id={pid}&priority=high").get_json()["items"]
    assert [p["id"] for p in lst] == [plan["id"]]
    # isolation
    assert dent["c"](a["users"]["dent_doc2"]).get(f"{BASE}/treatment-plans/{plan['id']}").status_code == 404
    # delete + undo
    r = c.delete(f"{BASE}/treatment-plans/{plan['id']}")
    assert r.status_code == 202
    assert c.get(f"{BASE}/treatment-plans/{plan['id']}").status_code == 404
    assert c.post("/api/v1/undo", json={"undo_token": r.get_json()["undo_token"]}).status_code == 200
    assert c.get(f"{BASE}/treatment-plans/{plan['id']}").status_code == 200
    # purge plan: converted treatment survives with plan_id cleared
    c.delete(f"{BASE}/treatment-plans/{plan['id']}")
    expire_and_purge(app)
    t = c.get(f"{BASE}/treatments/{out['treatment']['id']}").get_json()
    assert t["plan_id"] is None


# ---------------------------------------------------------------------------- timeline / summary
def test_timeline_and_summary(dent):
    a, pid = dent["A"], dent["pid"]
    c = dent["c"](a["users"]["dent_doc1"])
    t = _treat(c, pid, create_visit=True).get_json()
    c.post(f"{BASE}/treatment-plans", json={"patient_id": pid, "procedure": "crown"})
    c.put(f"{BASE}/patients/{pid}/odontogram/permanent/14", json={"condition": "decay"})
    r = c.post("/api/v1/appointments", json={"patient_id": pid, "starts_at": "2026-10-20T10:00",
                                             "duration_minutes": 30, "reason": "check-up"})
    assert r.status_code == 201, r.get_json()
    ev = c.get(f"{BASE}/patients/{pid}/timeline").get_json()["events"]
    types = {e["type"] for e in ev}
    assert {"visit", "treatment", "treatment-plan", "appointment"} <= types
    assert dent["c"](a["users"]["derm_doc"]).get(f"{BASE}/patients/{pid}/timeline").status_code == 404
    assert any(e["type"] == "treatment" and e["id"] == t["id"] and e["tooth"] == "#14" for e in ev)
    s = c.get(f"{BASE}/patients/{pid}/summary").get_json()
    assert s["treatments_total"] == 1 and s["open_plan_items"] == 1 and s["charted_teeth"] == 1
    full = c.get(f"/api/v1/patients/{pid}/summary").get_json()
    dental = [sec for sec in full["sections"] if sec["name"] == "dentistry"]
    assert dental and dental[0]["data"]["treatments_total"] == 1
    # dent2 doctor cannot see this patient's dental section; derm doctor cannot see the patient
    assert dent["c"](a["users"]["dent_doc2"]).get(f"{BASE}/patients/{pid}/summary").status_code == 404
    assert dent["c"](a["users"]["derm_doc"]).get(f"{BASE}/patients/{pid}/summary").status_code == 404
