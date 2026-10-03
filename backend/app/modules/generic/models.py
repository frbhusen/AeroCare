"""Generic medical environment (spec §43): one GenericVisitRecord per visit for departments
without a dedicated module (General Medicine, Pediatrics, Cardiology, custom departments...)."""
from sqlalchemy import Column, Index, Integer, JSON, Text, UniqueConstraint

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, VersionMixin, tenant_fk,
                                     tenant_unique)


class GenericVisitRecord(db.Model, TenantMixin, TimestampMixin, VersionMixin, AuthorSnapshotMixin):
    __tablename__ = "generic_visit_records"
    __table_args__ = (
        tenant_unique("generic_visit_records"),
        UniqueConstraint("visit_id", name="uq_generic_record_visit"),
        tenant_fk("visit_id", "visits", ondelete="CASCADE", name="fk_generic_record_visit"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_generic_record_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_generic_record_clinic"),
        tenant_fk("author_user_id", "users", name="fk_generic_record_author"),
        Index("ix_generic_record_patient", "health_center_id", "patient_id", "clinic_id"),
    )
    id = Column(Integer, primary_key=True)
    visit_id = Column(Integer, nullable=False)
    patient_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    chief_complaint = Column(Text)
    symptoms = Column(Text)
    # {bp_systolic, bp_diastolic, heart_rate, temperature, resp_rate, spo2, weight, height}
    vitals = Column(JSON, nullable=False, default=dict)
    examination = Column(Text)
    diagnosis = Column(Text)
    assessment = Column(Text)
    treatment_plan = Column(Text)
    medications = Column(Text)
    notes = Column(Text)
    extra = Column(JSON, nullable=False, default=dict)  # extensibility for department-specific fields
    last_edited_by = Column(Integer)
    last_edited_name = Column(db.String(200))
