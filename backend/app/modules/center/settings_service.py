"""Center settings, branding/logo, storage usage, plan limits + usage."""
from sqlalchemy import func, select

from backend.app.core.api import check_version
from backend.app.core.errors import ValidationError
from backend.app.core.storage import get_storage
from backend.app.core.timeutil import iso
from backend.app.core.validation import COLOR_RE, PHONE_RE, Int, Str, validate
from backend.app.extensions import db
from backend.app.models import HealthCenter, StoredFile
from backend.app.services import accounts, files as file_service
from backend.app.services.centers import LIMIT_FIELDS

from .common import is_center_level

LOGO_EXTS = ("png", "jpg", "jpeg", "webp")
LOGO_MAX_BYTES = 2 * 1024 * 1024


def _require_center_edit(p):
    p.require_center_manager()
    p.require("settings.edit")


def _center(p):
    return db.session.get(HealthCenter, p.center_id)


def settings_json(c, p=None):
    from backend.app.modules.admin.serializers import effective_status
    return {"id": c.id, "name": c.name, "slug": c.slug, "status": effective_status(c),
            "trial_ends_at": iso(c.trial_ends_at), "subscription_ends_at": iso(c.subscription_ends_at),
            "currency": c.currency, "primary_color": c.primary_color, "secondary_color": c.secondary_color,
            "login_message": c.login_message, "document_footer": c.document_footer, "address": c.address,
            "phone": c.phone, "logo_url": "/api/v1/branding/logo" if c.logo_file_id else None,
            "logo_file_id": c.logo_file_id, "version": c.version,
            "can_edit": bool(p and is_center_level(p) and p.has("settings.edit"))}


def get_settings(p):
    p.require("settings.view")
    return settings_json(_center(p), p)


def update_settings(p, body):
    _require_center_edit(p)
    c = _center(p)
    data = validate(body, {
        "name": Str(max_len=200, nullable=False), "currency": Str(max_len=10, pattern=r"[A-Za-z]{2,10}", nullable=False),
        "primary_color": Str(pattern=COLOR_RE), "secondary_color": Str(pattern=COLOR_RE),
        "address": Str(max_len=300), "phone": Str(max_len=40, pattern=PHONE_RE),
        "document_footer": Str(max_len=500), "login_message": Str(max_len=300), "version": Int()}, partial=True)
    check_version(c, data.pop("version", None))
    for k in ("name", "currency"):
        if k in data and not data[k]:
            raise ValidationError("Invalid input", details={k: "is required"})
    if "currency" in data:
        data["currency"] = data["currency"].upper()
    for k, v in data.items():
        setattr(c, k, v)
    db.session.commit()
    return settings_json(c, p)


def upload_logo(p, upload):
    _require_center_edit(p)
    if upload is None or not upload.filename:
        raise ValidationError("No file was uploaded.", code="no_files")
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in LOGO_EXTS:
        raise ValidationError("The logo must be a PNG, JPEG or WebP image.", code="file_type_not_allowed")
    head = upload.stream.read(LOGO_MAX_BYTES + 1)
    if len(head) > LOGO_MAX_BYTES:
        raise ValidationError("The logo must be 2 MB or smaller.", code="file_too_large")
    upload.stream.seek(0)
    rows = file_service.store_upload(p, [upload], category="branding", center_wide=True, owner_type="center_logo",
                                     owner_id=p.center_id, description="Health center logo", commit=False)
    c = _center(p)
    old_id = c.logo_file_id
    c.logo_file_id = rows[0].id
    old_key = _drop_file(p, old_id)
    db.session.commit()
    _delete_bytes(old_key)
    return settings_json(c, p)


def _delete_bytes(key):
    if not key:
        return
    try:
        get_storage().delete(key)
    except OSError:  # e.g. still open on Windows; `flask ops storage-gc` removes orphans later
        pass


def _drop_file(p, file_id):
    if not file_id:
        return None
    f = db.session.execute(select(StoredFile).where(StoredFile.id == file_id, p.tenant(StoredFile))
                           ).scalar_one_or_none()
    if f is None:
        return None
    key = f.storage_key
    db.session.delete(f)
    return key


def remove_logo(p):
    _require_center_edit(p)
    c = _center(p)
    key = _drop_file(p, c.logo_file_id)
    c.logo_file_id = None
    db.session.commit()
    _delete_bytes(key)
    return settings_json(c, p)


def storage(p):
    p.require("settings.view")
    out = file_service.storage_usage(p.center_id)
    rows = db.session.execute(select(StoredFile.category, func.count(), func.coalesce(func.sum(StoredFile.size_bytes), 0))
                              .where(p.tenant(StoredFile)).group_by(StoredFile.category)).all()
    out["by_category"] = [{"category": c, "count": n, "bytes": int(b)} for c, n, b in rows]
    q = out["quota_bytes"]
    out["percent_used"] = round(100.0 * out["used_bytes"] / q, 1) if q else 0.0
    return out


def limits(p):
    p.require("settings.view")
    c = _center(p)
    from backend.app.modules.admin.serializers import effective_status
    use = accounts.usage(c.id)
    return {"plan": {"id": c.plan.id, "code": c.plan.code, "name": c.plan.name} if c.plan else None,
            "status": effective_status(c), "trial_ends_at": iso(c.trial_ends_at),
            "subscription_ends_at": iso(c.subscription_ends_at),
            "limits": [{"key": k, "label": accounts.LIMIT_LABELS[k], "max": getattr(c, k), "used": use[k],
                        "remaining": None if getattr(c, k) is None else max(0, getattr(c, k) - use[k])}
                       for k in LIMIT_FIELDS],
            "storage": file_service.storage_usage(c.id)}
