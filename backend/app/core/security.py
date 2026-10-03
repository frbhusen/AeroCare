"""Request-level security: CSRF, security headers, idempotent replays for offline sync."""
import json
import re

from flask import current_app, g, request
from sqlalchemy import select

from .errors import Forbidden, error_body

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT = {"/api/v1/auth/login"}
OP_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def csrf_check():
    """Double defence for state-changing API calls: same-origin Origin/Referer AND the
    session-bound CSRF token in the X-CSRF-Token header."""
    if request.method not in MUTATING or not request.path.startswith("/api/"):
        return
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if origin:
        host = request.host_url.rstrip("/")
        if not (origin == host or origin.startswith(host + "/")):
            raise Forbidden("Cross-origin request rejected.", code="csrf_origin")
    if request.path in CSRF_EXEMPT:
        return
    expected = getattr(g, "csrf_token", None)
    if expected is None:
        return  # unauthenticated: the endpoint will reject with 401
    if request.headers.get("X-CSRF-Token") != expected:
        raise Forbidden("Missing or invalid CSRF token.", code="csrf_token")


def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; font-src 'self' data:; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ---------------------------------------------------------------- idempotency (offline sync)
def idempotency_before():
    """Mutations carrying X-Op-Id are applied at most once per user.

    The op id is *claimed* (committed row, status_code NULL) before the handler runs, so two
    concurrent retries cannot both execute: the loser gets 409 op_in_progress and retries later,
    by which time the stored response is replayed (header X-Op-Replayed: 1)."""
    op_id = request.headers.get("X-Op-Id")
    g.op_claim_id = None
    if not op_id or request.method not in MUTATING or getattr(g, "principal", None) is None:
        return None
    if not OP_ID_RE.match(op_id):
        return error_body("validation_error", "Invalid X-Op-Id", status=422)
    p = g.principal
    if not p.center_id:
        return None
    from sqlalchemy.exc import IntegrityError
    from backend.app.extensions import db
    from backend.app.models import SyncOperation
    prev = db.session.execute(select(SyncOperation).where(SyncOperation.user_id == p.user.id,
                                                          SyncOperation.op_id == op_id)).scalar_one_or_none()
    if prev is None:
        claim = SyncOperation(health_center_id=p.center_id, user_id=p.user.id, op_id=op_id,
                              method=request.method, path=request.path[:300])
        db.session.add(claim)
        try:
            db.session.commit()
            g.op_claim_id = claim.id
            return None
        except IntegrityError:
            db.session.rollback()
            prev = db.session.execute(select(SyncOperation).where(SyncOperation.user_id == p.user.id,
                                                                  SyncOperation.op_id == op_id)).scalar_one_or_none()
    if prev is None or prev.status_code is None:
        return error_body("op_in_progress", "This operation is already being processed.", status=409)
    resp = current_app.response_class(json.dumps(prev.response), status=prev.status_code,
                                      mimetype="application/json")
    resp.headers["X-Op-Replayed"] = "1"
    return resp


def idempotency_after(resp):
    claim_id = getattr(g, "op_claim_id", None)
    if not claim_id:
        return resp
    from backend.app.extensions import db
    from backend.app.models import SyncOperation
    g.op_claim_id = None
    try:
        db.session.rollback()
        claim = db.session.get(SyncOperation, claim_id)
        if claim is not None:
            if resp.status_code >= 500 or resp.status_code in (401, 429):
                db.session.delete(claim)  # transient failure: allow a real retry
            else:
                claim.status_code = resp.status_code
                claim.response = resp.get_json(silent=True)
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("failed to finalize sync op %s", claim_id)
    return resp


def idempotency_teardown(exc):
    """Unhandled exception after claiming: release the claim so the client can retry."""
    claim_id = getattr(g, "op_claim_id", None)
    if not claim_id or exc is None:
        return
    from backend.app.extensions import db
    from backend.app.models import SyncOperation
    try:
        db.session.rollback()
        claim = db.session.get(SyncOperation, claim_id)
        if claim is not None and claim.status_code is None:
            db.session.delete(claim)
            db.session.commit()
    except Exception:
        db.session.rollback()
