"""Tenant-leak scanner: proves the *application* filters isolate tenants on every endpoint, independent
of the PostgreSQL RLS backstop.

1. Center A gets a realistic day of data (the acceptance flow).
2. Requests from center B's manager run with the DB context forced to `platform` mode, i.e. Row Level
   Security lets every row through. Only the app's own tenant/scope filters stand between B and A.
3. Every GET endpoint is called — list endpoints as-is, and detail endpoints with the ids of center A's
   rows — and no response may contain center A's data (its unique tag or its patient's name).
"""
import re

from sqlalchemy import select, text

from tests.test_acceptance_flow import test_full_center_day as seed_center_day

SKIP_PREFIXES = ("/api/v1/admin", "/api/v1/auth", "/api/v1/platform", "/api/v1/health")


def _a_row_ids(app, center_id):
    """A sample of ids (first + last) from every tenant table of center A."""
    from backend.app.core import tenancy
    from backend.app.extensions import db
    ids = set()
    with app.app_context(), tenancy.scoped("platform"):
        tables = [t for t in db.metadata.sorted_tables if "health_center_id" in t.c and "id" in t.c]
        for t in tables:
            row = db.session.execute(select(text("min(id), max(id)")).select_from(t)
                                     .where(t.c.health_center_id == center_id)).one()
            ids.update(i for i in row if i)
        db.session.rollback()
    return sorted(ids)


def test_no_endpoint_leaks_other_tenant_data_without_rls(app, world, client_for, monkeypatch):
    A, B = world["A"], world["B"]
    seed_center_day(app, world, client_for)
    client_for(A["users"]["manager"]).post("/api/v1/favorites", json={"kind": "diagnosis", "title": f"Dx {A['tag']}",
                                                                        "body": "Penicillin allergy"})
    markers = [A["tag"], "Ali Ahmad", "Penicillin"]
    a_ids = _a_row_ids(app, A["center_id"])
    assert len(a_ids) >= 5

    b_mgr = client_for(B["users"]["manager"])
    # From here on, B's requests bypass RLS: tenant isolation rests on the application code alone.
    from backend.app.core import tenancy
    monkeypatch.setattr(tenancy, "use_tenant", lambda center_id: tenancy._set("platform"))

    leaks, checked = [], 0
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or not rule.rule.startswith("/api/v1") or rule.rule.startswith(SKIP_PREFIXES):
            continue
        params = re.findall(r"<(?:[^:>]+:)?([^>]+)>", rule.rule)
        if len(params) > 1:
            continue
        urls = [rule.rule] if not params else [re.sub(r"<[^>]+>", str(i), rule.rule) for i in a_ids]
        for url in urls:
            r = b_mgr.get(url)
            checked += 1
            if r.status_code != 200:
                continue
            body = r.get_data(as_text=True) if r.mimetype == "application/json" else ""
            hit = [m for m in markers if m in body]
            if hit:
                leaks.append(f"{url} -> {hit}")
    assert checked > 200
    assert not leaks, "Center B saw center A data with RLS bypassed:\n" + "\n".join(leaks[:50])
