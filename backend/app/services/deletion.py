"""Server-authoritative delete with a 30-second undo window (spec §25, §102).

    token = deletion.stage(principal, obj, "patient", label="PAT-000012 Ali")   # row hidden now
    deletion.undo(principal, token)                                              # restores
    deletion.purge_expired()                                                     # hard delete after window

Rows are hidden by `pending_delete_until IS NOT NULL` (UndoDeleteMixin.live()). Every list/get
query on such a model MUST filter `Model.live()`. Hard deletion cascades through FKs; stored file
bytes of cascaded files are removed by the purger.

Register each deletable type once (modules do this at import time):
    deletion.register("patient", Patient, files=lambda obj: StoredFile.patient_id == obj.id)
"""
import logging
import secrets
import threading
import time
from datetime import timedelta

from flask import current_app
from sqlalchemy import select

from backend.app.core import tenancy
from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.extensions import db
from backend.app.models import DeletionStage, StoredFile

log = logging.getLogger("hc.deletion")
_REGISTRY = {}


def register(entity_type, model, files=None, before_purge=None):
    """files: callable(obj) -> SQL clause selecting StoredFile rows whose bytes must be removed
    when obj is purged (files cascade-deleted with it). before_purge: callable(obj) hook."""
    _REGISTRY[entity_type] = {"model": model, "files": files, "before_purge": before_purge}


def stage(principal, obj, entity_type, label=None):
    if entity_type not in _REGISTRY:
        raise RuntimeError(f"unregistered deletable type {entity_type}")
    if obj.pending_delete_until is not None:
        raise NotFound("Not found")
    window = current_app.config["UNDO_WINDOW_SECONDS"]
    expires = utcnow() + timedelta(seconds=window)
    obj.pending_delete_until = expires
    token = secrets.token_urlsafe(24)
    db.session.add(DeletionStage(health_center_id=obj.health_center_id, token=token, entity_type=entity_type,
                                 entity_id=obj.id, label=(label or "")[:255], user_id=principal.user.id,
                                 expires_at=expires))
    db.session.commit()
    return {"undo_token": token, "undo_expires_at": iso(expires), "undo_seconds": window}


def undo(principal, token):
    st = db.session.execute(select(DeletionStage).where(DeletionStage.token == token,
                                                        DeletionStage.health_center_id == principal.center_id)
                            ).scalar_one_or_none()
    if st is None or st.user_id != principal.user.id:
        raise NotFound("Nothing to undo")
    if st.expires_at <= utcnow():
        raise ValidationError("The undo window has expired.", code="undo_expired")
    entry = _REGISTRY[st.entity_type]
    obj = db.session.get(entry["model"], st.entity_id)
    if obj is not None:
        obj.pending_delete_until = None
    db.session.delete(st)
    db.session.commit()
    return {"restored": True, "entity_type": st.entity_type, "entity_id": st.entity_id}


def purge_expired(limit=200):
    """Hard-delete staged rows whose window passed. Runs in platform DB mode."""
    from backend.app.core.storage import get_storage
    purged = 0
    with tenancy.scoped("platform"):
        stages = db.session.execute(select(DeletionStage).where(DeletionStage.expires_at <= utcnow())
                                    .order_by(DeletionStage.expires_at).limit(limit)
                                    .with_for_update(skip_locked=True)).scalars().all()
        for st in stages:
            entry = _REGISTRY.get(st.entity_type)
            keys = []
            if entry:
                obj = db.session.get(entry["model"], st.entity_id)
                if obj is not None and obj.pending_delete_until is not None:
                    if entry["before_purge"]:
                        entry["before_purge"](obj)
                    if entry["files"]:
                        keys = list(db.session.execute(select(StoredFile.storage_key).where(entry["files"](obj))
                                                       ).scalars())
                    db.session.delete(obj)
            db.session.delete(st)
            db.session.flush()
            db.session.commit()
            storage = get_storage()
            for k in keys:
                try:
                    storage.delete(k)
                except Exception:
                    log.exception("failed to delete stored bytes for purged entity %s", st.entity_type)
            purged += 1
    return purged


def start_background_purger(app, interval=10):
    """One lightweight daemon thread per worker; FOR UPDATE SKIP LOCKED makes concurrent
    purgers safe. Rows are already invisible during the window, so timing is not critical."""
    def loop():
        while True:
            time.sleep(interval)
            try:
                with app.app_context():
                    purge_expired()
                    db.session.remove()
            except Exception:
                log.exception("background purge failed")

    t = threading.Thread(target=loop, name="hc-purger", daemon=True)
    t.start()
    return t
