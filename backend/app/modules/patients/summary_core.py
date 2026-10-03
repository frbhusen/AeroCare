"""Core Complete-Patient-Summary sections: general profile, departments indicator, visits per
accessible clinic. (Prescriptions, files and generic records register from their modules.)"""
from sqlalchemy import func, select

from backend.app.extensions import db
from backend.app.models import Visit

from .summary import register_summary_provider

VISIT_LIMIT = 200


def _profile(p, patient):
    from .service import patient_json
    return patient_json(patient)


def _departments(p, patient):
    from .service import departments_indicator
    return departments_indicator(p, patient)


def _visits(p, patient):
    if not p.has("medical_records.view"):
        return None
    from .visits import serialize_many
    base = (Visit.patient_id == patient.id, p.tenant(Visit), Visit.live(), p.clinic_clause(Visit.clinic_id))
    rows = db.session.execute(select(Visit).where(*base).order_by(Visit.visit_at.desc(), Visit.id.desc())
                              .limit(VISIT_LIMIT)).scalars().all()
    totals = dict(db.session.execute(select(Visit.clinic_id, func.count()).where(*base)
                                     .group_by(Visit.clinic_id)).all())
    groups = {}
    for v in serialize_many(p.center_id, rows):
        g = groups.setdefault(v["clinic_id"], {
            "clinic_id": v["clinic_id"], "clinic_name": v["clinic_name"], "department_id": v["department_id"],
            "department_name": v["department_name"], "environment": v["environment"],
            "total": int(totals.get(v["clinic_id"], 0)), "visits": []})
        g["visits"].append(v)
    return {"clinics": list(groups.values()), "truncated": sum(totals.values()) > len(rows)}


register_summary_provider("profile", _profile, order=0)
register_summary_provider("departments", _departments, order=10)
register_summary_provider("visits", _visits, order=20)
