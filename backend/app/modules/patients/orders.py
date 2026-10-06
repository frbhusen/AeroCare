"""Visit Investigation Orders service: lab requests & radiology studies linked to a visit."""
from sqlalchemy import select

from backend.app.core.timeutil import iso
from backend.app.extensions import db
from backend.app.models.clinical import Visit
from backend.app.services.clinical import get_visit


def get_visit_orders(p, visit_id):
    p.require("medical_records.view")
    v = get_visit(p, visit_id)

    # Fetch Lab Requests for this visit
    lab_items = []
    try:
        from backend.app.modules.laboratory.models import LabRequest, LabRequestItem
        stmt = (select(LabRequest)
                .where(p.tenant(LabRequest), LabRequest.visit_id == visit_id, LabRequest.live())
                .order_by(LabRequest.requested_at.desc()))
        for req in db.session.execute(stmt).scalars().all():
            items = db.session.execute(
                select(LabRequestItem).where(LabRequestItem.request_id == req.id)
            ).scalars().all()
            lab_items.append({
                "id": req.id,
                "status": req.status,
                "priority": req.priority,
                "clinical_notes": req.clinical_notes,
                "requested_at": iso(req.requested_at),
                "finalized_at": iso(req.finalized_at),
                "tests": [{"id": it.id, "test_name": it.test_name, "result_value": it.result_value if req.status == "completed" else None, "abnormal_flag": it.abnormal_flag if req.status == "completed" else None} for it in items],
            })
    except Exception:
        pass

    # Fetch Radiology Studies for this visit
    rad_items = []
    try:
        from backend.app.modules.radiology.models import RadiologyStudy
        stmt = (select(RadiologyStudy)
                .where(p.tenant(RadiologyStudy), RadiologyStudy.visit_id == visit_id, RadiologyStudy.live())
                .order_by(RadiologyStudy.requested_at.desc()))
        for study in db.session.execute(stmt).scalars().all():
            rad_items.append({
                "id": study.id,
                "exam_type": study.exam_type,
                "body_region": study.body_region,
                "clinical_question": study.clinical_question,
                "priority": study.priority,
                "status": study.status,
                "requested_at": iso(study.requested_at),
                "findings": study.findings if study.status == "finalized" else None,
                "impression": study.impression if study.status == "finalized" else None,
            })
    except Exception:
        pass

    return {
        "visit_id": visit_id,
        "patient_id": v.patient_id,
        "lab_requests": lab_items,
        "radiology_studies": rad_items,
    }
