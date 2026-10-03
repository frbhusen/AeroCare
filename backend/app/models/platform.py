"""Platform-level (non-tenant) and tenant-root models."""
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, JSON,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import relationship

from backend.app.extensions import db
from .base import TimestampMixin, VersionMixin

CENTER_STATUSES = ("trial", "active", "expired", "suspended")
# Module "environments" implemented in code. Every department type maps to one of them.
ENVIRONMENTS = ("dentistry", "dermatology", "ophthalmology", "radiology", "laboratory", "pharmacy", "generic")


class Plan(db.Model, TimestampMixin):
    """Plan templates. Limits are copied onto the center (center columns are authoritative)
    so the Superadmin can override any limit per center. NULL limit == unlimited."""
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    max_departments = Column(Integer)
    max_head_doctors = Column(Integer)
    max_doctors = Column(Integer)
    max_receptionists = Column(Integer)
    max_clinics = Column(Integer)
    storage_quota_bytes = Column(BigInteger)
    is_active = Column(Boolean, nullable=False, default=True)


class DepartmentType(db.Model, TimestampMixin):
    """Platform catalog of specialties. Only the Superadmin creates these."""
    __tablename__ = "department_types"
    __table_args__ = (CheckConstraint("environment IN ('dentistry','dermatology','ophthalmology','radiology',"
                                      "'laboratory','pharmacy','generic')", name="environment"),)
    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)
    name_en = Column(String(100), nullable=False)
    name_ar = Column(String(100), nullable=False)
    environment = Column(String(30), nullable=False, default="generic")
    is_custom = Column(Boolean, nullable=False, default=False)
    icon = Column(String(50))
    color = Column(String(7))
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=100)


class HealthCenter(db.Model, TimestampMixin, VersionMixin):
    """Tenant root. RLS policy on this table uses `id` instead of health_center_id."""
    __tablename__ = "health_centers"
    __table_args__ = (
        CheckConstraint("status IN ('trial','active','expired','suspended')", name="status"),
        CheckConstraint("storage_used_bytes >= 0", name="storage_used_nonneg"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(80), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="trial")
    trial_ends_at = Column(DateTime(timezone=True))
    subscription_ends_at = Column(DateTime(timezone=True))
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"))
    # Effective limits (copied from plan, editable by Superadmin). NULL = unlimited.
    max_departments = Column(Integer)
    max_head_doctors = Column(Integer)
    max_doctors = Column(Integer)
    max_receptionists = Column(Integer)
    max_clinics = Column(Integer)
    storage_quota_bytes = Column(BigInteger, nullable=False)
    storage_used_bytes = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(10), nullable=False, default="SYP")
    # Branding
    logo_file_id = Column(Integer)  # files.id (no FK to avoid cycle; validated in service)
    primary_color = Column(String(7), default="#0f766e")
    secondary_color = Column(String(7), default="#0ea5e9")
    login_message = Column(String(300))
    document_footer = Column(String(500))
    address = Column(String(300))
    phone = Column(String(40))
    # Concurrency-safe per-center sequences (UPDATE ... RETURNING takes a row lock).
    patient_seq = Column(Integer, nullable=False, default=0)
    invoice_seq = Column(Integer, nullable=False, default=0)
    notes = Column(Text)

    plan = relationship("Plan")


class HealthCenterModule(db.Model, TimestampMixin):
    """Which department types the Superadmin activated for a center."""
    __tablename__ = "health_center_modules"
    __table_args__ = (UniqueConstraint("health_center_id", "department_type_id"),)
    id = Column(Integer, primary_key=True)
    health_center_id = Column(Integer, ForeignKey("health_centers.id", ondelete="CASCADE"), nullable=False, index=True)
    department_type_id = Column(Integer, ForeignKey("department_types.id", ondelete="RESTRICT"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class PlatformSetting(db.Model, TimestampMixin):
    __tablename__ = "platform_settings"
    key = Column(String(80), primary_key=True)
    value = Column(JSON)
