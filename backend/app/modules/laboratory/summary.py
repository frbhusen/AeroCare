"""Patient-summary section for laboratory results (registered with patients.summary if present)."""
from sqlalchemy import or_, select

from backend.app.core.timeutil import iso
from backend.app.extensions import db

from .models import LabRequest, LabRequestItem
from .service import lab_side_clause, requester_clause, result_clause


def lab_summary(p, patient):
    rows = db.session.execute(
        select(LabRequest).where(p.tenant(LabRequest), LabRequest.live(), LabRequest.patient_id == patient.id,
                                 or_(requester_clause(p), lab_side_clause(p), result_clause(p)))
        .order_by(LabRequest.requested_at.desc(), LabRequest.id.desc()).limit(20)).scalars().all()
    if not rows:
        return None
    done = [r.id for r in rows if r.status == "completed"]
    abnormal = {}
    if done:
        for rid, flag in db.session.execute(select(LabRequestItem.request_id, LabRequestItem.abnormal_flag)
                                            .where(LabRequestItem.request_id.in_(done))).all():
            if flag in ("L", "H", "A"):
                abnormal[rid] = abnormal.get(rid, 0) + 1
    names = {}
    for rid, name in db.session.execute(select(LabRequestItem.request_id, LabRequestItem.test_name)
                                        .where(LabRequestItem.request_id.in_([r.id for r in rows]))
                                        .order_by(LabRequestItem.sort_order)).all():
        names.setdefault(rid, []).append(name)
    return {"title": "Laboratory", "items": [
        {"id": r.id, "status": r.status, "priority": r.priority, "requested_at": iso(r.requested_at),
         "finalized_at": iso(r.finalized_at), "tests": names.get(r.id, []),
         "abnormal_count": abnormal.get(r.id, 0) if r.status == "completed" else None,
         "link": f"#/laboratory/requests/{r.id}"} for r in rows]}


def register():
    try:
        from backend.app.modules.patients.summary import register_summary_provider
    except ImportError:
        return False
    register_summary_provider("laboratory", lab_summary, order=600)
    return True


register()
