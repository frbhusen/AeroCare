"""Patient-summary section for radiology studies (registered with patients.summary if present)."""
from sqlalchemy import or_, select

from backend.app.core.timeutil import iso
from backend.app.extensions import db

from .models import RadiologyStudy
from .service import radiology_side_clause, requester_clause, shared_clause


def radiology_summary(p, patient):
    rows = db.session.execute(
        select(RadiologyStudy).where(p.tenant(RadiologyStudy), RadiologyStudy.live(),
                                     RadiologyStudy.patient_id == patient.id,
                                     or_(requester_clause(p), radiology_side_clause(p), shared_clause(p)))
        .order_by(RadiologyStudy.requested_at.desc(), RadiologyStudy.id.desc()).limit(20)).scalars().all()
    if not rows:
        return None
    return {"title": "Radiology", "items": [
        {"id": s.id, "status": s.status, "exam_type": s.exam_type, "body_region": s.body_region,
         "requested_at": iso(s.requested_at), "finalized_at": iso(s.finalized_at),
         "impression": s.impression if s.status == "finalized" else None} for s in rows]}


def register():
    try:
        from backend.app.modules.patients.summary import register_summary_provider
    except ImportError:
        return False
    register_summary_provider("radiology", radiology_summary, order=610)
    return True


register()
