"""Health center lifecycle + concurrency-safe per-center sequences."""
import re
from datetime import timedelta

from flask import current_app
from sqlalchemy import select, update

from backend.app.core.errors import Conflict, ValidationError
from backend.app.core.timeutil import utcnow
from backend.app.extensions import db
from backend.app.models import DepartmentType, HealthCenter, HealthCenterModule, Plan

LIMIT_FIELDS = ("max_departments", "max_head_doctors", "max_doctors", "max_receptionists", "max_clinics")


def next_sequence(center_id, column):
    """Atomically increment a per-center counter. The UPDATE row lock serializes concurrent
    callers, so values are unique and gap-free per committed transaction."""
    col = getattr(HealthCenter, column)
    return db.session.execute(update(HealthCenter).where(HealthCenter.id == center_id).values({col: col + 1})
                              .returning(col)).scalar_one()


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:60] or "center"


def apply_plan(center, plan):
    center.plan_id = plan.id
    for f in LIMIT_FIELDS:
        setattr(center, f, getattr(plan, f))
    if plan.storage_quota_bytes and plan.storage_quota_bytes > (center.storage_quota_bytes or 0):
        center.storage_quota_bytes = plan.storage_quota_bytes


def create_center(*, name, plan_code="basic", module_codes=(), slug=None, currency="SYP"):
    """Create a center in Trial status (14 days). Caller must be in platform DB mode."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("Name is required", details={"name": "is required"})
    plan = db.session.execute(select(Plan).where(Plan.code == plan_code)).scalar_one_or_none()
    if plan is None:
        raise ValidationError("Unknown plan", details={"plan_code": "unknown"})
    base = slug or slugify(name)
    candidate, n = base, 1
    while db.session.execute(select(HealthCenter.id).where(HealthCenter.slug == candidate)).first():
        n += 1
        candidate = f"{base}-{n}"
    c = HealthCenter(name=name, slug=candidate, status="trial",
                     trial_ends_at=utcnow() + timedelta(days=current_app.config["TRIAL_DAYS"]),
                     storage_quota_bytes=current_app.config["DEFAULT_STORAGE_QUOTA_BYTES"], currency=currency)
    apply_plan(c, plan)
    db.session.add(c)
    db.session.flush()
    set_modules(c, module_codes)
    return c


def set_modules(center, module_codes):
    """Activate exactly these department types (by code) for the center."""
    types = {t.code: t for t in db.session.execute(select(DepartmentType)).scalars()}
    unknown = [m for m in module_codes if m not in types]
    if unknown:
        raise ValidationError("Unknown modules", details={"modules": unknown})
    existing = {m.department_type_id: m for m in db.session.execute(
        select(HealthCenterModule).where(HealthCenterModule.health_center_id == center.id)).scalars()}
    wanted = {types[c].id for c in module_codes}
    for tid, m in existing.items():
        m.is_active = tid in wanted
    for tid in wanted - set(existing):
        db.session.add(HealthCenterModule(health_center_id=center.id, department_type_id=tid, is_active=True))
    db.session.flush()


def active_module_type_ids(center_id):
    return set(db.session.execute(select(HealthCenterModule.department_type_id).where(
        HealthCenterModule.health_center_id == center_id, HealthCenterModule.is_active.is_(True))).scalars())
