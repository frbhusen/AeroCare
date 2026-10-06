"""Password policy, forced change after an administrator-chosen password, idle session expiry."""
from datetime import timedelta

from tests.conftest import ApiClient

V = "/api/v1"


def test_password_policy_on_create_and_change(world, client_for):
    A = world["A"]
    mgr = client_for(A["users"]["manager"])
    base = {"role": "doctor", "name": "New Doc", "clinic_id": A["clinics"]["dent1"]}
    for bad in ("short1", "onlyletterspassword", "12345678901", "newdoc999pass"):
        r = mgr.post(f"{V}/center/staff", json={**base, "username": "newdoc999", "password": bad})
        assert r.status_code == 422, (bad, r.get_json())
        assert "password" in r.get_json()["error"]["details"]
    me = client_for(A["users"]["gen_doc"])
    r = me.post(f"{V}/auth/change-password", json={"current_password": "Test-Password-123",
                                                   "new_password": "Test-Password-123"})
    assert r.status_code == 422


def test_admin_chosen_password_forces_change(app, world, client_for):
    A = world["A"]
    mgr = client_for(A["users"]["manager"])
    r = mgr.post(f"{V}/center/staff", json={"role": "doctor", "name": "Fresh Doc", "username": "fresh.doc",
                                            "clinic_id": A["clinics"]["dent1"], "password": "Temp-Pass-2026"})
    assert r.status_code == 201, r.get_json()
    email = r.get_json()["email"]
    c = ApiClient(app)
    login = c.login(email, "Temp-Pass-2026")
    assert login.status_code == 200 and login.get_json()["user"]["must_change_password"] is True
    blocked = c.get(f"{V}/patients")
    assert blocked.status_code == 403 and blocked.get_json()["error"]["code"] == "password_change_required"
    assert c.post(f"{V}/auth/change-password", json={"current_password": "Temp-Pass-2026",
                                                     "new_password": "My-Own-Secret-77"}).status_code == 200
    assert c.get(f"{V}/patients").status_code == 200
    assert c.get(f"{V}/auth/me").get_json()["user"]["must_change_password"] is False
    # A reset by the manager forces it again (and ends existing sessions).
    uid = r.get_json()["id"]
    assert mgr.post(f"{V}/center/staff/{uid}/password", json={"password": "Reset-Pass-2026"}).status_code in (200, 204)
    c2 = ApiClient(app)
    assert c2.login(email, "Reset-Pass-2026").get_json()["user"]["must_change_password"] is True


def test_idle_session_expires_but_daily_use_does_not(app, world):
    from backend.app.core import tenancy
    from backend.app.core.timeutil import utcnow
    from backend.app.extensions import db
    from backend.app.models import UserSession
    email = world["A"]["users"]["rec_dent"]["email"]
    c = ApiClient(app)
    assert c.login(email).status_code == 200
    uid = world["A"]["users"]["rec_dent"]["id"]

    def age(days):
        with app.app_context(), tenancy.scoped("auth"):
            s = db.session.query(UserSession).filter_by(user_id=uid, revoked_at=None).one()
            s.last_seen_at = utcnow() - timedelta(days=days)
            db.session.commit()

    age(29)  # used within the last month: still signed in
    assert c.get(f"{V}/auth/me").status_code == 200
    age(31)
    r = c.get(f"{V}/auth/me")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "session_expired"
