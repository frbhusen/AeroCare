"""Health Center -> Department -> Clinic."""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from backend.app.extensions import db
from .base import TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin, tenant_fk, tenant_unique


class Department(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    """A specialty activated inside a center (table name per spec: health_center_departments)."""
    __tablename__ = "health_center_departments"
    __table_args__ = (
        tenant_unique("health_center_departments"),
        UniqueConstraint("health_center_id", "department_type_id", name="uq_dept_center_type"),
        tenant_fk("head_user_id", "users", name="fk_dept_head_user", use_alter=True),
        Index("uq_dept_head_user", "head_user_id", unique=True, postgresql_where="head_user_id IS NOT NULL"),
    )
    id = Column(Integer, primary_key=True)
    department_type_id = Column(Integer, ForeignKey("department_types.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(150), nullable=False)
    head_user_id = Column(Integer)  # exactly zero or one head doctor per department
    color = Column(String(7))
    settings = Column(JSON, nullable=False, default=dict)  # appointment behaviour, defaults, etc.
    is_active = Column(Boolean, nullable=False, default=True)

    department_type = relationship("DepartmentType")
    clinics = relationship("Clinic", back_populates="department",
                           primaryjoin="and_(Clinic.department_id == Department.id,"
                                       " Clinic.health_center_id == Department.health_center_id)",
                           foreign_keys="Clinic.department_id", viewonly=True)

    @property
    def environment(self):
        return self.department_type.environment if self.department_type else "generic"


class Clinic(db.Model, TenantMixin, TimestampMixin, VersionMixin, UndoDeleteMixin):
    """Operational unit inside a department. Not a branch: `location` is free text (e.g. "Room 101")."""
    __tablename__ = "clinics"
    __table_args__ = (
        tenant_unique("clinics"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_clinic_department"),
        UniqueConstraint("health_center_id", "department_id", "name", name="uq_clinic_name"),
    )
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, nullable=False, index=True)
    name = Column(String(150), nullable=False)
    location = Column(String(200))
    phone = Column(String(40))
    email = Column(String(200))
    logo_file_id = Column(Integer)
    working_hours = Column(JSON, nullable=False, default=dict)  # {"sat": [["09:00","17:00"]], ...}
    settings = Column(JSON, nullable=False, default=dict)  # overrides department settings
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)

    department = relationship("Department", back_populates="clinics",
                              primaryjoin="and_(Clinic.department_id == Department.id,"
                                          " Clinic.health_center_id == Department.health_center_id)",
                              foreign_keys="Clinic.department_id")
