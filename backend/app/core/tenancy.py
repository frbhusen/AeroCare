"""Database tenant context (defense-in-depth layer under the application policy checks).

Every transaction sets three transaction-local PostgreSQL settings that Row Level Security
policies read (see backend/app/schema/rls.py):

    app.mode       'tenant' | 'platform' | 'auth' | '' (unset => fail closed: no tenant rows)
    app.center_id  health center id when mode == 'tenant'

The context is a ContextVar so it works in requests, CLI commands and background threads.
Request code never sets it directly: the auth layer calls `use_tenant()` / `use_platform()`
after resolving the authenticated principal. Client input is never used to choose the tenant.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.orm import Session

_ctx: ContextVar[tuple] = ContextVar("hc_db_ctx", default=("", None))

MODES = {"tenant", "platform", "auth", ""}


def current():
    """Return (mode, center_id)."""
    return _ctx.get()


def current_center_id():
    mode, cid = _ctx.get()
    return cid if mode == "tenant" else None


def _set(mode, center_id=None):
    assert mode in MODES
    if mode == "tenant":
        if not isinstance(center_id, int) or center_id <= 0:
            raise RuntimeError("tenant context requires a valid health center id")
    _ctx.set((mode, center_id))
    _apply_to_open_transaction()


def use_tenant(center_id: int):
    _set("tenant", center_id)


def use_platform():
    _set("platform")


def use_auth():
    _set("auth")


def clear():
    _set("")


@contextmanager
def scoped(mode, center_id=None):
    token = _ctx.set((mode, center_id))
    _apply_to_open_transaction()
    try:
        yield
    finally:
        _ctx.reset(token)
        _apply_to_open_transaction()


def _apply(conn):
    mode, cid = _ctx.get()
    conn.execute(
        text("SELECT set_config('app.mode', :m, true), set_config('app.center_id', :c, true)"),
        {"m": mode, "c": str(cid) if cid else ""},
    )


def _apply_to_open_transaction():
    # If a transaction is already open in the current scoped session, refresh its settings.
    try:
        from backend.app.extensions import db
        sess = db.session()
        if sess.in_transaction():
            _apply(sess.connection())
    except RuntimeError:
        pass  # no app context


@event.listens_for(Session, "after_begin")
def _after_begin(session, transaction, connection):
    _apply(connection)
