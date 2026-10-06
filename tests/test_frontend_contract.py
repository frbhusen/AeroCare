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


IMPORT_RE = re.compile(r"""^\s*import\s*(?:([\s\S]*?)\s*from\s*)?["'](\.[^"']+)["']""", re.M)
EXPORT_RE = re.compile(r"""export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z0-9_$]+)""")


def _exports(f):
    src = f.read_text(encoding="utf-8")
    names = set(EXPORT_RE.findall(src))
    for block in re.findall(r"export\s*\{([^}]*)\}", src):
        names.update(x.strip().split(" as ")[-1].strip() for x in block.split(",") if x.strip())
    return names, bool(re.search(r"export\s*\*", src))


def test_ui_relative_imports_resolve():
    """Every relative ES import must point at a real file (exact case: Linux servers are case-sensitive)
    and every named import must be exported there, otherwise the whole module graph fails to load."""
    problems = []
    for f in WEB.rglob("*.js"):
        for names, spec in IMPORT_RE.findall(f.read_text(encoding="utf-8")):
            target = (f.parent / spec).resolve()
            src = str(f.relative_to(WEB))
            if not target.is_file() or target.name not in {p.name for p in target.parent.iterdir()}:
                problems.append(f"{src}: missing {spec}")
                continue
            braces = re.search(r"\{([^}]*)\}", names or "")
            if not braces:
                continue
            exported, star = _exports(target)
            for item in braces.group(1).split(","):
                name = item.strip().split(" as ")[0].strip()
                if name and not star and name not in exported:
                    problems.append(f"{src}: '{name}' is not exported by {spec}")
    assert not problems, "Broken UI imports:\n" + "\n".join(sorted(problems))
