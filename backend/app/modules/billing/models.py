"""Billing: services & pricing, invoices, invoice items, payments, document templates.

Money columns are NUMERIC(14,2) and handled as Decimal everywhere (serialized as strings).
Every invoice is traceable to center -> department -> clinic (-> doctor where applicable).
Invoice totals (subtotal/discount_total/total/paid_total/balance) are maintained exclusively by
billing.service.recalculate(); DB CHECKs guard the invariants.
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, Index, Integer, JSON, Numeric, String, Text,
                        UniqueConstraint)

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin,
                                     VersionMixin, tenant_fk, tenant_unique)

MONEY = Numeric(14, 2)

INVOICE_STATUSES = ("draft", "issued", "partially_paid", "paid", "void")
ITEM_KINDS = ("consultation", "treatment", "procedure", "lab_test", "radiology", "medicine", "product", "service",
              "other")
PAYMENT_METHODS = ("cash",)  # extensible later (DB CHECK must be widened together with this tuple)
TEMPLATE_KINDS = ("prescription", "invoice", "receipt", "lab_report", "radiology_report", "visit_summary",
                  "patient_summary", "appointment_slip")


class Service(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    """Billable service. department_id NULL = center-wide; clinic_id set = only that clinic
    (department_id is then the clinic's department)."""
    __tablename__ = "billing_services"
    __table_args__ = (
        tenant_unique("billing_services"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_bsvc_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_bsvc_clinic"),
        CheckConstraint("price >= 0 AND (cost IS NULL OR cost >= 0)", name="amounts"),
        CheckConstraint("duration_minutes IS NULL OR duration_minutes BETWEEN 1 AND 1440", name="duration"),
        CheckConstraint("clinic_id IS NULL OR department_id IS NOT NULL", name="clinic_has_department"),
        Index("ix_bsvc_center_dept", "health_center_id", "department_id", "clinic_id"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer)
    clinic_id = Column(Integer)
    name = Column(String(200), nullable=False)
    category = Column(String(100))
    kind = Column(String(20), nullable=False, default="service")  # default invoice item kind
    cost = Column(MONEY)
    price = Column(MONEY, nullable=False)
    duration_minutes = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)


class ServicePrice(db.Model, TenantMixin, TimestampMixin, VersionMixin):
    """Price override for one service at exactly one level: a department or a clinic.
    Effective price: clinic override -> department override -> service default."""
    __tablename__ = "billing_service_prices"
    __table_args__ = (
        tenant_unique("billing_service_prices"),
        tenant_fk("service_id", "billing_services", ondelete="CASCADE", name="fk_bsp_service"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_bsp_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_bsp_clinic"),
        CheckConstraint("(department_id IS NULL) <> (clinic_id IS NULL)", name="one_level"),
        CheckConstraint("price >= 0", name="price"),
        Index("uq_bsp_service_clinic", "service_id", "clinic_id", unique=True,
              postgresql_where="clinic_id IS NOT NULL"),
        Index("uq_bsp_service_department", "service_id", "department_id", unique=True,
              postgresql_where="department_id IS NOT NULL"),
    )
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer)
    clinic_id = Column(Integer)
    price = Column(MONEY, nullable=False)


class Invoice(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, AuthorSnapshotMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        tenant_unique("invoices"),
        UniqueConstraint("health_center_id", "number", name="uq_invoice_number"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_inv_patient"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_inv_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_inv_clinic"),
        tenant_fk("doctor_user_id", "users", name="fk_inv_doctor"),
        CheckConstraint("status IN ('draft','issued','partially_paid','paid','void')", name="status"),
        CheckConstraint("subtotal >= 0 AND discount_total >= 0 AND total >= 0 AND paid_total >= 0", name="nonneg"),
        CheckConstraint("total = subtotal - discount_total", name="total_math"),
        CheckConstraint("balance = total - paid_total", name="balance_math"),
        CheckConstraint("paid_total <= total", name="no_overpay"),
        Index("ix_inv_clinic_issued", "health_center_id", "clinic_id", "issued_at"),
        Index("ix_inv_dept_issued", "health_center_id", "department_id", "issued_at"),
        Index("ix_inv_center_status", "health_center_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    number = Column(Integer, nullable=False)  # per-center sequence; displayed INV-000001
    patient_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer, nullable=False)
    clinic_id = Column(Integer, nullable=False)
    doctor_user_id = Column(Integer)
    doctor_name = Column(String(200))  # snapshot
    status = Column(String(20), nullable=False, default="draft")
    subtotal = Column(MONEY, nullable=False, default=0)
    invoice_discount = Column(MONEY, nullable=False, default=0)  # invoice-level discount (on top of lines)
    discount_total = Column(MONEY, nullable=False, default=0)  # line discounts + invoice discount
    total = Column(MONEY, nullable=False, default=0)
    paid_total = Column(MONEY, nullable=False, default=0)
    balance = Column(MONEY, nullable=False, default=0)
    currency = Column(String(10), nullable=False)
    notes = Column(Text)
    issued_at = Column(DateTime(timezone=True))
    voided_at = Column(DateTime(timezone=True))
    void_reason = Column(String(300))
    payment_seq = Column(Integer, nullable=False, default=0)

    @property
    def display_number(self):
        return f"INV-{self.number:06d}"


class InvoiceItem(db.Model, TenantMixin):
    __tablename__ = "invoice_items"
    __table_args__ = (
        tenant_unique("invoice_items"),
        tenant_fk("invoice_id", "invoices", ondelete="CASCADE", name="fk_invi_invoice"),
        tenant_fk("service_id", "billing_services", name="fk_invi_service"),
        CheckConstraint("kind IN ('consultation','treatment','procedure','lab_test','radiology','medicine',"
                        "'product','service','other')", name="kind"),
        CheckConstraint("qty > 0 AND unit_price >= 0 AND discount_amount >= 0", name="amounts"),
        CheckConstraint("discount_percent IS NULL OR (discount_percent >= 0 AND discount_percent <= 100)",
                        name="percent"),
        CheckConstraint("line_total = round(qty * unit_price, 2) - discount_amount AND line_total >= 0",
                        name="line_math"),
        Index("ix_invi_reference", "health_center_id", "reference_type", "reference_id"),
    )
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    kind = Column(String(20), nullable=False, default="service")
    service_id = Column(Integer)
    description = Column(String(300), nullable=False)
    qty = Column(Numeric(10, 2), nullable=False, default=1)
    unit_price = Column(MONEY, nullable=False)
    list_price = Column(MONEY)  # effective catalog price when the line was added (custom/discount tracking)
    discount_percent = Column(Numeric(5, 2))
    discount_amount = Column(MONEY, nullable=False, default=0)
    line_total = Column(MONEY, nullable=False)
    reference_type = Column(String(40))  # e.g. 'dental_treatment', 'lab_request', 'radiology_study'
    reference_id = Column(Integer)


class Payment(db.Model, TenantMixin, TimestampMixin, VersionMixin, AuthorSnapshotMixin):
    """A received payment. Author snapshot = the staff member who received it. Corrections are
    made by voiding (never by editing the amount)."""
    __tablename__ = "payments"
    __table_args__ = (
        tenant_unique("payments"),
        tenant_fk("invoice_id", "invoices", ondelete="CASCADE", name="fk_pay_invoice"),
        CheckConstraint("method IN ('cash')", name="method"),
        CheckConstraint("amount > 0", name="amount"),
        UniqueConstraint("invoice_id", "seq", name="uq_payment_seq"),
        Index("ix_pay_center_paid", "health_center_id", "paid_at"),
    )
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, nullable=False, index=True)
    seq = Column(Integer, nullable=False)  # 1.. per invoice; receipt number INV-000001-1
    amount = Column(MONEY, nullable=False)
    method = Column(String(20), nullable=False, default="cash")
    paid_at = Column(DateTime(timezone=True), nullable=False)
    notes = Column(String(500))
    is_void = Column(Boolean, nullable=False, default=False)
    voided_at = Column(DateTime(timezone=True))
    voided_by_name = Column(String(200))
    void_reason = Column(String(300))


class DocumentTemplate(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    """Per-center (department_id NULL) or per-department document style. Inheritance:
    department -> center -> built-in defaults (see services/documents.py)."""
    __tablename__ = "document_templates"
    __table_args__ = (
        tenant_unique("document_templates"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_doctpl_department"),
        CheckConstraint("kind IN ('prescription','invoice','receipt','lab_report','radiology_report',"
                        "'visit_summary','patient_summary','appointment_slip')", name="kind"),
        CheckConstraint("accent_color IS NULL OR accent_color ~ '^#[0-9a-fA-F]{6}$'", name="accent_color"),
        Index("uq_doctpl_center_kind", "health_center_id", "kind", unique=True,
              postgresql_where="department_id IS NULL AND pending_delete_until IS NULL"),
        Index("uq_doctpl_dept_kind", "health_center_id", "department_id", "kind", unique=True,
              postgresql_where="department_id IS NOT NULL AND pending_delete_until IS NULL"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer)
    kind = Column(String(30), nullable=False)
    title = Column(String(200))
    header_text = Column(Text)
    footer_text = Column(Text)
    show_logo = Column(Boolean)  # NULL = inherit
    accent_color = Column(String(7))
    extra = Column(JSON, nullable=False, default=dict)
