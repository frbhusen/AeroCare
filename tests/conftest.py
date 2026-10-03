"""Test harness. Tests run against a real PostgreSQL test database using the *runtime* role
(hc_app, NOBYPASSRLS) so Row Level Security is exercised exactly as in production.

The schema is rebuilt once per session. Each test gets fresh centers via the `world` fixture
(unique names per test), so tests never depend on each other's data.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("FLASK_ENV", "testing")
os.environ["HC_DISABLE_PURGER"] = "1"

from backend.app import create_app  # noqa: E402
from backend.app.config import TestingConfig  # noqa: E402

PASSWORD = "Test-Password-123"


def _reset_schema():
    eng = create_engine(TestingConfig.SCHEMA_DATABASE_URL)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    _reset_schema()
    storage = tmp_path_factory.mktemp("storage")
    app = create_app("testing", STORAGE_ROOT=str(storage), BACKUP_ROOT=str(tmp_path_factory.mktemp("backups")))
    from backend.app.schema import init_schema
    from backend.app.cli import seed_catalog
    with app.app_context():
        init_schema(app, echo=lambda *a: None)
        seed_catalog()
    return app


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield
        from backend.app.extensions import db
        db.session.remove()


class ApiClient:
    """Test client that remembers the CSRF token and sends same-origin headers."""

    def __init__(self, app):
        self.c = app.test_client()
        self.csrf = None
        self.me = None

    def login(self, email, password=PASSWORD):
        r = self.c.post("/api/v1/auth/login", json={"email": email, "password": password},
                        headers={"Origin": "http://localhost"})
        if r.status_code == 200:
            self.me = r.get_json()
            self.csrf = self.me["csrf_token"]
        return r

    def _h(self, headers):
        h = {"Origin": "http://localhost"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        h.update(headers or {})
        return h

    def get(self, url, **kw):
        return self.c.get(url, headers=self._h(kw.pop("headers", None)), **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture()
def client_for(app):
    """client_for(user_or_email) -> logged-in ApiClient."""
    def make(user):
        cl = ApiClient(app)
        email = user if isinstance(user, str) else user["email"]
        r = cl.login(email)
        assert r.status_code == 200, r.get_json()
        return cl
    return make


@pytest.fixture()
def world(app):
    """Two isolated centers (A and B), each with the standard structure. See tests/factories.py."""
    from tests.factories import build_center
    tag = uuid.uuid4().hex[:6]
    with app.app_context():
        a = build_center(f"Center A {tag}", f"a{tag}")
        b = build_center(f"Center B {tag}", f"b{tag}")
        superadmin = build_superadmin(f"sa{tag}")
    return {"A": a, "B": b, "superadmin": superadmin}


def build_superadmin(username):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.services.accounts import create_user_record
    with tenancy.scoped("platform"):
        u = create_user_record(center_id=None, username=username, name="Platform Owner", role="superadmin",
                               password=PASSWORD)
        db.session.commit()
        return {"id": u.id, "email": u.email}
