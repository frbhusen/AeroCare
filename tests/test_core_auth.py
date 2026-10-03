from sqlalchemy import select, text

from tests.conftest import ApiClient, PASSWORD


def test_login_me_and_scope(app, world, client_for):
    a = world["A"]
    c = client_for(a["users"]["dent_doc1"])
    me = c.get("/api/v1/auth/me").get_json()
    assert me["user"]["role"] == "doctor"
    assert me["principal"]["clinic_ids"] == [a["clinics"]["dent1"]]
    # Department isolation: a dentistry doctor only sees Dentistry in navigation.
    assert [d["environment"] for d in me["departments"]] == ["dentistry"]
    assert me["portal"] == "department"


def test_bad_password_rejected(app, world):
    c = ApiClient(app)
    r = c.login(world["A"]["users"]["manager"]["email"], "wrong-password")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "invalid_credentials"


def test_single_session_enforced(app, world):
    email = world["A"]["users"]["manager"]["email"]
    first, second = ApiClient(app), ApiClient(app)
    assert first.login(email).status_code == 200
    assert first.get("/api/v1/auth/me").status_code == 200
    assert second.login(email).status_code == 200
    r = first.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "session_replaced"
    assert second.get("/api/v1/auth/me").status_code == 200


def test_csrf_token_required(app, world, client_for):
    c = client_for(world["A"]["users"]["manager"])
    r = c.c.post("/api/v1/notifications/read", json={}, headers={"Origin": "http://localhost"})
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "csrf_token"
    r = c.post("/api/v1/notifications/read", json={}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "csrf_origin"
    assert c.post("/api/v1/notifications/read", json={}).status_code == 200


def test_rls_fails_closed_without_context(app, world):
    """Defense in depth: the runtime DB role sees no tenant rows without a tenant context,
    and only its own center's rows with one."""
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import Clinic, User
    with app.app_context():
        with tenancy.scoped(""):
            assert db.session.execute(select(Clinic)).first() is None
            assert db.session.execute(select(User)).first() is None
        db.session.rollback()
        with tenancy.scoped("tenant", world["A"]["center_id"]):
            centers = set(db.session.execute(select(Clinic.health_center_id)).scalars())
            assert centers == {world["A"]["center_id"]}
        db.session.rollback()
        role = db.session.execute(text("select rolbypassrls or rolsuper from pg_roles where rolname = current_user")
                                  ).scalar()
        assert role is False


def test_archived_user_cannot_login(app, world):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import User
    u = world["A"]["users"]["gen_doc"]
    with app.app_context(), tenancy.scoped("platform"):
        db.session.get(User, u["id"]).status = "archived"
        db.session.commit()
    assert ApiClient(app).login(u["email"]).status_code == 401


def test_expired_center_blocks_staff(app, world):
    from datetime import timedelta
    from backend.app.core import tenancy
    from backend.app.core.timeutil import utcnow
    from backend.app.extensions import db
    from backend.app.models import HealthCenter
    b = world["B"]
    c = ApiClient(app)
    assert c.login(b["users"]["manager"]["email"]).status_code == 200
    with app.app_context(), tenancy.scoped("platform"):
        hc = db.session.get(HealthCenter, b["center_id"])
        hc.status, hc.trial_ends_at = "trial", utcnow() - timedelta(minutes=1)
        db.session.commit()
    r = c.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "center_inactive"
    r = ApiClient(app).login(b["users"]["manager"]["email"])
    assert r.status_code == 403
