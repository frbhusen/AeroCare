"""Recurring appointments: creation, all-or-nothing conflicts, limits, edit this / this_and_future."""
from datetime import date

import pytest

from backend.app.modules.appointments.recurrence import expand
from tests.test_appointments import API, make_patient

START = "2026-11-02T10:00:00"  # Monday


def recurring(c, pid, clinic_id, doctor_id=None, rule=None, start=START, minutes=30):
    body = {"patient_id": pid, "clinic_id": clinic_id, "starts_at": start, "duration_minutes": minutes,
            "rule": rule or {"freq": "weekly", "count": 4}, "reason": "Course"}
    if doctor_id:
        body["doctor_id"] = doctor_id
    return c.post(f"{API}/recurring", json=body)


def test_expand_rules():
    d = date(2026, 11, 2)  # Monday
    assert expand(d, "daily", 2, count=3) == [date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 6)]
    assert expand(d, "weekly", 1, [1, 4], count=4) == [date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 9),
                                                     date(2026, 11, 12)]
    assert expand(d, "weekly", 2, until=date(2026, 11, 30)) == [date(2026, 11, 2), date(2026, 11, 16),
                                                               date(2026, 11, 30)]
    assert expand(date(2026, 1, 31), "monthly", 1, count=3) == [date(2026, 1, 31), date(2026, 3, 31),
                                                              date(2026, 5, 31)]
    from backend.app.core.errors import ValidationError
    with pytest.raises(ValidationError):
        expand(d, "daily", 1, count=201)
    with pytest.raises(ValidationError):
        expand(d, "daily", 1, until=date(2027, 12, 31))
    with pytest.raises(ValidationError):
        expand(d, "daily", 1)


def test_recurring_create_and_conflicts(app, world, client_for):
    A = world["A"]
    pid = make_patient(app, A)
    c = client_for(A["users"]["rec_dent1"])
    d1 = A["users"]["dent_doc1"]["id"]
    # Pre-book the third week's slot: the whole series is rejected with the conflicting date.
    r = c.post(API, json={"patient_id": pid, "clinic_id": A["clinics"]["dent1"], "doctor_id": d1,
                          "starts_at": "2026-11-16T10:15:00", "duration_minutes": 30})
    assert r.status_code == 201
    r = recurring(c, pid, A["clinics"]["dent1"], d1)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "appointment_conflict"
    assert r.get_json()["error"]["details"]["conflicting_dates"] == ["2026-11-16"]
    assert len(c.get(f"{API}?from=2026-11-01&to=2026-11-30").get_json()["items"]) == 1  # nothing created
    # Too many occurrences.
    r = recurring(c, pid, A["clinics"]["dent1"], d1, rule={"freq": "daily", "count": 201})
    assert r.status_code == 422
    r = recurring(c, pid, A["clinics"]["dent1"], d1, rule={"freq": "daily", "until": "2027-12-31"})
    assert r.status_code == 422 and r.get_json()["error"]["code"] == "too_many_occurrences"
    # A doctor creating a series is auto-assigned.
    doc = client_for(A["users"]["dent_doc1"])
    r = recurring(doc, pid, None, rule={"freq": "weekly", "count": 3}, start="2026-12-07T09:00:00")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert [i["local_date"] for i in body["items"]] == ["2026-12-07", "2026-12-14", "2026-12-21"]
    assert {i["doctor"]["id"] for i in body["items"]} == {d1}
    assert [i["series_index"] for i in body["items"]] == [0, 1, 2]
    assert body["series"]["start_time"] == "09:00" and body["series"]["freq"] == "weekly"
    # Cross-tenant: series is invisible to center B.
    bm = client_for(world["B"]["users"]["manager"])
    assert bm.get(f"{API}/series/{body['series']['id']}").status_code == 404


def test_edit_this_and_this_and_future(app, world, client_for):
    A = world["A"]
    pid = make_patient(app, A)
    c = client_for(A["users"]["manager"])
    d1 = A["users"]["dent_doc1"]["id"]
    r = recurring(c, pid, A["clinics"]["dent1"], d1)
    assert r.status_code == 201, r.get_json()
    items = r.get_json()["items"]
    sid = r.get_json()["series"]["id"]
    # Only this one.
    r = c.put(f"{API}/{items[1]['id']}", json={"version": items[1]["version"], "mode": "this",
                                               "starts_at": "2026-11-09T11:00:00", "notes": "only me"})
    assert r.status_code == 200, r.get_json()
    s = c.get(f"{API}/series/{sid}").get_json()
    times = [(i["local_date"], i["start_time"]) for i in s["items"]]
    assert times == [("2026-11-02", "10:00"), ("2026-11-09", "11:00"), ("2026-11-16", "10:00"),
                     ("2026-11-23", "10:00")]
    assert s["series"]["start_time"] == "10:00"
    # This and future from the 3rd: time + duration + reason change for 3rd and 4th only.
    third = s["items"][2]
    r = c.put(f"{API}/{third['id']}", json={"version": third["version"], "mode": "this_and_future",
                                            "starts_at": "2026-11-16T14:00:00", "duration_minutes": 45,
                                            "reason": "Changed"})
    assert r.status_code == 200, r.get_json()
    s = c.get(f"{API}/series/{sid}").get_json()
    got = [(i["local_date"], i["start_time"], i["end_time"], i["reason"]) for i in s["items"]]
    assert got == [("2026-11-02", "10:00", "10:30", "Course"), ("2026-11-09", "11:00", "11:30", "Course"),
                   ("2026-11-16", "14:00", "14:45", "Changed"), ("2026-11-23", "14:00", "14:45", "Changed")]
    assert s["series"]["start_time"] == "14:00" and s["series"]["duration_minutes"] == 45
    assert s["series"]["reason"] == "Changed"
    # Each generated appointment stays individually manageable.
    last = s["items"][3]
    r = c.post(f"{API}/{last['id']}/status", json={"status": "cancelled", "version": last["version"]})
    assert r.status_code == 200
    # Conflicting this_and_future edit is rejected as a whole, listing the dates.
    blocker = c.post(API, json={"patient_id": pid, "clinic_id": A["clinics"]["dent1"], "doctor_id": d1,
                                "starts_at": "2026-11-16T16:00:00", "duration_minutes": 30}).get_json()
    assert blocker["id"]
    third = c.get(f"{API}/{third['id']}").get_json()
    r = c.put(f"{API}/{third['id']}", json={"version": third["version"], "mode": "this_and_future",
                                            "starts_at": "2026-11-16T16:00:00"})
    assert r.status_code == 409 and r.get_json()["error"]["details"]["conflicting_dates"] == ["2026-11-16"]
    assert c.get(f"{API}/{third['id']}").get_json()["start_time"] == "14:00"


def test_this_and_future_shift_onto_own_slots(app, world, client_for):
    """Shifting a daily series by one day moves each occurrence onto the next one's old slot;
    deferred constraints allow the swap within one transaction."""
    A = world["A"]
    pid = make_patient(app, A)
    c = client_for(A["users"]["manager"])
    r = recurring(c, pid, A["clinics"]["gen1"], A["users"]["gen_doc"]["id"], rule={"freq": "daily", "count": 3})
    items = r.get_json()["items"]
    r = c.put(f"{API}/{items[0]['id']}", json={"version": items[0]["version"], "mode": "this_and_future",
                                               "starts_at": "2026-11-03T10:00:00"})
    assert r.status_code == 200, r.get_json()
    s = c.get(f"{API}/series/{r.get_json()['series_id']}").get_json()
    assert [i["local_date"] for i in s["items"]] == ["2026-11-03", "2026-11-04", "2026-11-05"]


def test_cancel_whole_series_and_from_occurrence(world, client_for):
    A = world["A"]
    c = client_for(A["users"]["rec_dent"])
    from tests.test_appointments import make_patient  # noqa: E402
    import flask
    pid = make_patient(flask.current_app._get_current_object() if flask.has_app_context() else None, A) \
        if False else None
    # create a patient through the API instead (no direct DB access needed)
    pid = c.post("/api/v1/patients", json={"full_name": "Series Patient", "clinic_id": A["clinics"]["dent1"]}).get_json()["id"]
    r = recurring(c, pid, A["clinics"]["dent1"], rule={"freq": "weekly", "count": 4}, start="2027-01-04T10:00:00")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    sid, items = body["series"]["id"], body["items"]
    # First occurrence already happened (arrived) -> must be kept.
    first = items[0]
    assert c.post(f"{API}/{first['id']}/status", json={"status": "arrived", "version": first["version"]}).status_code == 200
    # Cancel from the 3rd occurrence on.
    r = c.post(f"{API}/series/{sid}/cancel", json={"from_appointment_id": items[2]["id"]})
    assert r.status_code == 200 and r.get_json()["cancelled"] == 2
    statuses = [x["status"] for x in c.get(f"{API}/series/{sid}").get_json()["items"]]
    assert statuses == ["arrived", "scheduled", "cancelled", "cancelled"]
    # Cancel the rest of the series.
    assert c.post(f"{API}/series/{sid}/cancel", json={}).get_json()["cancelled"] == 1
    # Other center cannot touch it; doctor of another clinic cannot either.
    assert client_for(world["B"]["users"]["manager"]).post(f"{API}/series/{sid}/cancel", json={}).status_code == 404
    assert client_for(A["users"]["dent_doc2"]).post(f"{API}/series/{sid}/cancel", json={}).status_code == 404
