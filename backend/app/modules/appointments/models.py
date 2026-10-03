"""Appointments (spec §44-50).

Double-booking is enforced by PostgreSQL exclusion constraints (race-safe):
  ex_appointments_doctor  - one live, non-cancelled/no-show appointment per doctor per time range
  ex_appointments_clinic  - same per clinic
Constraints are DEFERRABLE INITIALLY IMMEDIATE so a "this and future" series edit can shift many
rows in one transaction (SET CONSTRAINTS ... DEFERRED), still checked at commit.
The core error handler maps any `ex_appointments_*` violation to 409 `appointment_conflict`.
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, Date, DateTime, Index, Integer, JSON, String, Text, Time)

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin,
                                     VersionMixin, tenant_fk, tenant_unique)
from backend.app.schema import register_sql

STATUSES = ("scheduled", "arrived", "in_progress", "cancelled", "no_show", "completed")
# Statuses that do not occupy the time slot.
FREE_STATUSES = ("cancelled", "no_show")
FREQUENCIES = ("daily", "weekly", "monthly")
APPOINTMENT_TYPES = ("consultation", "follow_up", "treatment", "procedure", "session", "examination", "other")


class AppointmentSeries(db.Model, TenantMixin, TimestampMixin, VersionMixin):
    """Recurrence rule + template. Each generated Appointment is a normal, individually
    manageable row pointing back here (series_id, series_index)."""
    __tablename__ = "appointment_series"
    __table_args__ = (
        tenant_unique("appointment_series"),
        CheckConstraint("freq IN ('daily','weekly','monthly')", name="freq"),
        CheckConstraint("repeat_interval >= 1 AND repeat_interval <= 52", name="interval"),
        CheckConstraint("duration_minutes > 0 AND duration_minutes <= 1440", name="duration"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_apser_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_apser_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_apser_department"),
        tenant_fk("doctor_id", "users", ondelete="NO ACTION", name="fk_apser_doctor"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False, index=True)
    doctor_id = Column(Integer)
    patient_id = Column(Integer, nullable=False, index=True)
    # Rule
    freq = Column(String(10), nullable=False)
    repeat_interval = Column(Integer, nullable=False, default=1)
    weekdays = Column(JSON)  # weekly only: ISO weekday numbers 1=Mon..7=Sun
    count = Column(Integer)
    until = Column(Date)  # local date, inclusive
    starts_on = Column(Date, nullable=False)  # local date of the first occurrence
    # Template (local wall-clock time, Asia/Damascus)
    start_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    location = Column(String(200))
    appointment_type = Column(String(40))
    reason = Column(String(300))
    notes = Column(Text)
    created_by = Column(Integer)


class Appointment(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    __tablename__ = "appointments"
    __table_args__ = (
        tenant_unique("appointments"),
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint("status IN ('scheduled','arrived','in_progress','cancelled','no_show','completed')",
                        name="status"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_appt_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_appt_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_appt_department"),
        tenant_fk("doctor_id", "users", ondelete="NO ACTION", name="fk_appt_doctor"),
        tenant_fk("author_user_id", "users", ondelete="NO ACTION", name="fk_appt_author"),
        tenant_fk("series_id", "appointment_series", ondelete="NO ACTION", name="fk_appt_series"),
        Index("ix_appt_clinic_start", "health_center_id", "clinic_id", "starts_at"),
        Index("ix_appt_doctor_start", "health_center_id", "doctor_id", "starts_at"),
        Index("ix_appt_patient_start", "health_center_id", "patient_id", "starts_at"),
        Index("ix_appt_center_start", "health_center_id", "starts_at"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    doctor_id = Column(Integer)
    patient_id = Column(Integer, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(200))
    appointment_type = Column(String(40))
    reason = Column(String(300))
    notes = Column(Text)
    status = Column(String(20), nullable=False, default="scheduled")
    status_changed_at = Column(DateTime(timezone=True))
    is_walk_in = Column(Boolean, nullable=False, default=False)
    series_id = Column(Integer, index=True)
    series_index = Column(Integer)  # 0-based position in the generated series


def _exclusion(name, column):
    return f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
    ALTER TABLE appointments ADD CONSTRAINT {name}
      EXCLUDE USING gist ({column} WITH =, tstzrange(starts_at, ends_at) WITH &&)
      WHERE (status NOT IN ('cancelled','no_show') AND pending_delete_until IS NULL AND {column} IS NOT NULL)
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
END $$;
"""


register_sql("appointments_exclusion", _exclusion("ex_appointments_doctor", "doctor_id")
             + _exclusion("ex_appointments_clinic", "clinic_id"))
