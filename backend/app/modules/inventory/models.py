"""Inventory (spec §57-60): center-wide item catalog, stock locations (clinic / department pool /
center pool), lots with expiry, an append-only movement ledger and stock transfers.

Quantities are Numeric(14,3); a CHECK keeps every lot >= 0 and all decrements lock the item row
and the lots (SELECT ... FOR UPDATE) before reading balances, so stock can never go negative.
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, Date, DateTime, Index, Integer, JSON, Numeric, String,
                        Text, func)

from backend.app.extensions import db
from backend.app.models.base import (AuthorSnapshotMixin, TenantMixin, TimestampMixin, UndoDeleteMixin,
                                     VersionMixin, tenant_fk, tenant_unique)
from backend.app.schema import register_sql

LOCATION_KINDS = ("clinic", "department_pool", "center_pool")
MOVEMENT_TYPES = ("receive", "use", "adjust", "transfer_out", "transfer_in", "dispense", "sale", "write_off")
QTY = Numeric(14, 3)
MONEY = Numeric(12, 2)


class InventoryItem(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    """Catalog entry. `department_id` NULL = center-wide (general supplies) item."""
    __tablename__ = "inventory_items"
    __table_args__ = (
        tenant_unique("inventory_items"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_inv_item_department"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="inv_item_cost"),
        CheckConstraint("selling_price IS NULL OR selling_price >= 0", name="inv_item_price"),
        CheckConstraint("low_stock_threshold IS NULL OR low_stock_threshold >= 0", name="inv_item_threshold"),
        Index("ix_inv_items_center_name", "health_center_id", "name"),
        # Unique barcode / case-insensitive SKU per center: partial indexes in register_sql below.
    )
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100))
    sku = Column(String(100))
    barcode = Column(String(100))
    unit = Column(String(40))
    cost = Column(MONEY)
    selling_price = Column(MONEY)
    low_stock_threshold = Column(QTY)
    supplier = Column(String(200))
    is_medication = Column(Boolean, nullable=False, default=False)
    department_id = Column(Integer, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)


class InventoryLocation(db.Model, TenantMixin):
    """Where stock lives. One row per clinic / department pool / center pool (created on demand)."""
    __tablename__ = "inventory_locations"
    __table_args__ = (
        tenant_unique("inventory_locations"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_inv_loc_clinic"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_inv_loc_department"),
        CheckConstraint(
            "(kind = 'clinic' AND clinic_id IS NOT NULL AND department_id IS NOT NULL) OR "
            "(kind = 'department_pool' AND clinic_id IS NULL AND department_id IS NOT NULL) OR "
            "(kind = 'center_pool' AND clinic_id IS NULL AND department_id IS NULL)", name="inv_loc_kind"),
        Index("uq_inv_loc_clinic", "health_center_id", "clinic_id", unique=True,
              postgresql_where="kind = 'clinic'"),
        Index("uq_inv_loc_dept_pool", "health_center_id", "department_id", unique=True,
              postgresql_where="kind = 'department_pool'"),
        Index("uq_inv_loc_center_pool", "health_center_id", unique=True, postgresql_where="kind = 'center_pool'"),
    )
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)
    department_id = Column(Integer)  # clinic's department for kind=clinic
    clinic_id = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockLot(db.Model, TenantMixin):
    """Quantity of one item at one location for one lot/batch + expiry. Never negative."""
    __tablename__ = "stock_lots"
    __table_args__ = (
        tenant_unique("stock_lots"),
        tenant_fk("item_id", "inventory_items", ondelete="CASCADE", name="fk_lot_item"),
        tenant_fk("location_id", "inventory_locations", ondelete="CASCADE", name="fk_lot_location"),
        CheckConstraint("quantity >= 0", name="lot_qty_nonneg"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="lot_cost_nonneg"),
        Index("ix_lots_item_location", "health_center_id", "item_id", "location_id"),
        Index("ix_lots_location_expiry", "health_center_id", "location_id", "expiry_date"),
    )
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    lot_code = Column(String(100))
    expiry_date = Column(Date)
    quantity = Column(QTY, nullable=False, default=0)
    unit_cost = Column(MONEY)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockMovement(db.Model, TenantMixin, AuthorSnapshotMixin):
    """Append-only ledger. `quantity` is signed (+ in, - out)."""
    __tablename__ = "stock_movements"
    __table_args__ = (
        tenant_unique("stock_movements"),
        tenant_fk("item_id", "inventory_items", ondelete="CASCADE", name="fk_mov_item"),
        tenant_fk("location_id", "inventory_locations", ondelete="CASCADE", name="fk_mov_location"),
        tenant_fk("lot_id", "stock_lots", ondelete="CASCADE", name="fk_mov_lot"),
        CheckConstraint("type IN ('receive','use','adjust','transfer_out','transfer_in','dispense','sale',"
                        "'write_off')", name="mov_type"),
        CheckConstraint("quantity <> 0", name="mov_qty_nonzero"),
        Index("ix_mov_location_at", "health_center_id", "location_id", "created_at"),
        Index("ix_mov_item_at", "health_center_id", "item_id", "created_at"),
        Index("ix_mov_reference", "health_center_id", "reference_type", "reference_id"),
    )
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    lot_id = Column(Integer)
    type = Column(String(20), nullable=False)
    quantity = Column(QTY, nullable=False)
    balance_after = Column(QTY)  # item total at this location after the movement
    unit_cost = Column(MONEY)
    reason = Column(String(300))
    reference_type = Column(String(40))
    reference_id = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockTransfer(db.Model, TenantMixin, AuthorSnapshotMixin):
    """Immediate transfer between two locations (status always 'completed')."""
    __tablename__ = "stock_transfers"
    __table_args__ = (
        tenant_unique("stock_transfers"),
        tenant_fk("from_location_id", "inventory_locations", ondelete="CASCADE", name="fk_tr_from"),
        tenant_fk("to_location_id", "inventory_locations", ondelete="CASCADE", name="fk_tr_to"),
        CheckConstraint("from_location_id <> to_location_id", name="tr_distinct"),
        Index("ix_tr_center_at", "health_center_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    from_location_id = Column(Integer, nullable=False)
    to_location_id = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="completed")
    notes = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockTransferItem(db.Model, TenantMixin):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (
        tenant_unique("stock_transfer_items"),
        tenant_fk("transfer_id", "stock_transfers", ondelete="CASCADE", name="fk_tri_transfer"),
        tenant_fk("item_id", "inventory_items", ondelete="CASCADE", name="fk_tri_item"),
        CheckConstraint("quantity > 0", name="tri_qty_pos"),
    )
    id = Column(Integer, primary_key=True)
    transfer_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False)
    quantity = Column(QTY, nullable=False)
    lots = Column(JSON, nullable=False, default=list)  # [{lot_code, expiry_date, quantity}]


register_sql("inventory_unique_codes", """
CREATE UNIQUE INDEX IF NOT EXISTS uq_inv_item_barcode ON inventory_items (health_center_id, barcode)
  WHERE barcode IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_inv_item_sku ON inventory_items (health_center_id, lower(sku))
  WHERE sku IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_inv_items_name_trgm ON inventory_items USING gin (lower(name) gin_trgm_ops);
CREATE OR REPLACE FUNCTION hc_stock_movement_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'stock_movements is append-only'; END $$;
DROP TRIGGER IF EXISTS trg_stock_movement_immutable ON stock_movements;
CREATE TRIGGER trg_stock_movement_immutable BEFORE UPDATE ON stock_movements
  FOR EACH ROW EXECUTE FUNCTION hc_stock_movement_immutable();
""")
