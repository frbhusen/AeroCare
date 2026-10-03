"""/api/v1 — health check, notifications, undo of staged deletions, branding logo."""
from flask import Blueprint, jsonify, send_file
from sqlalchemy import func, select, update

from backend.app.authz.decorators import login_required, public, authenticated
from backend.app.authz.principal import current_principal
from backend.app.core.api import paginate
from backend.app.core.errors import NotFound
from backend.app.core.storage import get_storage
from backend.app.core.timeutil import iso
from backend.app.core.validation import Str, request_json, validate
from backend.app.extensions import db
from backend.app.models import HealthCenter, Notification, StoredFile
from backend.app.services import deletion

bp = Blueprint("common", __name__)


@bp.get("/health")
@public
def health():
    db.session.execute(select(1))
    return jsonify({"status": "ok"})


def _notif(n):
    return {"id": n.id, "type": n.type, "title": n.title, "body": n.body, "link": n.link, "is_read": n.is_read,
            "created_at": iso(n.created_at)}


@bp.get("/notifications")
@login_required
def list_notifications():
    p = current_principal()
    stmt = (select(Notification).where(p.tenant(Notification), Notification.user_id == p.user.id)
            .order_by(Notification.created_at.desc()))
    out = paginate(db.session, stmt, _notif, default_per_page=20)
    out["unread"] = db.session.execute(select(func.count()).select_from(Notification).where(
        p.tenant(Notification), Notification.user_id == p.user.id, Notification.is_read.is_(False))).scalar_one()
    return jsonify(out)


@bp.post("/notifications/read")
@login_required
def mark_read():
    p = current_principal()
    ids = (request_json().get("ids") or [])
    stmt = update(Notification).where(p.tenant(Notification), Notification.user_id == p.user.id)
    if ids:
        stmt = stmt.where(Notification.id.in_([int(i) for i in ids if str(i).isdigit()][:500]))
    db.session.execute(stmt.values(is_read=True))
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/undo")
@login_required
def undo():
    data = validate(request_json(), {"undo_token": Str(required=True, max_len=64)})
    return jsonify(deletion.undo(current_principal(), data["undo_token"]))


@bp.get("/branding/logo")
@authenticated
def center_logo():
    p = current_principal()
    if not p.center_id:
        raise NotFound("No logo")
    c = db.session.get(HealthCenter, p.center_id)
    f = db.session.get(StoredFile, c.logo_file_id) if c.logo_file_id else None
    if f is None or f.health_center_id != p.center_id or f.pending_delete_until is not None:
        raise NotFound("No logo")
    return send_file(get_storage().path(f.storage_key), mimetype=f.mime_type, max_age=300)
