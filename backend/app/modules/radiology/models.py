"""Radiology: one entity per request+study (spec §39).

Status: requested -> scheduled -> in_progress -> reported -> finalized | cancelled
(requested -> in_progress is allowed for walk-ins; cancel allowed before finalization).
Images are StoredFile rows (category 'radiology_image', owner_type 'radiology_study') owned by
the radiology clinic. On finalization they are shared with the requesting clinic.
"""
from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String, Text, func

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin,
                                     VersionMixin, tenant_fk, tenant_unique)

EXAM_TYPES = ("x_ray", "ct", "mri", "ultrasound", "other")
PRIORITIES = ("routine", "urgent")
STATUSES = ("requested", "scheduled", "in_progress", "reported", "finalized", "cancelled")


class RadiologyStudy(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """Author snapshot = requester."""
    __tablename__ = "radiology_studies"
    __table_args__ = (
        tenant_unique("radiology_studies"),
        CheckConstraint("status IN ('requested','scheduled','in_progress','reported','finalized','cancelled')",
                        name="status"),
        CheckConstraint("exam_type IN ('x_ray','ct','mri','ultrasound','other')", name="exam_type"),
        CheckConstraint("priority IN ('routine','urgent')", name="priority"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_rad_patient"),
        tenant_fk("requesting_department_id", "health_center_departments", ondelete="CASCADE",
                  name="fk_rad_req_dept"),
        tenant_fk("requesting_clinic_id", "clinics", ondelete="CASCADE", name="fk_rad_req_clinic"),
        tenant_fk("radiology_department_id", "health_center_departments", ondelete="CASCADE",
                  name="fk_rad_rad_dept"),
        tenant_fk("radiology_clinic_id", "clinics", ondelete="SET NULL", name="fk_rad_rad_clinic"),
        tenant_fk("visit_id", "visits", ondelete="SET NULL", name="fk_rad_visit"),
        tenant_fk("report_file_id", "files", ondelete="SET NULL", name="fk_rad_report_file"),
        Index("ix_rad_dept_status", "health_center_id", "radiology_department_id", "status", "requested_at"),
        Index("ix_rad_req_clinic", "health_center_id", "requesting_clinic_id", "requested_at"),
        Index("ix_rad_patient", "health_center_id", "patient_id", "requested_at"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False)
    requesting_department_id = Column(Integer, nullable=False)
    requesting_clinic_id = Column(Integer, nullable=False)
    radiology_department_id = Column(Integer, nullable=False)
    radiology_clinic_id = Column(Integer)
    visit_id = Column(Integer)
    exam_type = Column(String(20), nullable=False)
    body_region = Column(String(150))
    clinical_question = Column(Text)
    priority = Column(String(10), nullable=False, default="routine")
    status = Column(String(20), nullable=False, default="requested")
    requested_at = Column(DateTime(timezone=True), nullable=False)
    scheduled_at = Column(DateTime(timezone=True))
    performed_at = Column(DateTime(timezone=True))
    # report
    findings = Column(Text)
    impression = Column(Text)
    radiologist_user_id = Column(Integer)
    radiologist_name = Column(String(200))
    radiologist_role = Column(String(40))
    reported_at = Column(DateTime(timezone=True))
    finalized_at = Column(DateTime(timezone=True))
    finalized_by_user_id = Column(Integer)
    finalized_by_name = Column(String(200))
    cancelled_at = Column(DateTime(timezone=True))
    cancelled_by_name = Column(String(200))
    cancel_reason = Column(String(500))
    report_file_id = Column(Integer)


class RadiologyStudyShare(db.Model, TenantMixin):
    """Explicit share of a FINALIZED study (report + images) with one target. Revocable."""
    __tablename__ = "radiology_study_shares"
    __table_args__ = (
        tenant_unique("radiology_study_shares"),
        CheckConstraint("(CASE WHEN target_department_id IS NOT NULL THEN 1 ELSE 0 END"
                        " + CASE WHEN target_clinic_id IS NOT NULL THEN 1 ELSE 0 END"
                        " + CASE WHEN target_user_id IS NOT NULL THEN 1 ELSE 0 END) = 1", name="one_target"),
        tenant_fk("study_id", "radiology_studies", ondelete="CASCADE", name="fk_radshare_study"),
        tenant_fk("target_department_id", "health_center_departments", ondelete="CASCADE",
                  name="fk_radshare_dept"),
        tenant_fk("target_clinic_id", "clinics", ondelete="CASCADE", name="fk_radshare_clinic"),
        tenant_fk("target_user_id", "users", ondelete="CASCADE", name="fk_radshare_user"),
    )
    id = Column(Integer, primary_key=True)
    study_id = Column(Integer, nullable=False, index=True)
    target_department_id = Column(Integer)
    target_clinic_id = Column(Integer)
    target_user_id = Column(Integer)
    shared_by = Column(Integer)
    shared_by_name = Column(String(200))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
