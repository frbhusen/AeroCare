"""Route decorators. Every protected endpoint uses one of these; they only establish identity
and coarse role/permission. Object-level scope checks happen in services via
`current_principal().require(..., clinic_id=...)`."""
from functools import wraps

from flask import g

from backend.app.core.errors import Forbidden, Unauthorized


def _need_principal():
    p = getattr(g, "principal", None)
    if p is None:
        code = getattr(g, "auth_error", None) or "unauthorized"
        msg = {
            "session_replaced": "You were signed out because your account signed in on another device.",
            "center_inactive": "This health center's subscription is not active.",
            "account_inactive": "This account is archived.",
        }.get(code, "Authentication required")
        raise Unauthorized(msg, code=code)
    return p


def login_required(fn=None, *, perm=None):
    """Any authenticated principal *inside a health center* (staff or superadmin support mode)."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            p = _need_principal()
            if not p.center_id:
                raise Forbidden("This action requires a health center context.", code="no_center_context")
            if perm:
                p.require(perm)
            return f(*a, **kw)
        wrapper._auth = "center"
        return wrapper
    return deco(fn) if fn else deco


def superadmin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        p = _need_principal()
        if not p.is_superadmin:
            raise Forbidden("Superadmin access required.")
        return f(*a, **kw)
    wrapper._auth = "superadmin"
    return wrapper


def authenticated(f):
    """Any authenticated principal, with or without center context (e.g. /auth/me)."""
    @wraps(f)
    def wrapper(*a, **kw):
        _need_principal()
        return f(*a, **kw)
    wrapper._auth = "any"
    return wrapper


def public(f):
    """Explicitly public endpoint (login, health check). Lets the route audit test verify
    that every other endpoint is protected."""
    f._auth = "public"
    return f
