"""Feature modules. Each subpackage may contain:
    models.py  - SQLAlchemy models (imported on load)
    api.py     - `bp` Flask Blueprint (registered under /api/v1 by create_app)
    service.py - business logic
Adding a module = adding a package here; no shared file needs editing.
"""
import importlib
import pkgutil

_loaded = None


def load_all():
    """Import every module's models and api; return list of blueprints."""
    global _loaded
    if _loaded is not None:
        return _loaded
    bps = []
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if not m.ispkg:
            continue
        base = f"{__name__}.{m.name}"
        for sub in ("models", "api"):
            try:
                mod = importlib.import_module(f"{base}.{sub}")
            except ModuleNotFoundError as e:
                if e.name == f"{base}.{sub}":
                    continue
                raise
            if sub == "api" and hasattr(mod, "bp"):
                bps.append(mod.bp)
    _loaded = bps
    return bps
