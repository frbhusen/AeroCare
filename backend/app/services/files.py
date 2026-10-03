"""File service shared by every module: upload with quota, access checks, sharing.

Access rule (docs/PERMISSIONS.md "Files"):
  a principal may view a file if it has files.view (or medical_records.view for clinical files) AND
    * the file is center_wide (finalized lab reports, branding), or
    * the file's owning clinic is in the principal's scope, or
    * the file belongs to no clinic but its department is managed by the principal, or
    * the principal is center-wide (center manager / support mode), or
    * the file is shared with one of the principal's departments, clinics, or with the user.
Patient-bound files additionally require the patient to be visible to the principal, except
center-wide files (lab reports are center-wide by design, spec §71/§104).
"""
from sqlalchemy import exists, func, or_, select, false

from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.storage import get_storage, sha256, validate_upload
from backend.app.extensions import db
from backend.app.models import FileShare, HealthCenter, StoredFile
from backend.app.core.timeutil import iso


def visible_clause(p):
    """SQL clause for StoredFile rows visible to principal p (tenant filter included)."""
    if p.center_wide:
        return (StoredFile.health_center_id == p.center_id) & StoredFile.live()
    clinics = sorted(p.clinic_ids) or [-1]
    managed = sorted(p.managed_department_ids) or [-1]
    visible_depts = sorted(p.visible_department_ids) or [-1]
    shared = exists().where(
        FileShare.file_id == StoredFile.id,
        or_(FileShare.target_clinic_id.in_(clinics), FileShare.target_department_id.in_(visible_depts),
            FileShare.target_user_id == p.user.id))
    return (StoredFile.health_center_id == p.center_id) & StoredFile.live() & or_(
        StoredFile.center_wide.is_(True),
        StoredFile.clinic_id.in_(clinics),
        StoredFile.clinic_id.is_(None) & StoredFile.department_id.in_(managed),
        shared,
    )


def get_visible(p, file_id):
    f = db.session.execute(select(StoredFile).where(StoredFile.id == file_id, visible_clause(p))).scalar_one_or_none()
    if f is None:
        raise NotFound("File not found")
    if f.patient_id and not f.center_wide and not p.center_wide:
        from backend.app.models import Patient
        ok = db.session.execute(select(Patient.id).where(Patient.id == f.patient_id, p.patient_clause(Patient.id))
                                ).first()
        shared_direct = db.session.execute(select(FileShare.id).where(FileShare.file_id == f.id)).first()
        if not ok and not shared_direct:
            raise NotFound("File not found")
    return f


def can_manage(p, f):
    """Rename/annotate/delete/share: owner clinic in scope (or managed department / center-wide)."""
    if p.center_wide:
        return True
    if f.clinic_id is not None:
        return p.can_clinic(f.clinic_id)
    return f.department_id is not None and p.can_department(f.department_id)


def _lock_center_and_check_quota(center_id, incoming):
    center = db.session.execute(select(HealthCenter).where(HealthCenter.id == center_id).with_for_update()
                                ).scalar_one()
    used = db.session.execute(select(func.coalesce(func.sum(StoredFile.size_bytes), 0))
                              .where(StoredFile.health_center_id == center_id)).scalar_one()
    if used + incoming > center.storage_quota_bytes:
        raise ValidationError("Storage quota exceeded for this health center.", code="quota_exceeded",
                              details={"used_bytes": int(used), "quota_bytes": int(center.storage_quota_bytes)})
    return center, used


def store_upload(p, uploads, *, clinic_id=None, department_id=None, patient_id=None, visit_id=None,
                 category="document", owner_type=None, owner_id=None, center_wide=False, description=None,
                 commit=True):
    """Validate + quota-check + persist a list of werkzeug FileStorage objects atomically.
    Callers must have already authorized the target (clinic/patient/visit) for p."""
    if not uploads:
        raise ValidationError("No files were uploaded.", code="no_files")
    if len(uploads) > 20:
        raise ValidationError("Upload at most 20 files at once.")
    prepared = []
    for up in uploads:
        data = up.read()
        name, mime = validate_upload(up.filename, data)
        prepared.append((name, mime, data))
    total = sum(len(d) for _, _, d in prepared)
    center, used = _lock_center_and_check_quota(p.center_id, total)
    storage = get_storage()
    rows, written = [], []
    try:
        for name, mime, data in prepared:
            key = storage.new_key(p.center_id)
            storage.save(key, data)
            written.append(key)
            f = StoredFile(health_center_id=p.center_id, clinic_id=clinic_id, department_id=department_id,
                           patient_id=patient_id, visit_id=visit_id, category=category, owner_type=owner_type,
                           owner_id=owner_id, original_name=name, display_name=name, storage_key=key,
                           mime_type=mime, size_bytes=len(data), sha256=sha256(data), center_wide=center_wide,
                           description=description)
            f.set_author(p.user)
            db.session.add(f)
            rows.append(f)
        center.storage_used_bytes = used + total
        if commit:
            db.session.commit()
        else:
            db.session.flush()
    except Exception:
        db.session.rollback()
        for k in written:
            storage.delete(k)
        raise
    return rows


def storage_usage(center_id):
    center = db.session.get(HealthCenter, center_id)
    used = db.session.execute(select(func.coalesce(func.sum(StoredFile.size_bytes), 0))
                              .where(StoredFile.health_center_id == center_id)).scalar_one()
    return {"used_bytes": int(used), "quota_bytes": int(center.storage_quota_bytes),
            "remaining_bytes": max(0, int(center.storage_quota_bytes) - int(used))}


def serialize(f, p=None):
    return {
        "id": f.id, "display_name": f.display_name, "original_name": f.original_name, "mime_type": f.mime_type,
        "size_bytes": f.size_bytes, "category": f.category, "clinic_id": f.clinic_id,
        "department_id": f.department_id, "patient_id": f.patient_id, "visit_id": f.visit_id,
        "owner_type": f.owner_type, "owner_id": f.owner_id, "description": f.description,
        "annotations": f.annotations or [], "center_wide": f.center_wide, "uploaded_by": f.author_name,
        "created_at": iso(f.created_at), "version": f.version,
        "is_image": f.mime_type.startswith("image/"),
        "can_manage": can_manage(p, f) if p else None,
        "url": f"/api/v1/files/{f.id}/content",
    }
