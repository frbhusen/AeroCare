"""Accounts, scope assignments, sessions, permission overrides."""
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func, text)

from backend.app.extensions import db
from .base import TenantMixin, TimestampMixin, VersionMixin, tenant_fk, tenant_unique

ROLES = ("superadmin", "center_manager", "department_manager", "doctor", "receptionist")


class User(db.Model, TimestampMixin, VersionMixin):
    """One account per person. `id` is immutable and embedded in the generated email.

    Scope columns:
      doctor              -> clinic_id (exactly one, required)
      department_manager  -> department_id (required), clinic_id optional (their own working clinic)
      receptionist        -> user_scopes rows (center / departments / clinics)
      center_manager      -> whole center
      superadmin          -> health_center_id IS NULL (platform)
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("health_center_id", "id", name="uq_users_tenant_id"),
        CheckConstraint("role IN ('superadmin','center_manager','department_manager','doctor','receptionist')",
                        name="role"),
        CheckConstraint("status IN ('active','archived')", name="status"),
        CheckConstraint("(role = 'superadmin') = (health_center_id IS NULL)", name="superadmin_no_center"),
        CheckConstraint("role <> 'doctor' OR clinic_id IS NOT NULL", name="doctor_has_clinic"),
        CheckConstraint("role <> 'department_manager' OR department_id IS NOT NULL", name="manager_has_department"),
        CheckConstraint("username ~ '^[A-Za-z0-9._-]{3,50}$'", name="username_format"),
        tenant_fk("clinic_id", "clinics", name="fk_user_clinic"),
        tenant_fk("department_id", "health_center_departments", name="fk_user_department"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        Index("uq_users_center_username", "health_center_id", text("lower(username)"), unique=True),
    )
    id = Column(Integer, primary_key=True)
    health_center_id = Column(Integer, ForeignKey("health_centers.id", ondelete="CASCADE"), nullable=True, index=True)
    username = Column(String(50), nullable=False)
    name = Column(String(200), nullable=False)
    email = Column(String(255), nullable=False)
    email_is_generated = Column(Boolean, nullable=False, default=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    clinic_id = Column(Integer, index=True)
    department_id = Column(Integer, index=True)
    phone = Column(String(40))
    specialty_title = Column(String(150))
    last_login_at = Column(DateTime(timezone=True))
    password_changed_at = Column(DateTime(timezone=True))
    # Set when an administrator chose the password (new account / reset): the user must pick their own.
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="false")

    @property
    def is_active(self):
        return self.status == "active"


class UserScope(db.Model, TenantMixin, TimestampMixin):
    """Receptionist assignments. Both NULL = whole center; department_id = whole department;
    clinic_id = one clinic."""
    __tablename__ = "user_scopes"
    __table_args__ = (
        tenant_unique("user_scopes"),
        CheckConstraint("NOT (department_id IS NOT NULL AND clinic_id IS NOT NULL)", name="one_target"),
        tenant_fk("user_id", "users", ondelete="CASCADE", name="fk_scope_user"),
        tenant_fk("department_id", "health_center_departments", ondelete="CASCADE", name="fk_scope_department"),
        tenant_fk("clinic_id", "clinics", ondelete="CASCADE", name="fk_scope_clinic"),
        UniqueConstraint("user_id", "department_id", "clinic_id", name="uq_scope_target"),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    department_id = Column(Integer)
    clinic_id = Column(Integer)


class UserSession(db.Model):
    """Server-side session. Cookie carries a random token; only its SHA-256 is stored.
    Single active session per user: login revokes all other sessions of that user."""
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    csrf_token = Column(String(64), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    acting_center_id = Column(Integer, ForeignKey("health_centers.id", ondelete="SET NULL"))  # superadmin support view
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
    revoked_reason = Column(String(40))
    ip = Column(String(64))
    user_agent = Column(String(300))


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_email_at", "email", "attempted_at"),
                      Index("ix_login_attempts_ip_at", "ip", "attempted_at"))
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    ip = Column(String(64))
    success = Column(Boolean, nullable=False)
    attempted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RolePermission(db.Model, TenantMixin, TimestampMixin):
    """Center-level customization of a role's default permissions (defaults live in
    authz/permissions.py). allowed=False removes a default; allowed=True adds one."""
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("health_center_id", "role", "permission"),)
    id = Column(Integer, primary_key=True)
    role = Column(String(30), nullable=False)
    permission = Column(String(80), nullable=False)
    allowed = Column(Boolean, nullable=False)


class UserPermission(db.Model, TenantMixin, TimestampMixin):
    """Per-user grant/revoke on top of role permissions (e.g. a receptionist allowed to edit
    medical records). Revocable by deleting the row or setting allowed=False."""
    __tablename__ = "user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "permission"),
        tenant_fk("user_id", "users", ondelete="CASCADE", name="fk_userperm_user"),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    permission = Column(String(80), nullable=False)
    allowed = Column(Boolean, nullable=False)
    granted_by = Column(Integer)
    note = Column(Text)
