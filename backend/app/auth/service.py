"""Authentication: password hashing, server-side single sessions, CSRF, login rate limiting,
per-request principal loading."""
import hashlib
import secrets
from datetime import timedelta

from flask import current_app, g, request
from sqlalchemy import func, select, update
from werkzeug.security import check_password_hash, generate_password_hash

from backend.app.core import tenancy
from backend.app.core.errors import Forbidden, TooManyRequests, Unauthorized
from backend.app.core.timeutil import utcnow
from backend.app.extensions import db
from backend.app.models import HealthCenter, LoginAttempt, User, UserSession

PASSWORD_METHOD = "scrypt"
MIN_PASSWORD_LEN = 8


def hash_password(raw: str) -> str:
    method = PASSWORD_METHOD
    try:
        method = current_app.config.get("PASSWORD_HASH_METHOD") or PASSWORD_METHOD
    except RuntimeError:
        pass
    return generate_password_hash(raw, method=method)


def verify_password(hashed: str, raw: str) -> bool:
    return check_password_hash(hashed, raw)


def validate_password(raw):
    from backend.app.core.errors import ValidationError
    if not isinstance(raw, str) or len(raw) < MIN_PASSWORD_LEN or len(raw) > 200:
        raise ValidationError("Invalid password", details={"password": f"must be {MIN_PASSWORD_LEN}-200 characters"})
    return raw


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip():
    # Behind Nginx, ProxyFix (configured in create_app) makes remote_addr the real client IP.
    return (request.remote_addr or "")[:64]


# ---------------------------------------------------------------- rate limiting
def check_rate_limit(email):
    window = utcnow() - timedelta(seconds=current_app.config["LOGIN_RATE_WINDOW_SECONDS"])
    limit = current_app.config["LOGIN_RATE_LIMIT"]
    fails = db.session.execute(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.success.is_(False), LoginAttempt.attempted_at >= window,
            (LoginAttempt.email == email) | (LoginAttempt.ip == client_ip()))).scalar_one()
    if fails >= limit:
        raise TooManyRequests("Too many failed login attempts. Try again later.")


def record_attempt(email, success):
    db.session.add(LoginAttempt(email=email[:255], ip=client_ip(), success=success))


# ---------------------------------------------------------------- center status
def center_access_state(center: HealthCenter):
    """Returns the effective status, lazily moving expired trials/subscriptions to 'expired'."""
    now = utcnow()
    if center.status == "trial" and center.trial_ends_at and center.trial_ends_at < now:
        center.status = "expired"
    elif center.status == "active" and center.subscription_ends_at and center.subscription_ends_at < now:
        center.status = "expired"
    return center.status


# ---------------------------------------------------------------- sessions
def authenticate(email: str, password: str):
    """Returns the user or raises Unauthorized. Runs in 'auth' DB mode (users readable for login)."""
    from backend.app.services import audit
    email = (email or "").strip().lower()
    with tenancy.scoped("auth"):
        check_rate_limit(email)
        user = db.session.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
        ok = bool(user and user.status == "active" and verify_password(user.password_hash, password or ""))
        record_attempt(email, ok)
        audit.log_login(user, email, ok)
        if not ok:
            db.session.commit()
            raise Unauthorized("Invalid email or password.", code="invalid_credentials")
        if user.role != "superadmin":
            center = db.session.get(HealthCenter, user.health_center_id)
            state = center_access_state(center)
            if state in ("expired", "suspended"):
                db.session.commit()
                raise Forbidden("This health center's subscription is not active. Contact the platform administrator.",
                                code="center_inactive")
        return user


def create_session(user):
    """Create a new session and revoke every other session of the user (single active session)."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with tenancy.scoped("auth"):
        db.session.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                           .values(revoked_at=now, revoked_reason="new_login"))
        sess = UserSession(token_hash=_hash_token(token), csrf_token=secrets.token_urlsafe(32), user_id=user.id,
                           ip=client_ip(), user_agent=(request.user_agent.string or "")[:300])
        db.session.add(sess)
        user.last_login_at = now
        db.session.commit()
    return token, sess


def set_session_cookie(response, token):
    cfg = current_app.config
    response.set_cookie(cfg["SESSION_COOKIE_NAME"], token, max_age=cfg["SESSION_MAX_AGE_DAYS"] * 86400,
                        httponly=True, secure=cfg["SESSION_COOKIE_SECURE"], samesite=cfg["SESSION_COOKIE_SAMESITE"],
                        path="/")


def clear_session_cookie(response):
    cfg = current_app.config
    response.delete_cookie(cfg["SESSION_COOKIE_NAME"], path="/", httponly=True, secure=cfg["SESSION_COOKIE_SECURE"],
                           samesite=cfg["SESSION_COOKIE_SAMESITE"])


def revoke_session(sess, reason="logout"):
    with tenancy.scoped("auth"):
        sess.revoked_at = utcnow()
        sess.revoked_reason = reason
        db.session.commit()


def revoke_user_sessions(user_id, reason):
    with tenancy.scoped("auth"):
        db.session.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                           .values(revoked_at=utcnow(), revoked_reason=reason))


def load_request_principal(token=None):
    """Resolve cookie -> session -> user -> principal, then set the DB tenant context.
    Sets g.principal = None when unauthenticated; g.session_revoked_reason when the session
    was replaced by a newer login (lets the UI explain the logout)."""
    from backend.app.authz.principal import build_principal
    g.principal = None
    g.auth_error = None
    token = token or request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
    if not token:
        return
    tenancy.use_auth()
    sess = db.session.execute(select(UserSession).where(UserSession.token_hash == _hash_token(token))
                              ).scalar_one_or_none()
    if sess is None:
        tenancy.clear()
        return
    if sess.revoked_at is not None:
        g.auth_error = "session_replaced" if sess.revoked_reason == "new_login" else "session_ended"
        tenancy.clear()
        return
    user = db.session.get(User, sess.user_id)
    if user is None or user.status != "active":
        g.auth_error = "account_inactive"
        tenancy.clear()
        return
    now = utcnow()
    if (now - sess.last_seen_at).total_seconds() > 300:
        sess.last_seen_at = now  # coarse touch, no inactivity logout
    center_id = sess.acting_center_id if user.role == "superadmin" else user.health_center_id
    if center_id:
        center = db.session.get(HealthCenter, center_id)
        if center is None:
            tenancy.clear()
            return
        if user.role != "superadmin" and center_access_state(center) in ("expired", "suspended"):
            g.auth_error = "center_inactive"
            db.session.commit()
            tenancy.clear()
            return
        db.session.commit()
        tenancy.use_tenant(center_id)
    else:
        db.session.commit()
        tenancy.use_platform()  # superadmin in platform portal
    g.principal = build_principal(user, sess, acting_center_id=sess.acting_center_id)
    g.csrf_token = sess.csrf_token
