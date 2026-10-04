"""Frontend ↔ backend contract checks that need no browser.

Permission codes referenced by the UI (route/menu `perm:`, `can(...)`, `has(...)`) must exist in
the backend catalog, otherwise the screen is silently hidden from everyone.
"""
import re
from pathlib import Path

from backend.app.authz.permissions import CATALOG

WEB = Path(__file__).resolve().parents[1] / "web" / "js"
PERM_RE = re.compile(r"""(?:perm:\s*|can\(\s*|has\(\s*)["']([a-z_]+\.[a-z_]+)["']""")


def test_ui_permission_codes_exist():
    unknown = {}
    for f in WEB.rglob("*.js"):
        for code in PERM_RE.findall(f.read_text(encoding="utf-8")):
            if code not in CATALOG:
                unknown.setdefault(code, []).append(str(f.relative_to(WEB)))
    assert not unknown, f"UI references unknown permissions: {unknown}"


CALL_RE = re.compile(r"""api\.(get|post|put|patch|del)\(\s*(["'`])(/[^"'`]*)\2""")
METHOD = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "del": "DELETE"}


def _ui_calls():
    for f in WEB.rglob("*.js"):
        for m, _q, path in CALL_RE.findall(f.read_text(encoding="utf-8")):
            exprs = re.findall(r"\$\{([^}]*)\}", path)
            if any("id" not in e.lower() and "encodeURIComponent" not in e for e in exprs):
                continue  # dynamic action segment (e.g. `/lab/requests/${id}/${action}`): not checkable statically
            path = re.sub(r"\$\{[^}]*\}", "1", path).split("?")[0]
            yield METHOD[m], path, str(f.relative_to(WEB))


def test_ui_api_calls_match_backend_routes(app):
    """Every literal api.<method>('/path') in the UI must match a registered backend route+method."""
    adapter = app.url_map.bind("localhost")
    missing = []
    for method, path, src in _ui_calls():
        try:
            adapter.match("/api/v1" + path, method=method)
        except Exception as e:  # NotFound / MethodNotAllowed / RequestRedirect
            if type(e).__name__ == "RequestRedirect":
                continue
            missing.append(f"{method} {path}  ({src})")
    assert not missing, "UI calls with no backend route:\n" + "\n".join(sorted(set(missing)))
