"""The authenticated principal and its scope. Built once per request by the auth layer and
available as `flask.g.principal` (or `current_principal()`).

Authorization chain for every protected endpoint (spec §8/§86):
    authenticated user -> health center -> role -> department scope -> clinic scope -> permission

Use:
    p = current_principal()
    p.require("patients.view")                         # permission only (403)
    p.require("medical_records.edit", clinic_id=c)     # permission + scope (404 if out of scope)
    stmt = stmt.where(p.clinic_clause(Visit.clinic_id)) # scope filter for lists
"""
from dataclasses import dataclass, field

from flask import g
from sqlalchemy import false, select, true

from backend.app.core.errors import Forbidden, NotFound, Unauthorized
from backend.app.extensions import db
from .permissions import ROLE_DEFAULTS, ROLE_FORBIDDEN

# Permissions a Superadmin keeps while viewing a center in support mode (never medical edits).
SUPPORT_READ = {"patients.view", "appointments.view", "medical_records.view", "files.view", "billing.view",
                "inventory.view", "staff.view", "staff.create", "staff.edit", "staff.delete", "settings.view",
                "settings.edit", "reports.view", "reports.export", "audit.view", "backup.create",
                "permissions.manage"}


@dataclass
class Principal:
    user: object
    session: object = None
    center_id: int | None = None
    role: str = ""
    is_superadmin: bool = False
    support_mode: bool = False  # superadmin acting inside a center
    perms: set = field(default_factory=set)
    center_wide: bool = False
    clinic_ids: frozenset = frozenset()  # accessible clinics (all active clinics if center_wide)
    managed_department_ids: frozenset = frozenset()  # departments with full department-level access
    visible_department_ids: frozenset = frozenset()  # departments shown in navigation
    clinic_department: dict = field(default_factory=dict)  # clinic_id -> department_id (accessible only)
    department_env: dict = field(default_factory=dict)  # department_id -> environment (accessible only)

    # ---- permission checks -------------------------------------------------
    def has(self, perm: str) -> bool:
        return perm in self.perms

    def can_clinic(self, clinic_id) -> bool:
        return clinic_id is not None and clinic_id in self.clinic_ids

    def can_department(self, department_id) -> bool:
        """Department-level (manage) access: managers / department receptionists / center-wide."""
        return department_id is not None and department_id in self.managed_department_ids

    def sees_department(self, department_id) -> bool:
        return department_id is not None and department_id in self.visible_department_ids

    def require(self, perm=None, *, clinic_id=None, department_id=None, department_level=False):
        """Raise unless permitted. Out-of-scope -> 404 (never reveal existence); missing
        permission on an in-scope object -> 403."""
        if clinic_id is not None and not self.can_clinic(clinic_id):
            raise NotFound("Not found")
        if department_id is not None:
            ok = self.can_department(department_id) if department_level else self.sees_department(department_id)
            if not ok:
                raise NotFound("Not found")
        if perm and perm not in self.perms:
            raise Forbidden("You do not have permission to perform this action.",
                            details={"permission": perm})
        return True

    def require_center_manager(self):
        if not (self.role == "center_manager" or self.support_mode):
            raise Forbidden("Health center manager access required.")

    # ---- SQL helpers -------------------------------------------------------
    def tenant(self, model):
        """Explicit tenant filter. Always combine with scope clauses (RLS is only a backstop)."""
        if not self.center_id:
            return false()
        return model.health_center_id == self.center_id

    def clinic_clause(self, column):
        if self.center_wide:
            return true()
        if not self.clinic_ids:
            return false()
        return column.in_(sorted(self.clinic_ids))

    def department_clause(self, column, managed=False):
        ids = self.managed_department_ids if managed else self.visible_department_ids
        if self.center_wide:
            return true()
        if not ids:
            return false()
        return column.in_(sorted(ids))

    def patient_clause(self, patient_id_column):
        """Patients visible to this principal: linked to an accessible clinic."""
        from backend.app.models import PatientClinicLink
        if self.center_wide:
            return true()
        if not self.clinic_ids:
            return false()
        sub = select(PatientClinicLink.patient_id).where(PatientClinicLink.clinic_id.in_(sorted(self.clinic_ids)))
        return patient_id_column.in_(sub)

    def to_json(self):
        return {
            "role": self.role, "center_id": self.center_id, "is_superadmin": self.is_superadmin,
            "support_mode": self.support_mode, "permissions": sorted(self.perms), "center_wide": self.center_wide,
            "clinic_ids": sorted(self.clinic_ids), "managed_department_ids": sorted(self.managed_department_ids),
            "visible_department_ids": sorted(self.visible_department_ids),
        }


def current_principal() -> Principal:
    p = getattr(g, "principal", None)
    if p is None:
        raise Unauthorized("Authentication required")
    return p


def effective_permissions(user, center_id):
    from backend.app.models import RolePermission, UserPermission
    perms = set(ROLE_DEFAULTS.get(user.role, set()))
    rows = db.session.execute(
        select(RolePermission.permission, RolePermission.allowed)
        .where(RolePermission.health_center_id == center_id, RolePermission.role == user.role)).all()
    for perm, allowed in rows:
        (perms.add if allowed else perms.discard)(perm)
    rows = db.session.execute(
        select(UserPermission.permission, UserPermission.allowed).where(UserPermission.user_id == user.id)).all()
    for perm, allowed in rows:
        (perms.add if allowed else perms.discard)(perm)
    return perms - ROLE_FORBIDDEN.get(user.role, set())


def active_structure(center_id):
    """(clinic_id -> department_id, department_id -> environment) for active, non-deleted
    departments whose module is activated for the center, and their active clinics."""
    from backend.app.models import Clinic, Department, DepartmentType, HealthCenterModule
    depts = db.session.execute(
        select(Department.id, DepartmentType.environment)
        .join(DepartmentType, DepartmentType.id == Department.department_type_id)
        .join(HealthCenterModule, (HealthCenterModule.department_type_id == Department.department_type_id)
              & (HealthCenterModule.health_center_id == Department.health_center_id))
        .where(Department.health_center_id == center_id, Department.is_active.is_(True),
               Department.pending_delete_until.is_(None), HealthCenterModule.is_active.is_(True),
               DepartmentType.is_active.is_(True))).all()
    dept_env = {d: env for d, env in depts}
    clinics = db.session.execute(
        select(Clinic.id, Clinic.department_id).where(
            Clinic.health_center_id == center_id, Clinic.is_active.is_(True), Clinic.pending_delete_until.is_(None),
            Clinic.department_id.in_(list(dept_env) or [-1]))).all()
    return {c: d for c, d in clinics}, dept_env


def build_principal(user, session=None, acting_center_id=None) -> Principal:
    from backend.app.models import UserScope
    if user.role == "superadmin":
        if not acting_center_id:
            return Principal(user=user, session=session, role="superadmin", is_superadmin=True)
        center_id = acting_center_id
        clinic_dept, dept_env = active_structure(center_id)
        return Principal(user=user, session=session, center_id=center_id, role="superadmin", is_superadmin=True,
                         support_mode=True, perms=set(SUPPORT_READ), center_wide=True,
                         clinic_ids=frozenset(clinic_dept), managed_department_ids=frozenset(dept_env),
                         visible_department_ids=frozenset(dept_env), clinic_department=clinic_dept,
                         department_env=dept_env)

    center_id = user.health_center_id
    clinic_dept, dept_env = active_structure(center_id)
    perms = effective_permissions(user, center_id)
    center_wide = False
    clinics, managed = set(), set()
    if user.role == "center_manager":
        center_wide = True
    elif user.role == "department_manager":
        if user.department_id in dept_env:
            managed.add(user.department_id)
            clinics |= {c for c, d in clinic_dept.items() if d == user.department_id}
    elif user.role == "doctor":
        if user.clinic_id in clinic_dept:
            clinics.add(user.clinic_id)
    elif user.role == "receptionist":
        scopes = db.session.execute(select(UserScope.department_id, UserScope.clinic_id)
                                    .where(UserScope.user_id == user.id)).all()
        for dept_id, clinic_id in scopes:
            if dept_id is None and clinic_id is None:
                center_wide = True
            elif dept_id is not None and dept_id in dept_env:
                managed.add(dept_id)
                clinics |= {c for c, d in clinic_dept.items() if d == dept_id}
            elif clinic_id is not None and clinic_id in clinic_dept:
                clinics.add(clinic_id)
    if center_wide:
        clinics, managed = set(clinic_dept), set(dept_env)
    visible = managed | {clinic_dept[c] for c in clinics}
    return Principal(
        user=user, session=session, center_id=center_id, role=user.role, perms=perms, center_wide=center_wide,
        clinic_ids=frozenset(clinics), managed_department_ids=frozenset(managed),
        visible_department_ids=frozenset(visible),
        clinic_department={c: clinic_dept[c] for c in clinics},
        department_env={d: dept_env[d] for d in visible},
    )
