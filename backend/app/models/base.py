"""Model mixins and helpers used by every tenant-scoped table.

Rules (see docs/DATABASE.md):
* Every tenant-scoped table has `health_center_id` NOT NULL (TenantMixin). RLS policies are
  generated automatically for any table with that column.
* Each tenant table exposes UNIQUE(health_center_id, id) so children can use composite FKs
  `tenant_fk(...)` that make cross-tenant relationships impossible at the database level.
* Mutable records use `VersionMixin` (optimistic locking via SQLAlchemy version_id_col).
* Entities supporting delete+undo use `UndoDeleteMixin` (see core/deletion.py).
"""
from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, UniqueConstraint
from sqlalchemy.orm import declared_attr

from backend.app.core.timeutil import utcnow
from backend.app.extensions import db


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TenantMixin:
    @declared_attr
    def health_center_id(cls):
        return Column(Integer, ForeignKey("health_centers.id", ondelete="CASCADE"), nullable=False, index=True)


class VersionMixin:
    version = Column(Integer, nullable=False, default=1)

    @declared_attr
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


class UndoDeleteMixin:
    """Row is hidden from all normal queries while `pending_delete_until` is set.
    The purger permanently deletes it after the undo window."""
    pending_delete_until = Column(DateTime(timezone=True), nullable=True, index=True)

    @classmethod
    def live(cls):
        return cls.pending_delete_until.is_(None)


def tenant_unique(table):
    return UniqueConstraint("health_center_id", "id", name=f"uq_{table}_tenant_id")


def tenant_fk(col, ref_table, ondelete="RESTRICT", name=None, **kw):
    """Composite FK (health_center_id, col) -> ref_table(health_center_id, id).
    MATCH SIMPLE: a NULL `col` is allowed (optional reference).
    ondelete="SET NULL" is rewritten to PostgreSQL's column-list form `SET NULL (col)` so the
    NOT NULL health_center_id is never nulled by the FK action."""
    if ondelete and ondelete.upper() == "SET NULL":
        ondelete = f"SET NULL ({col})"
    return ForeignKeyConstraint(
        ["health_center_id", col], [f"{ref_table}.health_center_id", f"{ref_table}.id"],
        ondelete=ondelete, name=name or f"fk_{col}_{ref_table}_tenant", **kw,
    )


class AuthorSnapshotMixin:
    """Historical author: the user id plus immutable name/role snapshots taken at creation.
    Renaming or reassigning a user never rewrites these (spec §11, §101)."""
    author_user_id = Column(Integer, nullable=True, index=True)
    author_name = Column(db.String(200), nullable=False, default="")
    author_role = Column(db.String(40), nullable=True)

    def set_author(self, user):
        self.author_user_id = user.id
        self.author_name = user.name
        self.author_role = user.role
