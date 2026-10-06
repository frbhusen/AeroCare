"""Shared clinical core: one patient identity per center, patient<->department/clinic links,
visits (encounters) and the shared prescription system.

Ownership boundary for medical data is the CLINIC (doctor identity is historical metadata).
Specialty modules attach their own tables to `visits.id` (one-to-one detail rows or children).
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, Date, DateTime, Index, Integer, Numeric, String, Text,
                        UniqueConstraint, func)

from backend.app.extensions import db
from .base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin, VersionMixin, tenant_fk,
                   tenant_unique)

GENDERS = ("male", "female")
BLOOD_TYPES = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


class Patient(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    __tablename__ = "patients"
    __table_args__ = (
        tenant_unique("patients"),
        UniqueConstraint("health_center_id", "code", name="uq_patient_code"),
        CheckConstraint("gender IS NULL OR gender IN ('male','female')", name="gender"),
        # Trigram GIN indexes on search_name / phone_digits are created in schema/sql.py.
        Index("ix_patients_center_created", "health_center_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    code = Column(Integer, nullable=False)  # per-center sequence; displayed as PAT-000001
    full_name = Column(String(200), nullable=False)
    search_name = Column(String(200), nullable=False)  # normalized (lowercase, Arabic letter folding)
    date_of_birth = Column(Date)
    gender = Column(String(10))
    phone = Column(String(40))
    phone_digits = Column(String(40))  # digits only, for search
    address = Column(String(300))
    blood_type = Column(String(5))
    allergies = Column(Text)
    chronic_conditions = Column(Text)
    medications = Column(Text)
    general_notes = Column(Text)
    created_by = Column(Integer)

    @property
    def display_code(self):
        return f"PAT-{self.code:06d}"


class PatientDepartmentLink(db.Model, TenantMixin):
    __tablename__ = "patient_department_links"
    __table_args__ = (
        UniqueConstraint("patient_id", "department_id"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_pdl_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_pdl_department"),
        Index("ix_pdl_center_department", "health_center_id", "department_id"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PatientClinicLink(db.Model, TenantMixin):
    """A patient becomes visible to a clinic's doctors through this link (created on
    registration, first appointment, walk-in, or first visit in that clinic)."""
    __tablename__ = "patient_clinic_links"
    __table_args__ = (
        UniqueConstraint("patient_id", "clinic_id"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_pcl_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_pcl_clinic"),
        Index("ix_pcl_center_clinic", "health_center_id", "clinic_id"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    clinic_id = Column(Integer, nullable=False)
    department_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


VISIT_TYPES = ("consultation", "follow_up", "treatment", "procedure", "session", "examination", "other")


class Visit(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """One encounter. Never one giant mutable record: each interaction is a new visit."""
    __tablename__ = "visits"
    __table_args__ = (
        tenant_unique("visits"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_visit_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_visit_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_visit_clinic"),
        tenant_fk("author_user_id", "users", name="fk_visit_author"),
        Index("ix_visits_clinic_patient", "health_center_id", "clinic_id", "patient_id", "visit_at"),
        Index("ix_visits_dept_at", "health_center_id", "department_id", "visit_at"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    appointment_id = Column(Integer)  # optional link; not an FK so appointments can be purged independently
    visit_at = Column(DateTime(timezone=True), nullable=False)
    visit_type = Column(String(30), nullable=False, default="consultation")
    status = Column(String(20), nullable=False, default="open")  # open | completed
    title = Column(String(200))
    notes = Column(Text)


PRESCRIPTION_STATUSES = ("pending", "partially_dispensed", "dispensed", "cancelled")


class Prescription(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """Shared across specialties. Pharmacy moves it Pending -> Dispensed (see modules/pharmacy)."""
    __tablename__ = "prescriptions"
    __table_args__ = (
        tenant_unique("prescriptions"),
        CheckConstraint("status IN ('pending','partially_dispensed','dispensed','cancelled')", name="status"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_rx_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_rx_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_rx_clinic"),
        tenant_fk("visit_id", "visits", ondelete="SET NULL", name="fk_rx_visit"),
        tenant_fk("author_user_id", "users", name="fk_rx_author"),
        Index("ix_rx_center_status", "health_center_id", "status", "prescribed_at"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    visit_id = Column(Integer)
    prescribed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status = Column(String(30), nullable=False, default="pending")
    notes = Column(Text)


class PrescriptionItem(db.Model, TenantMixin):
    __tablename__ = "prescription_items"
    __table_args__ = (
        tenant_unique("prescription_items"),
        tenant_fk("prescription_id", "prescriptions", ondelete="CASCADE", name="fk_rxi_rx"),
    )
    id = Column(Integer, primary_key=True)
    prescription_id = Column(Integer, nullable=False, index=True)
    medication_name = Column(String(200), nullable=False)
    inventory_item_id = Column(Integer)  # optional catalog link (pharmacy medication)
    dose = Column(String(100))
    frequency = Column(String(100))
    duration = Column(String(100))
    instructions = Column(Text)
    quantity = Column(Numeric(12, 2))
    dispensed_quantity = Column(Numeric(12, 2), nullable=False, default=0)
    sort_order = Column(Integer, nullable=False, default=0)


class PatientVital(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """Patient vital signs record (BP, HR, Temp, RR, SpO2, Weight, Height, BMI)."""
    __tablename__ = "patient_vitals"
    __table_args__ = (
        tenant_unique("patient_vitals"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_vital_patient"),
        tenant_fk("clinic_id", "clinics", ondelete="SET NULL", name="fk_vital_clinic"),
        tenant_fk("visit_id", "visits", ondelete="SET NULL", name="fk_vital_visit"),
        Index("ix_vitals_patient_recorded", "health_center_id", "patient_id", "recorded_at"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    clinic_id = Column(Integer)
    visit_id = Column(Integer)
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    bp_systolic = Column(Integer)
    bp_diastolic = Column(Integer)
    heart_rate = Column(Integer)
    temperature = Column(Numeric(4, 1))
    resp_rate = Column(Integer)
    spo2 = Column(Integer)
    weight = Column(Numeric(5, 2))
    height = Column(Numeric(5, 1))
    bmi = Column(Numeric(4, 1))
    notes = Column(Text)


REFERRAL_URGENCIES = ("routine", "urgent", "stat")
REFERRAL_STATUSES = ("pending", "accepted", "completed", "cancelled")


class PatientReferral(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """Cross-department consult or internal patient referral."""
    __tablename__ = "patient_referrals"
    __table_args__ = (
        tenant_unique("patient_referrals"),
        CheckConstraint("urgency IN ('routine','urgent','stat')", name="urgency"),
        CheckConstraint("status IN ('pending','accepted','completed','cancelled')", name="status"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_ref_patient"),
        tenant_fk("from_department_id", "health_center_departments", ondelete="CASCADE", name="fk_ref_from_dept"),
        tenant_fk("from_clinic_id", "clinics", ondelete="CASCADE", name="fk_ref_from_clinic"),
        tenant_fk("to_department_id", "health_center_departments", ondelete="CASCADE", name="fk_ref_to_dept"),
        tenant_fk("to_clinic_id", "clinics", ondelete="SET NULL", name="fk_ref_to_clinic"),
        tenant_fk("visit_id", "visits", ondelete="SET NULL", name="fk_ref_visit"),
        tenant_fk("completed_visit_id", "visits", ondelete="SET NULL", name="fk_ref_comp_visit"),
        Index("ix_ref_to_dept_status", "health_center_id", "to_department_id", "status", "referred_at"),
        Index("ix_ref_patient", "health_center_id", "patient_id", "referred_at"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False, index=True)
    from_department_id = Column(Integer, nullable=False)
    from_clinic_id = Column(Integer, nullable=False)
    to_department_id = Column(Integer, nullable=False)
    to_clinic_id = Column(Integer)
    visit_id = Column(Integer)
    completed_visit_id = Column(Integer)
    reason = Column(Text, nullable=False)
    urgency = Column(String(10), nullable=False, default="routine")
    status = Column(String(20), nullable=False, default="pending")
    referred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    accepted_at = Column(DateTime(timezone=True))
    accepted_by_user_id = Column(Integer)
    accepted_by_name = Column(String(200))
    completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)

