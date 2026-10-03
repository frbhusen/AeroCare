"""Radiology workflow: schedule, start, images, report, finalize, cancel, explicit shares."""
import io
import logging

from sqlalchemy import false, select
from werkzeug.datastructures import FileStorage

from backend.app.authz.principal import current_principal
from backend.app.core.api import check_version
from backend.app.core.errors import Conflict, Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import DateTime, Id, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Department, FileShare, User
from backend.app.services import files as files_svc
from backend.app.services.clinical import link_patient_to_clinic

from backend.app.modules.laboratory import notify as N
from .models import RadiologyStudyShare
from .service import images, load, require_radiology, require_status, study_json

log = logging.getLogger("hc.radiology")


def _assign_clinic(p, s, clinic_id):
    if clinic_id is not None:
        if p.clinic_department.get(clinic_id) != s.radiology_department_id or not p.can_clinic(clinic_id):
            raise ValidationError("Invalid input", details={"radiology_clinic_id": "is invalid"})
        s.radiology_clinic_id = clinic_id
    elif s.radiology_clinic_id is None:
        mine = [c for c in sorted(p.clinic_ids) if p.clinic_department.get(c) == s.radiology_department_id]
        if p.user.clinic_id in mine:
            s.radiology_clinic_id = p.user.clinic_id
        elif len(mine) == 1:
            s.radiology_clinic_id = mine[0]
    if s.radiology_clinic_id is not None:
        link_patient_to_clinic(p.center_id, s.patient_id, s.radiology_clinic_id, s.radiology_department_id)


def schedule(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    require_radiology(level)
    check_version(s, data.get("version"))
    require_status(s, "requested", "scheduled")
    d = validate(data, {"scheduled_at": DateTime(required=True), "radiology_clinic_id": Id()})
    _assign_clinic(p, s, d.get("radiology_clinic_id"))
    s.scheduled_at, s.status = d["scheduled_at"], "scheduled"
    db.session.commit()
    return study_json(p, s, level)


def start(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    require_radiology(level)
    check_version(s, data.get("version"))
    require_status(s, "requested", "scheduled")
    d = validate(data, {"radiology_clinic_id": Id()})
    _assign_clinic(p, s, d.get("radiology_clinic_id"))
    if s.radiology_clinic_id is None:
        raise ValidationError("Choose the radiology clinic performing the study.",
                              details={"radiology_clinic_id": "is required"})
    s.status, s.performed_at = "in_progress", utcnow()
    db.session.commit()
    return study_json(p, s, level)


def upload_images(sid, uploads, description=None):
    p = current_principal()
    s, level = load(p, sid)
    require_radiology(level)
    require_status(s, "in_progress", "reported")
    p.require("files.upload", clinic_id=s.radiology_clinic_id)
    rows = files_svc.store_upload(p, uploads, clinic_id=s.radiology_clinic_id, department_id=s.radiology_department_id,
                                  patient_id=s.patient_id, visit_id=None, category="radiology_image",
                                  owner_type="radiology_study", owner_id=s.id,
                                  description=(description or None) and description[:2000])
    return {"items": [files_svc.serialize(f, p) for f in rows]}


def write_report(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    require_radiology(level)
    check_version(s, data.get("version"))
    require_status(s, "in_progress", "reported")
    d = validate(data, {"findings": Text(max_len=20000), "impression": Text(max_len=10000)}, partial=True)
    for k, v in d.items():
        setattr(s, k, v)
    if not (s.findings or s.impression):
        raise ValidationError("Write the findings or the impression.", details={"findings": "is required"})
    s.radiologist_user_id, s.radiologist_name, s.radiologist_role = p.user.id, p.user.name, p.user.role
    s.reported_at, s.status = utcnow(), "reported"
    db.session.commit()
    return study_json(p, s, level)


def _share_files(s, file_ids, by_user_id, *, clinic_id=None, department_id=None, user_id=None):
    for fid in file_ids:
        q = select(FileShare.id).where(FileShare.health_center_id == s.health_center_id, FileShare.file_id == fid)
        q = q.where(FileShare.target_clinic_id == clinic_id) if clinic_id else \
            q.where(FileShare.target_department_id == department_id) if department_id else \
            q.where(FileShare.target_user_id == user_id)
        if db.session.execute(q).first() is None:
            db.session.add(FileShare(health_center_id=s.health_center_id, file_id=fid, target_clinic_id=clinic_id,
                                     target_department_id=department_id, target_user_id=user_id,
                                     shared_by=by_user_id))


def _study_file_ids(s):
    ids = [f.id for f in images(s)]
    if s.report_file_id:
        ids.append(s.report_file_id)
    return ids


def finalize(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    require_radiology(level)
    check_version(s, data.get("version"))
    require_status(s, "reported")
    s.status, s.finalized_at = "finalized", utcnow()
    s.finalized_by_user_id, s.finalized_by_name = p.user.id, p.user.name
    if s.radiology_clinic_id != s.requesting_clinic_id:
        _share_files(s, [f.id for f in images(s)], p.user.id, clinic_id=s.requesting_clinic_id)
    N.radiology_result(p, s)
    db.session.commit()
    _attach_pdf(p, s)  # best-effort, separate transaction
    return study_json(p, s, level)


def _attach_pdf(p, s):
    from .report import render_pdf, report_payload
    try:
        pdf = render_pdf(s, report_payload(p, s, "radiology"), "en")
        up = FileStorage(stream=io.BytesIO(pdf), filename=f"radiology-report-{s.id}.pdf")
        f = files_svc.store_upload(p, [up], clinic_id=s.radiology_clinic_id, department_id=s.radiology_department_id,
                                   patient_id=s.patient_id, category="radiology_report",
                                   owner_type="radiology_study", owner_id=s.id, commit=False)[0]
        s.report_file_id = f.id
        targets = [dict(clinic_id=s.requesting_clinic_id)] if s.radiology_clinic_id != s.requesting_clinic_id else []
        for sh in db.session.execute(select(RadiologyStudyShare).where(RadiologyStudyShare.study_id == s.id)).scalars():
            targets.append(dict(clinic_id=sh.target_clinic_id, department_id=sh.target_department_id,
                                user_id=sh.target_user_id))
        for t in targets:
            _share_files(s, [f.id], p.user.id, **t)
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.exception("radiology report PDF generation failed for study %s", s.id)


def cancel(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    check_version(s, data.get("version"))
    d = validate(data, {"reason": Str(max_len=500)})
    if level == "radiology":
        require_status(s, "requested", "scheduled", "in_progress")
    elif p.has("radiology.request") and p.can_clinic(s.requesting_clinic_id):
        require_status(s, "requested", "scheduled")
    else:
        raise Forbidden("You cannot cancel this study.", details={"permission": "radiology.request"})
    s.status, s.cancelled_at = "cancelled", utcnow()
    s.cancelled_by_name, s.cancel_reason = p.user.name, d.get("reason")
    db.session.commit()
    return study_json(p, s, level)


# ---- explicit shares of finalized studies -------------------------------------
def _can_share(p, s, level):
    if s.status != "finalized":
        raise Conflict("Only finalized studies can be shared.", code="invalid_status", details={"status": s.status})
    if level == "radiology" or (level == "requester" and p.has("files.share")):
        return
    raise Forbidden("You cannot share this study.", details={"permission": "files.share"})


def share_json(sh, names=None):
    return {"id": sh.id, "target_clinic_id": sh.target_clinic_id, "target_department_id": sh.target_department_id,
            "target_user_id": sh.target_user_id, "target_name": (names or {}).get(sh.id),
            "shared_by": sh.shared_by_name, "created_at": iso(sh.created_at)}


def _target_names(center_id, shares):
    out = {}
    for sh in shares:
        if sh.target_clinic_id:
            out[sh.id] = db.session.execute(select(Clinic.name).where(Clinic.id == sh.target_clinic_id,
                                                                      Clinic.health_center_id == center_id)).scalar()
        elif sh.target_department_id:
            out[sh.id] = db.session.execute(select(Department.name).where(
                Department.id == sh.target_department_id, Department.health_center_id == center_id)).scalar()
        else:
            out[sh.id] = db.session.execute(select(User.name).where(User.id == sh.target_user_id,
                                                                    User.health_center_id == center_id)).scalar()
    return out


def list_shares(sid):
    p = current_principal()
    s, level = load(p, sid)
    if level not in ("radiology", "requester"):
        raise Forbidden("You cannot view the shares of this study.")
    rows = db.session.execute(select(RadiologyStudyShare).where(RadiologyStudyShare.study_id == s.id,
                                                                p.tenant(RadiologyStudyShare))
                              .order_by(RadiologyStudyShare.id)).scalars().all()
    names = _target_names(p.center_id, rows)
    return {"items": [share_json(r, names) for r in rows]}


def add_share(sid, data):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    _can_share(p, s, level)
    d = validate(data, {"target_clinic_id": Id(), "target_department_id": Id(), "target_user_id": Id()})
    given = {k: v for k, v in d.items() if v is not None}
    if len(given) != 1:
        raise ValidationError("Choose exactly one target (clinic, department or doctor).", code="one_target")
    cid, did, uid = d.get("target_clinic_id"), d.get("target_department_id"), d.get("target_user_id")
    if cid and not db.session.execute(select(Clinic.id).where(Clinic.id == cid, p.tenant(Clinic), Clinic.live(),
                                                              Clinic.is_active.is_(True))).first():
        raise ValidationError("Invalid input", details={"target_clinic_id": "is invalid"})
    if did and not db.session.execute(select(Department.id).where(Department.id == did, p.tenant(Department),
                                                                  Department.live())).first():
        raise ValidationError("Invalid input", details={"target_department_id": "is invalid"})
    if uid and not db.session.execute(select(User.id).where(User.id == uid, User.health_center_id == p.center_id,
                                                            User.status == "active")).first():
        raise ValidationError("Invalid input", details={"target_user_id": "is invalid"})
    q = select(RadiologyStudyShare).where(RadiologyStudyShare.study_id == s.id, p.tenant(RadiologyStudyShare),
                                          RadiologyStudyShare.target_clinic_id.is_(None) if cid is None else
                                          RadiologyStudyShare.target_clinic_id == cid,
                                          RadiologyStudyShare.target_department_id.is_(None) if did is None else
                                          RadiologyStudyShare.target_department_id == did,
                                          RadiologyStudyShare.target_user_id.is_(None) if uid is None else
                                          RadiologyStudyShare.target_user_id == uid)
    sh = db.session.execute(q).scalar_one_or_none()
    if sh is None:
        sh = RadiologyStudyShare(health_center_id=p.center_id, study_id=s.id, target_clinic_id=cid,
                                 target_department_id=did, target_user_id=uid, shared_by=p.user.id,
                                 shared_by_name=p.user.name)
        db.session.add(sh)
        _share_files(s, _study_file_ids(s), p.user.id, clinic_id=cid, department_id=did, user_id=uid)
        db.session.commit()
    return share_json(sh, _target_names(p.center_id, [sh]))


def remove_share(sid, share_id):
    p = current_principal()
    s, level = load(p, sid, for_update=True)
    _can_share(p, s, level)
    sh = db.session.execute(select(RadiologyStudyShare).where(
        RadiologyStudyShare.id == share_id, RadiologyStudyShare.study_id == s.id, p.tenant(RadiologyStudyShare))
    ).scalar_one_or_none()
    if sh is None:
        raise NotFound("Share not found")
    ids = _study_file_ids(s)
    if ids:
        q = select(FileShare).where(FileShare.health_center_id == p.center_id, FileShare.file_id.in_(ids))
        if sh.target_clinic_id:
            q = q.where(FileShare.target_clinic_id == sh.target_clinic_id)
            # never revoke the automatic share to the requesting clinic
            if sh.target_clinic_id == s.requesting_clinic_id:
                q = q.where(false())
        elif sh.target_department_id:
            q = q.where(FileShare.target_department_id == sh.target_department_id)
        else:
            q = q.where(FileShare.target_user_id == sh.target_user_id)
        for fs in db.session.execute(q).scalars():
            db.session.delete(fs)
    db.session.delete(sh)
    db.session.commit()
    return {"ok": True}

