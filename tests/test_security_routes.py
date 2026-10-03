"""Route-level security sweep across ALL modules:
* every /api endpoint declares its auth mode via the authz decorators
* unauthenticated calls to non-public endpoints are rejected (401/403/405), never 200
* non-superadmins are rejected from superadmin endpoints
"""
import re

from tests.conftest import ApiClient

PUBLIC_ALLOWED = {"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/health"}
PUBLIC_PREFIXES = ("/api/v1/platform/branding",)


def _api_rules(app):
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/"):
            yield rule, app.view_functions[rule.endpoint]


def _concrete(rule):
    return re.sub(r"<(?:[^:>]+:)?[^>]+>", "1", rule.rule)


def test_every_endpoint_declares_auth(app):
    missing = [r.rule for r, fn in _api_rules(app) if getattr(fn, "_auth", None) is None]
    assert not missing, f"endpoints without an authz decorator: {missing}"


def test_public_endpoints_are_whitelisted(app):
    public = {r.rule for r, fn in _api_rules(app) if getattr(fn, "_auth", None) == "public"}
    unexpected = {p for p in public if p not in PUBLIC_ALLOWED and not p.startswith(PUBLIC_PREFIXES)}
    assert not unexpected, f"unexpected public endpoints: {unexpected}"


def test_unauthenticated_requests_rejected(app):
    c = ApiClient(app)
    for rule, fn in _api_rules(app):
        if getattr(fn, "_auth", None) == "public":
            continue
        url = _concrete(rule)
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            r = c.c.open(url, method=method, json={}, headers={"Origin": "http://localhost"})
            assert r.status_code in (401, 403, 405), f"{method} {url} -> {r.status_code}"


def test_staff_cannot_reach_superadmin_endpoints(app, world, client_for):
    c = client_for(world["A"]["users"]["manager"])
    for rule, fn in _api_rules(app):
        if getattr(fn, "_auth", None) != "superadmin" or "GET" not in rule.methods:
            continue
        r = c.get(_concrete(rule))
        assert r.status_code in (403, 404), f"GET {rule.rule} -> {r.status_code}"
