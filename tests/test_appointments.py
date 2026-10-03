"""Appointments: scope, permissions, doctor auto-assignment, double-booking (service + DB),
concurrency race, status transitions, walk-in, WhatsApp link, delete + undo, versioning."""
import threading

import pytest
from sqlalchemy import select

from backend.app.core import tenancy
from backend.app.extensions import db

API = "/api/v1/appointments"
DAY = "2026-11-10"


def make_patient(app, center, name="Test Patient", phone="0944 123 456"):
    from backend.app.models import Patient
    from backend.app.services.centers import next_sequence
    from backend.app.services.clinical import normalize_name, phone_digits
    with app.app_context(), tenancy.scoped("platform"):
        code = next_sequence(center["center_id"], "patient_seq")
        pt = Patient(health_center_id=center["center_id"], code=code, full_name=name, search_name=normalize_name(name),
                     phone=phone, phone_digits=phone_digits(phone))
        db.session.add(pt)
        db.session.commit()
        return pt.id


def book(c, patient_id, start, end=None, **kw):
    body = {"patient_id": patient_id, "starts_at": f"{DAY}T{start}:00"}
    if end:
        body["ends_at"] = f"{DAY}T{end}:00"
    body.update(kw)
    return c.post(API, json=body)


@pytest.fixture()
def A(world):
    return world["A"]


def test_create_by_receptionist_defaults_and_link(app, A, client_for):
    pid = make_patient(app, A)
    c = client_for(A["users"]["rec_dent1"])
    r = book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=A["users"]["dent_doc1"]["id"],
             reason="Checkup")
    assert r.status_code == 201, r.get_json()
    a = r.get_json()
    assert a["status"] == "scheduled" and a["location"] == "Room dent1"
    assert a["start_time"] == "10:00" and a["end_time"] == "10:30" and a["local_date"] == DAY
    assert a["doctor"]["id"] == A["users"]["dent_doc1"]["id"]
    assert a["department"]["id"] == A["departments"]["dentistry"]
    assert a["created_by"]["id"] == A["users"]["rec_dent1"]["id"] and a["created_by"]["role"] == "receptionist"
    # Patient is now linked to the clinic, so the clinic's doctor sees the patient.
    from backend.app.models import PatientClinicLink
    with app.app_context(), tenancy.scoped("platform"):
        assert db.session.execute(select(PatientClinicLink).where(
            PatientClinicLink.patient_id == pid, PatientClinicLink.clinic_id == A["clinics"]["dent1"])).first()
    # Doctor gets an appointment_created notification; the actor does not.
    doc = client_for(A["users"]["dent_doc1"])
    types = [n["type"] for n in doc.get("/api/v1/notifications").get_json()["items"]]
    assert "appointment_created" in types
    assert not [n for n in c.get("/api/v1/notifications").get_json()["items"] if n["type"] == "appointment_created"]


def test_doctor_auto_assignment(app, A, client_for):
    pid = make_patient(app, A)
    c = client_for(A["users"]["dent_doc1"])
    # Even when another clinic/doctor is sent, a doctor books in their own clinic for themselves.
    r = book(c, pid, "09:00", duration_minutes=20, clinic_id=A["clinics"]["dent2"],
             doctor_id=A["users"]["dent_doc2"]["id"])
    assert r.status_code == 201, r.get_json()
    a = r.get_json()
    assert a["clinic"]["id"] == A["clinics"]["dent1"] and a["doctor"]["id"] == A["users"]["dent_doc1"]["id"]
    assert a["duration_minutes"] == 20


def test_validation_errors(app, A, client_for):
    pid = make_patient(app, A)
    c = client_for(A["users"]["manager"])
    assert book(c, pid, "10:00", "10:30").status_code == 422  # clinic required for non-doctors
    r = book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=A["users"]["derm_doc"]["id"])
    assert r.status_code == 422 and "doctor_id" in r.get_json()["error"]["details"]
    r = book(c, pid, "10:00", "09:30", clinic_id=A["clinics"]["dent1"])
    assert r.status_code == 422
    assert c.post(API, json={"clinic_id": A["clinics"]["dent1"]}).status_code == 422
    assert book(c, 999999, "10:00", "10:30", clinic_id=A["clinics"]["dent1"]).status_code == 404


def _seed_three(app, A, client_for):
    pid = make_patient(app, A)
    m = client_for(A["users"]["manager"])
    ids = {}
    for key in ("dent1", "dent2", "derm1"):
        r = book(m, pid, "10:00", "10:30", clinic_id=A["clinics"][key])
        assert r.status_code == 201, r.get_json()
        ids[key] = r.get_json()["id"]
    return pid, ids


@pytest.mark.parametrize("user,expected", [
    ("manager", {"dent1", "dent2", "derm1"}),
    ("dent_head", {"dent1", "dent2"}),
    ("dent_doc1", {"dent1"}),
    ("derm_doc", {"derm1"}),
    ("rec_dent1", {"dent1"}),
    ("rec_dent", {"dent1", "dent2"}),
    ("rec_multi", {"dent1", "dent2", "derm1"}),
    ("rec_center", {"dent1", "dent2", "derm1"}),
    ("gen_doc", set()),
])
def test_scope_per_role(app, A, client_for, user, expected):
    _, ids = _seed_three(app, A, client_for)
    c = client_for(A["users"][user])
    items = c.get(f"{API}?from={DAY}&to={DAY}").get_json()["items"]
    assert {i["id"] for i in items} == {ids[k] for k in expected}
    for key, aid in ids.items():
        assert c.get(f"{API}/{aid}").status_code == (200 if key in expected else 404)
    sched = c.get(f"{API}/schedule?date={DAY}&view=week").get_json()
    assert {i["id"] for d in sched["days"] for i in d["items"]} == {ids[k] for k in expected}


def test_out_of_scope_and_cross_tenant(app, world, client_for):
    A, B = world["A"], world["B"]
    _, ids = _seed_three(app, A, client_for)
    pid = make_patient(app, A)
    rec = client_for(A["users"]["rec_dent1"])
    assert book(rec, pid, "12:00", "12:30", clinic_id=A["clinics"]["derm1"]).status_code == 404
    assert rec.put(f"{API}/{ids['derm1']}", json={"version": 1, "reason": "x"}).status_code == 404
    assert rec.delete(f"{API}/{ids['derm1']}").status_code == 404
    bm = client_for(B["users"]["manager"])
    for aid in ids.values():
        assert bm.get(f"{API}/{aid}").status_code == 404
        assert bm.put(f"{API}/{aid}", json={"version": 1, "reason": "x"}).status_code == 404
        assert bm.post(f"{API}/{aid}/status", json={"status": "cancelled", "version": 1}).status_code == 404
        assert bm.get(f"{API}/{aid}/whatsapp").status_code == 404
        assert bm.delete(f"{API}/{aid}").status_code == 404
    assert bm.get(f"{API}?from={DAY}").get_json()["items"] == []
    # Center B cannot book a center A patient or clinic.
    assert book(bm, pid, "12:00", "12:30", clinic_id=B["clinics"]["dent1"]).status_code == 404
    pb = make_patient(app, B)
    assert book(bm, pb, "12:00", "12:30", clinic_id=A["clinics"]["dent1"]).status_code == 404


def test_permission_denied(app, A, client_for):
    from backend.app.models import UserPermission
    _, ids = _seed_three(app, A, client_for)
    uid = A["users"]["rec_dent1"]["id"]
    with app.app_context(), tenancy.scoped("platform"):
        for perm in ("appointments.create", "appointments.delete"):
            db.session.add(UserPermission(health_center_id=A["center_id"], user_id=uid, permission=perm,
                                          allowed=False))
        db.session.commit()
    c = client_for(A["users"]["rec_dent1"])
    pid = make_patient(app, A)
    assert book(c, pid, "12:00", "12:30", clinic_id=A["clinics"]["dent1"]).status_code == 403
    assert c.delete(f"{API}/{ids['dent1']}").status_code == 403
    assert c.get(f"{API}/{ids['dent1']}").status_code == 200


def test_doctor_and_clinic_conflicts(app, A, client_for):
    pid = make_patient(app, A)
    m = client_for(A["users"]["manager"])
    d1 = A["users"]["dent_doc1"]["id"]
    assert book(m, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1).status_code == 201
    r = book(m, pid, "10:15", "10:45", clinic_id=A["clinics"]["dent1"], doctor_id=d1)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "appointment_conflict"
    assert r.get_json()["error"]["details"]["conflicts"][0]["kind"] == "doctor"
    # Same clinic, another doctor (the department head works in dent1): clinic double-booking.
    r = book(m, pid, "10:15", "10:45", clinic_id=A["clinics"]["dent1"], doctor_id=A["users"]["dent_head"]["id"])
    assert r.status_code == 409 and r.get_json()["error"]["details"]["conflicts"][0]["kind"] == "clinic"
    # Back-to-back is fine; another clinic at the same time is fine.
    assert book(m, pid, "10:30", "11:00", clinic_id=A["clinics"]["dent1"], doctor_id=d1).status_code == 201
    assert book(m, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent2"]).status_code == 201


def test_database_constraints_are_authoritative(app, A):
    """Bypass the service pre-check: the exclusion constraints still reject overlaps."""
    from datetime import datetime
    from sqlalchemy.exc import IntegrityError
    from backend.app.core.timeutil import TZ
    from backend.app.models import Clinic
    from backend.app.modules.appointments.models import Appointment
    pid = make_patient(app, A)
    s, e = datetime(2026, 11, 10, 10, 0, tzinfo=TZ), datetime(2026, 11, 10, 11, 0, tzinfo=TZ)

    def add(clinic_key, doctor_key=None, status="scheduled"):
        cl = db.session.get(Clinic, A["clinics"][clinic_key])
        db.session.add(Appointment(health_center_id=A["center_id"], department_id=cl.department_id,
                                   clinic_id=cl.id, patient_id=pid, starts_at=s, ends_at=e, status=status,
                                   doctor_id=A["users"][doctor_key]["id"] if doctor_key else None, author_name="t"))
        db.session.commit()

    with app.app_context(), tenancy.scoped("tenant", A["center_id"]):
        add("dent1", "dent_doc1")
        with pytest.raises(IntegrityError) as ei:  # same doctor, different clinic
            add("dent2", "dent_doc1")
        assert ei.value.orig.diag.constraint_name == "ex_appointments_doctor"
        db.session.rollback()
        with pytest.raises(IntegrityError) as ei:  # same clinic, no doctor
            add("dent1")
        assert ei.value.orig.diag.constraint_name == "ex_appointments_clinic"
        db.session.rollback()
        add("dent1", "dent_doc1", status="cancelled")  # cancelled rows never block


def test_concurrent_booking_race(app, A, client_for):
    pid = make_patient(app, A)
    clients = [client_for(A["users"]["manager"]), client_for(A["users"]["rec_center"])]
    for slot in ("08:00", "13:00", "16:00"):
        barrier = threading.Barrier(2)
        results = []

        def run(c):
            barrier.wait()
            r = book(c, pid, slot, duration_minutes=30, clinic_id=A["clinics"]["gen1"],
                     doctor_id=A["users"]["gen_doc"]["id"])
            results.append((r.status_code, (r.get_json().get("error") or {}).get("code")))

        threads = [threading.Thread(target=run, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(s for s, _ in results) == [201, 409], results
        assert [code for s, code in results if s == 409] == ["appointment_conflict"]
    items = clients[0].get(f"{API}?from={DAY}&clinic_id={A['clinics']['gen1']}").get_json()["items"]
    assert len(items) == 3


def test_cancel_frees_slot_and_status_flow(app, A, client_for):
    pid = make_patient(app, A)
    c = client_for(A["users"]["rec_dent1"])
    d1 = A["users"]["dent_doc1"]["id"]
    a = book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1).get_json()
    r = c.post(f"{API}/{a['id']}/status", json={"status": "cancelled", "version": a["version"]})
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    cancelled = r.get_json()
    doc = client_for(A["users"]["dent_doc1"])
    assert "appointment_cancelled" in [n["type"] for n in doc.get("/api/v1/notifications").get_json()["items"]]
    b = book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1)
    assert b.status_code == 201
    b = b.get_json()
    # Re-activating the cancelled one would double-book.
    r = c.post(f"{API}/{a['id']}/status", json={"status": "scheduled", "version": cancelled["version"]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "appointment_conflict"
    # Normal flow: scheduled -> arrived -> in_progress -> completed; completed -> cancelled is invalid.
    v = b["version"]
    for st in ("arrived", "in_progress", "completed"):
        r = c.post(f"{API}/{b['id']}/status", json={"status": st, "version": v})
        assert r.status_code == 200, r.get_json()
        v = r.get_json()["version"]
    assert "patient_arrived" in [n["type"] for n in doc.get("/api/v1/notifications").get_json()["items"]]
    r = c.post(f"{API}/{b['id']}/status", json={"status": "cancelled", "version": v})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "invalid_transition"
    assert c.post(f"{API}/{b['id']}/status", json={"status": "bogus", "version": v}).status_code == 422


def test_edit_and_version_conflict(app, A, client_for):
    pid = make_patient(app, A)
    c = client_for(A["users"]["rec_dent"])
    d1 = A["users"]["dent_doc1"]["id"]
    a = book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1).get_json()
    other = book(c, pid, "11:00", "11:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1).get_json()
    r = c.put(f"{API}/{a['id']}", json={"version": a["version"], "starts_at": f"{DAY}T12:00:00", "notes": "moved"})
    assert r.status_code == 200, r.get_json()
    e = r.get_json()
    assert e["start_time"] == "12:00" and e["end_time"] == "12:30" and e["notes"] == "moved"
    assert e["version"] == a["version"] + 1
    # Stale version -> 409, nothing overwritten.
    r = c.put(f"{API}/{a['id']}", json={"version": a["version"], "notes": "stale"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "version_conflict"
    assert c.get(f"{API}/{a['id']}").get_json()["notes"] == "moved"
    # Moving onto another appointment -> conflict.
    r = c.put(f"{API}/{a['id']}", json={"version": e["version"], "starts_at": f"{DAY}T11:15:00"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "appointment_conflict"
    # Move to dent2: location follows the clinic, the dent1 doctor must be replaced.
    r = c.put(f"{API}/{a['id']}", json={"version": e["version"], "clinic_id": A["clinics"]["dent2"]})
    assert r.status_code == 422
    r = c.put(f"{API}/{a['id']}", json={"version": e["version"], "clinic_id": A["clinics"]["dent2"],
                                        "doctor_id": A["users"]["dent_doc2"]["id"]})
    assert r.status_code == 200 and r.get_json()["location"] == "Room dent2"
    assert c.put(f"{API}/{other['id']}", json={"notes": "x"}).status_code == 422  # version required


def test_walk_in(app, A, client_for):
    from backend.app.models import Clinic
    pid = make_patient(app, A)
    with app.app_context(), tenancy.scoped("platform"):
        db.session.get(Clinic, A["clinics"]["dent2"]).settings = {"appointment_duration_minutes": 20}
        db.session.commit()
    c = client_for(A["users"]["rec_dent"])
    r = c.post(f"{API}/walk-in", json={"patient_id": pid, "clinic_id": A["clinics"]["dent1"],
                                       "doctor_id": A["users"]["dent_doc1"]["id"]})
    assert r.status_code == 201, r.get_json()
    w = r.get_json()
    assert w["status"] == "arrived" and w["is_walk_in"] and w["duration_minutes"] == 15
    doc = client_for(A["users"]["dent_doc1"])
    assert "patient_arrived" in [n["type"] for n in doc.get("/api/v1/notifications").get_json()["items"]]
    r = c.post(f"{API}/walk-in", json={"patient_id": pid, "clinic_id": A["clinics"]["dent2"]})
    assert r.status_code == 201 and r.get_json()["duration_minutes"] == 20
    meta = c.get(f"{API}/meta").get_json()
    assert {x["id"]: x["default_duration_minutes"] for x in meta["clinics"]}[A["clinics"]["dent2"]] == 20
    docs = c.get(f"{API}/doctors?clinic_id={A['clinics']['dent1']}").get_json()["items"]
    assert {d["id"] for d in docs} == {A["users"]["dent_doc1"]["id"], A["users"]["dent_head"]["id"]}
    assert c.get(f"{API}/doctors?clinic_id={A['clinics']['derm1']}").status_code == 404


def test_whatsapp_link(app, world, client_for):
    from urllib.parse import unquote
    A = world["A"]
    pid = make_patient(app, A, name="Ali Hasan", phone="0944 123 456")
    c = client_for(A["users"]["rec_dent1"])
    a = book(c, pid, "14:30", "15:00", clinic_id=A["clinics"]["dent1"]).get_json()
    r = c.get(f"{API}/{a['id']}/whatsapp?lang=en")
    assert r.status_code == 200
    w = r.get_json()
    assert w["url"].startswith("https://wa.me/963944123456?text=")
    assert unquote(w["url"].split("text=", 1)[1]) == w["message"]
    from backend.app.models import HealthCenter
    with app.app_context(), tenancy.scoped("platform"):
        center_name = db.session.get(HealthCenter, A["center_id"]).name
    for part in (center_name, "11/10/2026", "14:30", "Dental Clinic 1", "Room dent1", "Ali Hasan"):
        assert part in w["message"]
    ar = c.get(f"{API}/{a['id']}/whatsapp?lang=ar").get_json()
    assert "موعدك" in ar["message"] and "14:30" in ar["message"]
    nophone = make_patient(app, A, phone=None)
    b = book(c, nophone, "16:00", "16:30", clinic_id=A["clinics"]["dent1"]).get_json()
    r = c.get(f"{API}/{b['id']}/whatsapp")
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "no_phone"


def test_phone_normalization():
    from backend.app.modules.appointments.reminders import normalize_phone
    assert normalize_phone("0944123456") == "963944123456"
    assert normalize_phone("+963 944 123 456") == "963944123456"
    assert normalize_phone("00963944123456") == "963944123456"
    assert normalize_phone("944123456") == "963944123456"
    assert normalize_phone("abc") is None


def test_delete_and_undo(app, A, client_for):
    pid = make_patient(app, A)
    c = client_for(A["users"]["rec_dent1"])
    d1 = A["users"]["dent_doc1"]["id"]
    a = book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1).get_json()
    r = c.delete(f"{API}/{a['id']}")
    assert r.status_code == 202
    token = r.get_json()["undo_token"]
    assert c.get(f"{API}/{a['id']}").status_code == 404
    assert c.get(f"{API}?from={DAY}").get_json()["items"] == []
    assert c.post("/api/v1/undo", json={"undo_token": token}).status_code == 200
    assert c.get(f"{API}/{a['id']}").status_code == 200
    # Deleted slot is free; undo is refused if someone booked it meanwhile.
    token = c.delete(f"{API}/{a['id']}").get_json()["undo_token"]
    assert book(c, pid, "10:00", "10:30", clinic_id=A["clinics"]["dent1"], doctor_id=d1).status_code == 201
    r = c.post("/api/v1/undo", json={"undo_token": token})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "appointment_conflict"
