"""Ophthalmology examination (spec §38, §82-83): one exam per visit, structured per-eye data.

Per-eye blocks (`right_eye` = OD, `left_eye` = OS) are JSONB validated by a strict server-side
schema (schemas.py) so the structure stays consistent while remaining extensible.
"""
from sqlalchemy import Boolean, Column, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin, VersionMixin,
                                     tenant_fk, tenant_unique)


class OphthalmologyExam(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    __tablename__ = "ophthalmology_exams"
    __table_args__ = (
        tenant_unique("ophthalmology_exams"),
        UniqueConstraint("visit_id", name="uq_ophthalmology_exams_visit"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_oph_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_oph_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_oph_clinic"),
        tenant_fk("visit_id", "visits", ondelete="CASCADE", name="fk_oph_visit"),
        tenant_fk("author_user_id", "users", name="fk_oph_author"),
        Index("ix_oph_exams_clinic_patient", "health_center_id", "clinic_id", "patient_id"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    visit_id = Column(Integer, nullable=False)
    owns_visit = Column(Boolean, nullable=False, default=True)
    chief_complaint = Column(Text)
    history = Column(Text)
    right_eye = Column(JSONB, nullable=False, default=dict)  # OD
    left_eye = Column(JSONB, nullable=False, default=dict)  # OS
    diagnosis = Column(Text)
    treatment = Column(Text)
    glasses = Column(JSONB, nullable=False, default=dict)  # spectacle prescription block
    follow_up = Column(String(200))
    notes = Column(Text)
    extra = Column(JSONB, nullable=False, default=dict)
