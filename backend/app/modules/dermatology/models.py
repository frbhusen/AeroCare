"""Dermatology + Laser Hair Removal data (spec §34-37, §82-83).

Ownership: center + department + clinic + patient (+ visit). Author fields are historical snapshots.
"""
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin, VersionMixin,
                                     tenant_fk, tenant_unique)

SEVERITIES = ("mild", "moderate", "severe")


def _owner_fks(prefix):
    return (
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name=f"fk_{prefix}_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name=f"fk_{prefix}_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name=f"fk_{prefix}_clinic"),
        tenant_fk("visit_id", "visits", ondelete="CASCADE", name=f"fk_{prefix}_visit"),
        tenant_fk("author_user_id", "users", name=f"fk_{prefix}_author"),
    )


class DermVisitRecord(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """Dermatology detail of one visit (one-to-one with visits)."""
    __tablename__ = "derm_visit_records"
    __table_args__ = (
        tenant_unique("derm_visit_records"),
        UniqueConstraint("visit_id", name="uq_derm_visit_records_visit"),
        CheckConstraint("severity IS NULL OR severity IN ('mild','moderate','severe')", name="severity"),
        *_owner_fks("derm"),
        Index("ix_derm_records_clinic_patient", "health_center_id", "clinic_id", "patient_id"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    visit_id = Column(Integer, nullable=False)
    owns_visit = Column(Boolean, nullable=False, default=True)  # visit was created together with this record
    affected_areas = Column(JSONB, nullable=False, default=list)  # body-region codes (regions.py)
    condition = Column(String(200))
    symptoms = Column(Text)
    severity = Column(String(10))
    diagnosis = Column(Text)
    examination_findings = Column(Text)
    treatment = Column(Text)
    notes = Column(Text)
    extra = Column(JSONB, nullable=False, default=dict)  # extensible dermatology fields


class LaserSession(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """One laser hair removal session. Numbered per patient + department (live rows unique)."""
    __tablename__ = "laser_sessions"
    __table_args__ = (
        tenant_unique("laser_sessions"),
        UniqueConstraint("visit_id", name="uq_laser_sessions_visit"),
        CheckConstraint("session_number > 0 AND session_number < 10000", name="session_number"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_laser_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_laser_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_laser_clinic"),
        tenant_fk("visit_id", "visits", ondelete="CASCADE", name="fk_laser_visit"),
        tenant_fk("author_user_id", "users", name="fk_laser_author"),
        Index("uq_laser_session_number_live", "health_center_id", "patient_id", "department_id", "session_number",
              unique=True, postgresql_where=text("pending_delete_until IS NULL")),
        Index("ix_laser_clinic_patient", "health_center_id", "clinic_id", "patient_id", "session_date"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    visit_id = Column(Integer)
    owns_visit = Column(Boolean, nullable=False, default=False)
    session_number = Column(Integer, nullable=False)
    session_date = Column(Date, nullable=False)
    notes = Column(Text)
    next_session_at = Column(DateTime(timezone=True))
    next_appointment_id = Column(Integer)  # integration point with appointments (not an FK)
    extra = Column(JSONB, nullable=False, default=dict)


class LaserSessionArea(db.Model, TenantMixin):
    __tablename__ = "laser_session_areas"
    __table_args__ = (
        tenant_unique("laser_session_areas"),
        UniqueConstraint("session_id", "region", "side", name="uq_laser_area"),
        CheckConstraint("side IN ('front','back')", name="side"),
        tenant_fk("session_id", "laser_sessions", ondelete="CASCADE", name="fk_laser_area_session"),
        Index("ix_laser_area_region", "health_center_id", "region"),
    )
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    region = Column(String(40), nullable=False)
    side = Column(String(5), nullable=False)
