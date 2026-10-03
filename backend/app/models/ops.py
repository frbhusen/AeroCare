"""Cross-cutting operational tables: audit log, notifications, offline sync idempotency,
staged deletions (30-second undo)."""
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String,
                        Text, UniqueConstraint, func)

from backend.app.extensions import db
from .base import TenantMixin

AUDIT_CATEGORIES = ("login", "department", "clinic", "user")


class AuditLog(db.Model):
    """Immutable (UPDATE/DELETE blocked by trigger + privileges). Only the categories in
    AUDIT_CATEGORIES are logged; never medical or financial content."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("category IN ('login','department','clinic','user')", name="category"),
        Index("ix_audit_center_at", "health_center_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    health_center_id = Column(Integer, ForeignKey("health_centers.id", ondelete="SET NULL"), index=True)
    department_id = Column(Integer, index=True)
    category = Column(String(20), nullable=False)
    action = Column(String(40), nullable=False)  # success, failure, create, edit, delete
    actor_user_id = Column(Integer)
    actor_name = Column(String(200))
    actor_role = Column(String(30))
    target_type = Column(String(40))
    target_id = Column(Integer)
    target_label = Column(String(255))
    details = Column(JSON)  # field names changed etc. Never medical/financial content.
    ip = Column(String(64))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Notification(db.Model, TenantMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "is_read", "created_at"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(String(500))
    link = Column(String(255))
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SyncOperation(db.Model, TenantMixin):
    """Idempotency record for mutations carrying an `X-Op-Id` header (offline queue replays).
    The stored response is replayed for duplicates, so retries never duplicate data."""
    __tablename__ = "offline_sync_operations"
    __table_args__ = (UniqueConstraint("user_id", "op_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    op_id = Column(String(64), nullable=False)
    method = Column(String(10), nullable=False)
    path = Column(String(300), nullable=False)
    status_code = Column(Integer)
    response = Column(JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DeletionStage(db.Model, TenantMixin):
    """Server-authoritative undo buffer. The entity row is flagged (pending_delete_until) and
    hidden; after expires_at the purger hard-deletes it. Undo clears the flag."""
    __tablename__ = "deletion_buffer"
    __table_args__ = (Index("ix_deletion_expires", "expires_at"),)
    id = Column(Integer, primary_key=True)
    token = Column(String(64), nullable=False, unique=True)
    entity_type = Column(String(60), nullable=False)
    entity_id = Column(Integer, nullable=False)
    label = Column(String(255))
    user_id = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
