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
