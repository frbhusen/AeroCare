"""Uploaded files and explicit sharing. Bytes live in the storage backend (core/storage.py),
never under a public URL; every download goes through an authorized endpoint."""
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, JSON, String, Text, func

from backend.app.extensions import db
from .base import AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin, VersionMixin, tenant_fk, tenant_unique

FILE_CATEGORIES = ("xray", "photo", "medical_image", "document", "lab_report", "radiology_image",
                   "radiology_report", "branding", "other")


class StoredFile(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    __tablename__ = "files"
    __table_args__ = (
        tenant_unique("files"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_file_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_file_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_file_department"),
        tenant_fk("visit_id", "visits", ondelete="SET NULL", name="fk_file_visit"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 15728640", name="size"),
        Index("ix_files_patient_clinic", "health_center_id", "patient_id", "clinic_id"),
        Index("ix_files_owner", "health_center_id", "owner_type", "owner_id"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer)  # owning department (NULL for center-level files e.g. logo)
    clinic_id = Column(Integer)  # owning clinic (normal files are visible to this clinic only)
    patient_id = Column(Integer)
    visit_id = Column(Integer)
    category = Column(String(30), nullable=False, default="document")
    owner_type = Column(String(40))  # e.g. 'dental_xray', 'laser_session', 'radiology_study', 'lab_request'
    owner_id = Column(Integer)
    original_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    storage_key = Column(String(300), nullable=False, unique=True)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    annotations = Column(JSON)  # basic image annotations [{type, points, text, color}]
    description = Column(Text)
    center_wide = Column(db.Boolean, nullable=False, default=False)  # e.g. finalized lab reports, branding


class FileShare(db.Model, TenantMixin):
    """Explicit share to exactly one target: department, clinic or user. Revocable (delete row)."""
    __tablename__ = "file_shares"
    __table_args__ = (
        tenant_unique("file_shares"),
        CheckConstraint("(CASE WHEN target_department_id IS NOT NULL THEN 1 ELSE 0 END"
                        " + CASE WHEN target_clinic_id IS NOT NULL THEN 1 ELSE 0 END"
                        " + CASE WHEN target_user_id IS NOT NULL THEN 1 ELSE 0 END) = 1", name="one_target"),
        tenant_fk("file_id", "files", ondelete="CASCADE", name="fk_share_file"),
        tenant_fk("target_department_id", "health_center_departments", ondelete="CASCADE", name="fk_share_dept"),
        tenant_fk("target_clinic_id", "clinics", ondelete="CASCADE", name="fk_share_clinic"),
        tenant_fk("target_user_id", "users", ondelete="CASCADE", name="fk_share_user"),
    )
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, nullable=False, index=True)
    target_department_id = Column(Integer)
    target_clinic_id = Column(Integer)
    target_user_id = Column(Integer)
    shared_by = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
