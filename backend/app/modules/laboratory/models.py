"""Laboratory models.

Catalog (center-level): LabTestCategory, LabTest. Managed only by holders of `lab.manage_tests`
who are center-wide or manage a laboratory-environment department (never Superadmin).

Workflow: LabRequest (requested -> in_progress -> completed | cancelled) with LabRequestItem
rows. Items snapshot the test definition (code/name/unit/ranges) at request time so later
catalog edits never rewrite historical results.
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, Index, Integer, JSON, Numeric, String, Text)

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin,
                                     VersionMixin, tenant_fk, tenant_unique)

RESULT_TYPES = ("numeric", "text", "choice")
PRIORITIES = ("routine", "urgent")
STATUSES = ("requested", "in_progress", "completed", "cancelled")
FLAGS = ("L", "H", "N", "A")


class LabTestCategory(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    __tablename__ = "lab_test_categories"
    __table_args__ = (
        tenant_unique("lab_test_categories"),
        Index("uq_lab_category_name", "health_center_id", "name", unique=True,
              postgresql_where="pending_delete_until IS NULL"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    sort_order = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)


class LabTest(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    __tablename__ = "lab_tests"
    __table_args__ = (
        tenant_unique("lab_tests"),
        tenant_fk("category_id", "lab_test_categories", ondelete="SET NULL", name="fk_labtest_category"),
        CheckConstraint("result_type IN ('numeric','text','choice')", name="result_type"),
        Index("uq_lab_test_code", "health_center_id", "code", unique=True,
              postgresql_where="pending_delete_until IS NULL"),
    )
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer)
    code = Column(String(40), nullable=False)
    name = Column(String(200), nullable=False)
    unit = Column(String(40))
    result_type = Column(String(10), nullable=False, default="numeric")
    choices = Column(JSON)  # choice type: allowed values
    normal_choices = Column(JSON)  # choice type: values considered normal (others flagged "A")
    ref_low = Column(Numeric(14, 4))
    ref_high = Column(Numeric(14, 4))
    ref_low_male = Column(Numeric(14, 4))
    ref_high_male = Column(Numeric(14, 4))
    ref_low_female = Column(Numeric(14, 4))
    ref_high_female = Column(Numeric(14, 4))
    ref_text = Column(String(255))  # textual reference ("Negative", "< 200 mg/dL"...)
    price = Column(Numeric(12, 2))
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=100)
    notes = Column(Text)


class LabRequest(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    """Author snapshot = requester. Owned on the requesting side by requesting_clinic_id and on
    the laboratory side by lab_department_id (+ lab_clinic_id once known)."""
    __tablename__ = "lab_requests"
    __table_args__ = (
        tenant_unique("lab_requests"),
        CheckConstraint("status IN ('requested','in_progress','completed','cancelled')", name="status"),
        CheckConstraint("priority IN ('routine','urgent')", name="priority"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_labreq_patient"),
        tenant_fk("requesting_department_id", "health_center_departments", ondelete="CASCADE",
                  name="fk_labreq_req_dept"),
        tenant_fk("requesting_clinic_id", "clinics", ondelete="CASCADE", name="fk_labreq_req_clinic"),
        tenant_fk("lab_department_id", "health_center_departments", ondelete="CASCADE", name="fk_labreq_lab_dept"),
        tenant_fk("lab_clinic_id", "clinics", ondelete="SET NULL", name="fk_labreq_lab_clinic"),
        tenant_fk("visit_id", "visits", ondelete="SET NULL", name="fk_labreq_visit"),
        tenant_fk("report_file_id", "files", ondelete="SET NULL", name="fk_labreq_report_file"),
        Index("ix_labreq_lab_status", "health_center_id", "lab_department_id", "status", "requested_at"),
        Index("ix_labreq_req_clinic", "health_center_id", "requesting_clinic_id", "requested_at"),
        Index("ix_labreq_patient", "health_center_id", "patient_id", "requested_at"),
    )
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False)
    requesting_department_id = Column(Integer, nullable=False)
    requesting_clinic_id = Column(Integer, nullable=False)
    lab_department_id = Column(Integer, nullable=False)
    lab_clinic_id = Column(Integer)
    visit_id = Column(Integer)
    priority = Column(String(10), nullable=False, default="routine")
    status = Column(String(20), nullable=False, default="requested")
    clinical_notes = Column(Text)
    result_notes = Column(Text)  # overall laboratory comment on the report
    patient_gender = Column(String(10))  # snapshot used to pick gender ranges
    requested_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True))
    performed_by_user_id = Column(Integer)
    performed_by_name = Column(String(200))
    finalized_at = Column(DateTime(timezone=True))
    finalized_by_user_id = Column(Integer)
    finalized_by_name = Column(String(200))
    finalized_by_role = Column(String(40))
    cancelled_at = Column(DateTime(timezone=True))
    cancelled_by_name = Column(String(200))
    cancel_reason = Column(String(500))
    report_file_id = Column(Integer)  # generated PDF (center-wide file) when PDF service is available


class LabRequestItem(db.Model, TenantMixin, TimestampMixin):
    __tablename__ = "lab_request_items"
    __table_args__ = (
        tenant_unique("lab_request_items"),
        tenant_fk("request_id", "lab_requests", ondelete="CASCADE", name="fk_labitem_request"),
        tenant_fk("test_id", "lab_tests", ondelete="SET NULL", name="fk_labitem_test"),
        CheckConstraint("abnormal_flag IS NULL OR abnormal_flag IN ('L','H','N','A')", name="flag"),
    )
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, nullable=False, index=True)
    test_id = Column(Integer)
    # snapshot of the test definition at request time
    test_code = Column(String(40), nullable=False)
    test_name = Column(String(200), nullable=False)
    category_name = Column(String(150))
    unit = Column(String(40))
    result_type = Column(String(10), nullable=False)
    choices = Column(JSON)
    normal_choices = Column(JSON)
    ref_low = Column(Numeric(14, 4))
    ref_high = Column(Numeric(14, 4))
    ref_text = Column(String(255))
    price = Column(Numeric(12, 2))
    # result
    result_value = Column(Text)
    numeric_value = Column(Numeric(14, 4))
    abnormal_flag = Column(String(1))
    comment = Column(Text)
    sort_order = Column(Integer, nullable=False, default=0)
