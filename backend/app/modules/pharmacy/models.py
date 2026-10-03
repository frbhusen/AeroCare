"""Pharmacy (spec §41-42): dispensing of shared prescriptions and basic OTC sales.
Prescriptions themselves are core (models/clinical.py); stock comes from inventory locations."""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Index, Integer, JSON, Numeric, String, Text, func

from backend.app.extensions import db
from backend.app.models.base import AuthorSnapshotMixin, TenantMixin, tenant_fk, tenant_unique

QTY = Numeric(14, 3)
MONEY = Numeric(12, 2)


class Dispensation(db.Model, TenantMixin, AuthorSnapshotMixin):
    """One dispensing event for a prescription at a pharmacy clinic (what was actually handed out)."""
    __tablename__ = "pharmacy_dispensations"
    __table_args__ = (
        tenant_unique("pharmacy_dispensations"),
        tenant_fk("prescription_id", "prescriptions", ondelete="CASCADE", name="fk_disp_rx"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_disp_clinic"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_disp_patient"),
        Index("ix_disp_center_at", "health_center_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    prescription_id = Column(Integer, nullable=False, index=True)
    clinic_id = Column(Integer, nullable=False)  # pharmacy clinic that dispensed
    patient_id = Column(Integer, nullable=False)
    notes = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DispensationItem(db.Model, TenantMixin):
    __tablename__ = "pharmacy_dispensation_items"
    __table_args__ = (
        tenant_unique("pharmacy_dispensation_items"),
        tenant_fk("dispensation_id", "pharmacy_dispensations", ondelete="CASCADE", name="fk_dispi_disp"),
        tenant_fk("prescription_item_id", "prescription_items", ondelete="CASCADE", name="fk_dispi_rxi"),
        tenant_fk("inventory_item_id", "inventory_items", ondelete="NO ACTION", name="fk_dispi_item"),
        CheckConstraint("quantity > 0", name="dispi_qty_pos"),
    )
    id = Column(Integer, primary_key=True)
    dispensation_id = Column(Integer, nullable=False, index=True)
    prescription_item_id = Column(Integer, nullable=False, index=True)
    inventory_item_id = Column(Integer, nullable=False)
    item_name = Column(String(200), nullable=False)  # snapshot of what was dispensed
    quantity = Column(QTY, nullable=False)
    is_substitution = Column(Boolean, nullable=False, default=False)
    note = Column(String(500))
    lots = Column(JSON, nullable=False, default=list)  # [{lot_id, lot_code, expiry_date, quantity}]


class Sale(db.Model, TenantMixin, AuthorSnapshotMixin):
    """Basic over-the-counter sale (self-contained; see docs/modules/inventory.md for billing)."""
    __tablename__ = "pharmacy_sales"
    __table_args__ = (
        tenant_unique("pharmacy_sales"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_sale_clinic"),
        tenant_fk("patient_id", "patients", ondelete="CASCADE", name="fk_sale_patient"),
        CheckConstraint("total >= 0 AND paid_amount >= 0", name="sale_amounts"),
        Index("ix_sale_center_at", "health_center_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    clinic_id = Column(Integer, nullable=False)
    patient_id = Column(Integer)
    customer_name = Column(String(200))
    total = Column(MONEY, nullable=False)
    paid_amount = Column(MONEY, nullable=False, default=0)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SaleItem(db.Model, TenantMixin):
    __tablename__ = "pharmacy_sale_items"
    __table_args__ = (
        tenant_unique("pharmacy_sale_items"),
        tenant_fk("sale_id", "pharmacy_sales", ondelete="CASCADE", name="fk_salei_sale"),
        tenant_fk("inventory_item_id", "inventory_items", ondelete="NO ACTION", name="fk_salei_item"),
        CheckConstraint("quantity > 0 AND unit_price >= 0 AND line_total >= 0", name="salei_amounts"),
    )
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, nullable=False, index=True)
    inventory_item_id = Column(Integer, nullable=False)
    item_name = Column(String(200), nullable=False)
    quantity = Column(QTY, nullable=False)
    unit_price = Column(MONEY, nullable=False)
    line_total = Column(MONEY, nullable=False)
    lots = Column(JSON, nullable=False, default=list)
