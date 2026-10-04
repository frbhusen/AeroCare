"""Clinical favorites: reusable note snippets, favorite diagnoses, prescription sets and procedures
with default prices. Center-wide (department_id NULL) or per department."""
from sqlalchemy import CheckConstraint, Column, Index, Integer, JSON, String, Text

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin, VersionMixin,
                                     tenant_fk, tenant_unique)

KINDS = ("snippet", "diagnosis", "rx_set", "procedure")


class ClinicalFavorite(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    __tablename__ = "clinical_favorites"
    __table_args__ = (
        tenant_unique("clinical_favorites"),
        CheckConstraint("kind IN ('snippet','diagnosis','rx_set','procedure')", name="kind"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_fav_department"),
        Index("ix_fav_lookup", "health_center_id", "kind", "department_id"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer)  # NULL = whole center
    kind = Column(String(20), nullable=False)
    field = Column(String(60))  # snippets: target form field (e.g. "examination"); NULL = any field
    title = Column(String(200), nullable=False)
    body = Column(Text)  # snippet / diagnosis text
    payload = Column(JSON, nullable=False, default=dict)  # rx_set: {"items": [...]}; procedure: {"price", "code"}
    sort_order = Column(Integer, nullable=False, default=100)
