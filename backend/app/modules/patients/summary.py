"""Complete Patient Summary: an extensible, access-scoped aggregate (spec §22).

Any module contributes a section by registering a provider at import time:

    from backend.app.modules.patients.summary import register_summary_provider

    def dental_summary(p, patient):
        if not p.has("medical_records.view"):
            return None
        rows = ...  # MUST be filtered with p.tenant(...) + p.clinic_clause(<Model>.clinic_id) + live()
        return {"title": "Dentistry", "items": [...]} if rows else None

    register_summary_provider("dentistry", dental_summary, order=200)

Contract (also in docs/modules/patients.md):
  * fn(p, patient) is called only after the patient is confirmed visible to p and p has
    patients.view. `patient` is a live `Patient` ORM object of p's center.
  * Return a JSON-serializable dict/list, or None to omit the section (no access / no data).
  * The provider alone is responsible for scoping: include ONLY rows the principal may see
    (tenant + clinic scope, live rows, its own permission checks). Never reveal restricted
    departments' details.
  * Read-only. Each provider runs inside a SAVEPOINT; an exception omits the section (logged)
    instead of breaking the whole summary.
  * Keep it bounded (e.g. latest 50 items) — the summary is a single request.

This file is deliberately import-light so other modules can import it at load time.
"""
import logging

from flask import current_app

log = logging.getLogger("hc.patients.summary")

_PROVIDERS = {}  # name -> (order, fn)


def register_summary_provider(name, fn, order=100):
    """Register (or replace) the section `name`. Lower `order` renders first."""
    _PROVIDERS[name] = (order, fn)


def providers():
    return [(name, fn) for name, (order, fn) in sorted(_PROVIDERS.items(), key=lambda kv: (kv[1][0], kv[0]))]


def build_summary(p, patient):
    from backend.app.extensions import db
    sections = []
    for name, fn in providers():
        try:
            with db.session.begin_nested():
                data = fn(p, patient)
        except Exception:
            log.exception("summary provider %s failed", name)
            if current_app.config.get("TESTING"):
                raise
            continue
        if data is not None:
            sections.append({"name": name, "data": data})
    return {"patient_id": patient.id, "sections": sections}
