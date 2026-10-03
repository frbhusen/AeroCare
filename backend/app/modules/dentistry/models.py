"""Dentistry (port of AeroDent) models.

Ownership: health center + department + clinic + patient (+ optional visit). Every reference to a
tenant table is a composite (health_center_id, x_id) FK, so cross-tenant links are impossible.

Tooth numbering keeps AeroDent's Universal scheme (see constants.py):
  permanent 1..32, primary 1..20 (displayed as letters A..T).
"""
from sqlalchemy import (JSON, CheckConstraint, Column, Date, DateTime, Index, Integer, Numeric, String, Text, Time,
                        UniqueConstraint, func)

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin,
                                     VersionMixin, tenant_fk, tenant_unique)

_TOOTH_CHECK = ("tooth_mode IN ('permanent','primary') AND (tooth_number IS NULL OR "
                "(tooth_mode = 'permanent' AND tooth_number BETWEEN 1 AND 32) OR "
                "(tooth_mode = 'primary' AND tooth_number BETWEEN 1 AND 20))")
_STATUS_CHECK = "status IN ('planned','accepted','scheduled','in-progress','completed','cancelled')"
# Composite visit FKs null only visit_id on visit deletion (health_center_id is NOT NULL).
_SET_NULL_VISIT = "SET NULL (visit_id)"


class OdontogramTooth(db.Model, TenantMixin, TimestampMixin, VersionMixin, AuthorSnapshotMixin):
    """Current state of one tooth for a patient in a clinic. Author = who first charted it;
    `updated_by_*` = last change. Every change also appends an OdontogramEntry (history)."""
    __tablename__ = "dental_odontogram_teeth"
    __table_args__ = (
        tenant_unique("dental_odontogram_teeth"),
        UniqueConstraint("health_center_id", "clinic_id", "patient_id", "tooth_mode", "tooth_number",
                         name="uq_dental_tooth"),
        CheckConstraint(_TOOTH_CHECK + " AND tooth_number IS NOT NULL", name="tooth"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_dtooth_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_dtooth_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_dtooth_department"),
        tenant_fk("author_user_id", "users", name="fk_dtooth_author"),
        Index("ix_dtooth_clinic_patient", "health_center_id", "clinic_id", "patient_id"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    patient_id = Column(Integer, nullable=False, index=True)
    tooth_mode = Column(String(20), nullable=False)
    tooth_number = Column(Integer, nullable=False)
    condition = Column(String(40))  # NULL = cleared (AeroDent "clear")
    procedure = Column(String(150))
    notes = Column(Text)
    surfaces = Column(JSON)  # e.g. ["M","O","D"]; NULL/[] = whole tooth
    updated_by_user_id = Column(Integer)
    updated_by_name = Column(String(200))


class OdontogramEntry(db.Model, TenantMixin, AuthorSnapshotMixin):
    """Append-only history of tooth changes (never updated)."""
    __tablename__ = "dental_odontogram_entries"
    __table_args__ = (
        tenant_unique("dental_odontogram_entries"),
        tenant_fk("tooth_id", "dental_odontogram_teeth", ondelete="CASCADE", name="fk_dentry_tooth"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_dentry_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_dentry_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_dentry_department"),
        tenant_fk("visit_id", "visits", ondelete=_SET_NULL_VISIT, name="fk_dentry_visit"),
        tenant_fk("author_user_id", "users", name="fk_dentry_author"),
        Index("ix_dentry_tooth", "health_center_id", "tooth_id", "created_at"),
        Index("ix_dentry_clinic_patient", "health_center_id", "clinic_id", "patient_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    tooth_id = Column(Integer, nullable=False)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    patient_id = Column(Integer, nullable=False)
    visit_id = Column(Integer)
    tooth_mode = Column(String(20), nullable=False)
    tooth_number = Column(Integer, nullable=False)
    action = Column(String(10), nullable=False)  # set | clear
    condition = Column(String(40))
    procedure = Column(String(150))
    notes = Column(Text)
    surfaces = Column(JSON)
    tooth_version = Column(Integer, nullable=False)  # version of the tooth row after this change
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class _DentalRecord(TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    patient_id = Column(Integer, nullable=False, index=True)
    tooth_mode = Column(String(20), nullable=False, default="permanent")
    tooth_number = Column(Integer)
    procedure = Column(String(150))
    fee = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="planned")
    doctor_user_id = Column(Integer)
    doctor_name = Column(String(200))  # snapshot at assignment


class Treatment(db.Model, _DentalRecord):
    __tablename__ = "dental_treatments"
    __table_args__ = (
        tenant_unique("dental_treatments"),
        CheckConstraint(_TOOTH_CHECK, name="tooth"),
        CheckConstraint(_STATUS_CHECK, name="status"),
        CheckConstraint("fee >= 0", name="fee"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_dtreat_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_dtreat_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_dtreat_department"),
        tenant_fk("visit_id", "visits", ondelete=_SET_NULL_VISIT, name="fk_dtreat_visit"),
        tenant_fk("plan_id", "dental_treatment_plans", ondelete="SET NULL (plan_id)", name="fk_dtreat_plan"),
        tenant_fk("doctor_user_id", "users", name="fk_dtreat_doctor"),
        tenant_fk("author_user_id", "users", name="fk_dtreat_author"),
        Index("ix_dtreat_clinic_patient", "health_center_id", "clinic_id", "patient_id", "date"),
    )
    visit_id = Column(Integer)
    plan_id = Column(Integer)  # source treatment-plan item (convert)
    description = Column(Text)
    date = Column(Date, nullable=False)


class TreatmentPlan(db.Model, _DentalRecord):
    __tablename__ = "dental_treatment_plans"
    __table_args__ = (
        tenant_unique("dental_treatment_plans"),
        CheckConstraint(_TOOTH_CHECK, name="tooth"),
        CheckConstraint(_STATUS_CHECK, name="status"),
        CheckConstraint("priority IN ('low','medium','high')", name="priority"),
        CheckConstraint("fee >= 0", name="fee"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_dplan_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_dplan_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_dplan_department"),
        tenant_fk("doctor_user_id", "users", name="fk_dplan_doctor"),
        tenant_fk("author_user_id", "users", name="fk_dplan_author"),
        Index("ix_dplan_clinic_patient", "health_center_id", "clinic_id", "patient_id"),
    )
    diagnosis = Column(Text)
    priority = Column(String(10), nullable=False, default="medium")
    notes = Column(Text)
    converted_treatment_id = Column(Integer)  # last treatment created from this item (plain id)
    converted_at = Column(DateTime(timezone=True))


class XRay(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """X-ray metadata. Bytes live in the platform file store (`files`, category 'xray',
    owner_type 'dental_xray', owner_id = this id); download via /api/v1/files/<file_id>/content.
    Purging the X-ray deletes its file row (trigger below) and the purger removes the bytes."""
    __tablename__ = "dental_xrays"
    __table_args__ = (
        tenant_unique("dental_xrays"),
        CheckConstraint("type IN ('periapical','bitewing','panoramic','cephalometric','occlusal','cbct','other')",
                        name="type"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_dxray_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_dxray_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_dxray_department"),
        tenant_fk("visit_id", "visits", ondelete=_SET_NULL_VISIT, name="fk_dxray_visit"),
        tenant_fk("file_id", "files", ondelete="CASCADE", name="fk_dxray_file"),
        tenant_fk("author_user_id", "users", name="fk_dxray_author"),
        Index("ix_dxray_clinic_patient", "health_center_id", "clinic_id", "patient_id", "date"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    patient_id = Column(Integer, nullable=False, index=True)
    visit_id = Column(Integer)
    file_id = Column(Integer, nullable=False, unique=True)
    filename = Column(String(255), nullable=False)
    type = Column(String(20), nullable=False, default="other")
    tooth_tag = Column(String(100))
    date = Column(Date, nullable=False)
    time = Column(Time)
    notes = Column(Text)


from backend.app.schema import register_sql  # noqa: E402

register_sql("dentistry_xray_file_cleanup", """
CREATE OR REPLACE FUNCTION hc_dental_xray_delete_file() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM files WHERE health_center_id = OLD.health_center_id AND id = OLD.file_id;
  RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS trg_dental_xray_delete_file ON dental_xrays;
CREATE TRIGGER trg_dental_xray_delete_file AFTER DELETE ON dental_xrays
  FOR EACH ROW EXECUTE FUNCTION hc_dental_xray_delete_file();
""")
