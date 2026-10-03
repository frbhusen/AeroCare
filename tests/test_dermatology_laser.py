"""Laser Hair Removal sessions: numbering (incl. concurrency), areas, history, scope, delete/undo."""
import threading

from sqlalchemy import select

from tests.test_dermatology_support import expire_and_purge, make_patient, platform_rows, png_upload, upload

BASE = "/api/v1/dermatology/laser"
LEGS = [{"region": "full_legs", "side": "front"}, {"region": "full_legs", "side": "back"}]
UNDERARMS = [{"region": "underarm_left", "side": "front"}, {"region": "underarm_right", "side": "front"}]


def _new(client, a, pid, areas, **kw):
    body = {"patient_id": pid, "clinic_id": a["clinics"]["derm1"], "areas": areas, **kw}
    return client.post(f"{BASE}/sessions", json=body)


def test_create_numbering_and_visit(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    r = _new(d, a, pid, LEGS + UNDERARMS, notes="Tolerated well", next_session_at="2026-11-01T10:00:00")
    assert r.status_code == 201, r.get_json()
    s1 = r.get_json()
    assert s1["session_number"] == 1 and len(s1["areas"]) == 4 and s1["owns_visit"] is True and s1["visit_id"]
    assert s1["next_session_at"].startswith("2026-11-01T07:00")  # Damascus +03:00 stored as UTC
    assert s1["areas"][0]["label_ar"]
    s2 = _new(d, a, pid, LEGS).get_json()
    assert s2["session_number"] == 2
    nxt = d.get(f"{BASE}/patients/{pid}/next-number?clinic_id={a['clinics']['derm1']}").get_json()
    assert nxt["next_session_number"] == 3
    # Explicit duplicate number -> 409
    r = _new(d, a, pid, LEGS, session_number=2)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "session_number_taken"
    # Editable number; next auto number follows the max.
    r = d.patch(f"{BASE}/sessions/{s2['id']}", json={"version": s2["version"], "session_number": 5})
    assert r.status_code == 200 and r.get_json()["session_number"] == 5
    r = d.patch(f"{BASE}/sessions/{s2['id']}", json={"version": r.get_json()["version"], "session_number": 1})
    assert r.status_code == 409
    assert _new(d, a, pid, LEGS).get_json()["session_number"] == 6
    # Visit of type 'session' in the derm clinic.
    from backend.app.models import Visit
    v = platform_rows(app, select(Visit.visit_type, Visit.clinic_id).where(Visit.id == s1["visit_id"]))[0]
    assert v == ("session", a["clinics"]["derm1"])
    # Without a visit
    r = _new(d, a, pid, LEGS, create_visit=False)
    assert r.status_code == 201 and r.get_json()["visit_id"] is None


def test_area_validation(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    r = _new(d, a, pid, [{"region": "underarm_left", "side": "back"}])
    assert r.status_code == 422 and "areas.0" in r.get_json()["error"]["details"]
    assert _new(d, a, pid, []).status_code == 422
    assert _new(d, a, pid, [{"region": "wing", "side": "front"}]).status_code == 422
    assert _new(d, a, pid, [{"region": "face", "side": "top"}]).status_code == 422
    # Duplicated areas are collapsed.
    r = _new(d, a, pid, [{"region": "face", "side": "front"}] * 3)
    assert r.status_code == 201 and len(r.get_json()["areas"]) == 1


def test_history_grouping(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    _new(d, a, pid, LEGS + UNDERARMS, session_date="2026-09-01")
    _new(d, a, pid, LEGS + UNDERARMS + [{"region": "face", "side": "front"}], session_date="2026-09-29",
         next_session_at="2026-10-27T09:00:00")
    h = d.get(f"{BASE}/patients/{pid}/history").get_json()
    assert h["total_sessions"] == 2
    assert [s["session_number"] for s in h["sessions"]] == [1, 2]
    assert {x["region"] for x in h["sessions"][0]["areas"]} == {"full_legs", "underarm_left", "underarm_right"}
    assert "face" in {x["region"] for x in h["sessions"][1]["areas"]}
    counts = {c["region"]: c for c in h["area_counts"]}
    assert counts["full_legs"]["count"] == 2 and counts["full_legs"]["sides"] == {"front": 2, "back": 2}
    assert counts["face"]["count"] == 1 and counts["face"]["session_numbers"] == [2]
    assert counts["underarm_left"]["first_date"] == "2026-09-01"
    assert h["last_session_date"] == "2026-09-29" and h["next_session_at"]
    lst = d.get(f"{BASE}/patients/{pid}/sessions").get_json()
    assert lst["total"] == 2 and lst["items"][0]["session_number"] == 2


def test_concurrent_auto_numbering(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    cookie = d.c.get_cookie("hc_session").value
    results, n = [], 8

    def worker():
        c = app.test_client()
        c.set_cookie("hc_session", cookie)
        r = c.post(f"{BASE}/sessions", json={"patient_id": pid, "clinic_id": a["clinics"]["derm1"],
                                              "areas": LEGS, "create_visit": False},
                   headers={"Origin": "http://localhost", "X-CSRF-Token": d.csrf})
        results.append((r.status_code, (r.get_json() or {}).get("session_number")))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(code == 201 for code, _ in results), results
    assert sorted(num for _, num in results) == list(range(1, n + 1))


def test_environment_and_isolation(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    m = client_for(a["users"]["manager"])
    r = m.post(f"{BASE}/sessions", json={"patient_id": pid, "clinic_id": a["clinics"]["dent1"], "areas": LEGS})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "wrong_environment"
    assert m.get(f"{BASE}/patients/{pid}/next-number?clinic_id={a['clinics']['oph1']}").status_code == 422
    d = client_for(a["users"]["derm_doc"])
    s = _new(d, a, pid, LEGS).get_json()
    dent = client_for(a["users"]["dent_doc1"])
    assert dent.get(f"{BASE}/sessions/{s['id']}").status_code == 404
    assert dent.get(f"{BASE}/patients/{pid}/history").status_code == 404
    assert dent.delete(f"{BASE}/sessions/{s['id']}").status_code == 404
    assert _new(dent, a, pid, LEGS).status_code == 404
    rec = client_for(a["users"]["rec_multi"])
    assert rec.get(f"{BASE}/sessions/{s['id']}").status_code == 200
    assert rec.patch(f"{BASE}/sessions/{s['id']}", json={"version": 1, "notes": "x"}).status_code == 403
    assert _new(rec, a, pid, LEGS).status_code == 403
    b = client_for(world["B"]["users"]["manager"])
    assert b.get(f"{BASE}/sessions/{s['id']}").status_code == 404
    assert b.get(f"{BASE}/patients/{pid}/history").status_code == 404
    assert b.post(f"{BASE}/sessions", json={"patient_id": pid, "clinic_id": world["B"]["clinics"]["derm1"],
                                             "areas": LEGS}).status_code == 404


def test_update_version_conflict(world, client_for, app):
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    s = _new(d, a, pid, LEGS).get_json()
    r = d.patch(f"{BASE}/sessions/{s['id']}", json={"version": 1, "areas": UNDERARMS, "notes": "n"})
    assert r.status_code == 200
    assert {x["region"] for x in r.get_json()["areas"]} == {"underarm_left", "underarm_right"}
    r = d.patch(f"{BASE}/sessions/{s['id']}", json={"version": 1, "notes": "stale"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"


def test_delete_undo_purge_and_photos(world, client_for, app):
    from backend.app.models import StoredFile, Visit
    from backend.app.modules.dermatology.models import LaserSession, LaserSessionArea
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    s = _new(d, a, pid, LEGS).get_json()
    r = upload(d, f"{BASE}/sessions/{s['id']}/photos", png_upload("legs.png"))
    assert r.status_code == 201, r.get_json()
    fid = r.get_json()["items"][0]["id"]
    assert r.get_json()["items"][0]["owner_type"] == "laser_session"
    assert d.get(f"{BASE}/sessions/{s['id']}/photos").get_json()["items"][0]["id"] == fid
    assert client_for(a["users"]["dent_doc1"]).get(f"{BASE}/sessions/{s['id']}/photos").status_code == 404
    assert d.get(f"{BASE}/sessions/{s['id']}").get_json()["photo_count"] == 1
    r = d.delete(f"{BASE}/sessions/{s['id']}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert d.get(f"{BASE}/sessions/{s['id']}").status_code == 404
    assert d.get(f"{BASE}/patients/{pid}/history").get_json()["total_sessions"] == 0
    assert d.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert d.get(f"{BASE}/sessions/{s['id']}").status_code == 200
    token = d.delete(f"{BASE}/sessions/{s['id']}").get_json()["undo_token"]
    expire_and_purge(app, token)
    assert platform_rows(app, select(LaserSession.id).where(LaserSession.id == s["id"])) == []
    assert platform_rows(app, select(LaserSessionArea.id).where(LaserSessionArea.session_id == s["id"])) == []
    assert platform_rows(app, select(Visit.id).where(Visit.id == s["visit_id"])) == []
    assert platform_rows(app, select(StoredFile.id).where(StoredFile.id == fid)) == []
    # Numbering restarts from the live maximum.
    assert _new(d, a, pid, LEGS).get_json()["session_number"] == 1


def test_laser_summary(world, client_for, app):
    from backend.app.core import tenancy
    from backend.app.modules.dermatology import laser_service
    from tests.test_dermatology_support import principal_for
    a = world["A"]
    pid = make_patient(app, a)
    d = client_for(a["users"]["derm_doc"])
    _new(d, a, pid, LEGS + UNDERARMS)
    with app.app_context(), tenancy.scoped("tenant", a["center_id"]):
        s = laser_service.patient_summary(principal_for(app, a["users"]["derm_doc"]["id"]), pid)
        assert s["session_count"] == 1 and s["area_counts"]["full_legs"] == 1
        assert laser_service.patient_summary(principal_for(app, a["users"]["oph_doc"]["id"]), pid) is None
