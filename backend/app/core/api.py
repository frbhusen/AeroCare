"""Response conventions shared by every blueprint.

Success:     200/201 with the resource object, or {"items": [...], "page": n, "per_page": n, "total": n}
Delete:      202 {"undo_token": "...", "undo_expires_at": iso}   (see core/deletion.py)
Errors:      see core/errors.py
"""
from flask import jsonify, request
from sqlalchemy import func, select

from .errors import Conflict, ValidationError

MAX_PER_PAGE = 100


def ok(data=None, status=200):
    return jsonify(data if data is not None else {"ok": True}), status


def created(data):
    return jsonify(data), 201


def page_params(default_per_page=25):
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(MAX_PER_PAGE, max(1, int(request.args.get("per_page", default_per_page))))
    except ValueError:
        raise ValidationError("page and per_page must be integers")
    return page, per_page


def paginate(session, stmt, serialize, default_per_page=25, count=True):
    """Execute a bounded, paginated select. `stmt` must already be tenant/scope filtered."""
    page, per_page = page_params(default_per_page)
    rows = session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).scalars().all()
    total = None
    if count:
        total = session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    return {"items": [serialize(r) for r in rows], "page": page, "per_page": per_page, "total": total}


def check_version(obj, expected):
    """Optimistic locking: clients send the `version` they edited. Mismatch -> 409 with server copy."""
    if expected is None:
        raise ValidationError("version is required for updates", details={"version": "is required"})
    if int(expected) != obj.version:
        raise Conflict("This record was changed by someone else.", code="version_conflict",
                       details={"current_version": obj.version})
