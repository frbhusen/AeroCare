"""Account creation/updates and plan-limit enforcement (shared by staff + superadmin modules)."""
import uuid

from flask import current_app, has_app_context
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.core.errors import Conflict, ValidationError
from backend.app.core.validation import EMAIL_RE, USERNAME_RE
from backend.app.extensions import db
from backend.app.models import Clinic, Department, HealthCenter, User

import re

_USERNAME = re.compile(USERNAME_RE)
_EMAIL = re.compile(EMAIL_RE)


def email_domain():
    return current_app.config["EMAIL_DOMAIN"] if has_app_context() else "aerodent.com"


def generated_email(username, user_id):
    return f"{username.lower()}_{user_id}@{email_domain()}"


def check_username(username):
    if not username or not _USERNAME.fullmatch(username):
        raise ValidationError("Invalid username", details={
            "username": "English letters, digits, dot, dash or underscore; 3-50 characters; no spaces"})
    return username


def check_email(email):
    email = (email or "").strip().lower()
    if not _EMAIL.fullmatch(email):
        raise ValidationError("Invalid email", details={"email": "has an invalid format"})
    return email


def _flush_user(u):
    try:
        db.session.flush()
    except IntegrityError as e:
        db.session.rollback()
        cname = getattr(getattr(e.orig, "diag", None), "constraint_name", "") or ""
        if cname == "uq_users_email_lower":
            raise Conflict("This email is already in use.", code="email_taken")
        if cname == "uq_users_center_username":
            raise Conflict("This username is already used in this health center.", code="username_taken")
        raise


def create_user_record(*, center_id, username, name, role, password, email=None, clinic_id=None,
                       department_id=None, phone=None, specialty_title=None):
    from backend.app.auth.service import hash_password, validate_password
    check_username(username)
    validate_password(password)
    name = (name or "").strip()
    if not name or len(name) > 200:
        raise ValidationError("Invalid name", details={"name": "is required (max 200 characters)"})
    u = User(health_center_id=center_id, username=username, name=name, role=role,
             password_hash=hash_password(password), clinic_id=clinic_id, department_id=department_id, phone=phone,
             specialty_title=specialty_title, email=f"pending-{uuid.uuid4().hex}@invalid.local",
             email_is_generated=email is None)
    db.session.add(u)
    _flush_user(u)
    u.email = check_email(email) if email else generated_email(username, u.id)
    _flush_user(u)
    return u


def apply_identity_change(u, *, username=None, email=None, reset_email_to_generated=False):
    """Username change regenerates the generated email (same immutable id). A custom email is
    kept unless reset_email_to_generated."""
    if username is not None and username != u.username:
        check_username(username)
        u.username = username
        if u.email_is_generated:
            u.email = generated_email(username, u.id)
    if email is not None:
        u.email = check_email(email)
        u.email_is_generated = u.email == generated_email(u.username, u.id)
    if reset_email_to_generated:
        u.email = generated_email(u.username, u.id)
        u.email_is_generated = True
    _flush_user(u)


# ---------------------------------------------------------------- plan limits
LIMIT_LABELS = {"max_doctors": "doctors", "max_receptionists": "receptionists", "max_head_doctors": "head doctors",
                "max_clinics": "clinics", "max_departments": "departments"}


def usage(center_id):
    def cnt(stmt):
        return db.session.execute(stmt).scalar_one()
    active = (User.health_center_id == center_id) & (User.status == "active")
    return {
        "max_doctors": cnt(select(func.count()).select_from(User).where(active, User.role == "doctor")),
        "max_receptionists": cnt(select(func.count()).select_from(User).where(active, User.role == "receptionist")),
        "max_head_doctors": cnt(select(func.count()).select_from(Department).where(
            Department.health_center_id == center_id, Department.head_user_id.isnot(None),
            Department.pending_delete_until.is_(None))),
        "max_clinics": cnt(select(func.count()).select_from(Clinic).where(
            Clinic.health_center_id == center_id, Clinic.pending_delete_until.is_(None))),
        "max_departments": cnt(select(func.count()).select_from(Department).where(
            Department.health_center_id == center_id, Department.pending_delete_until.is_(None))),
    }


def check_limit(center_id, key, adding=1):
    center = db.session.get(HealthCenter, center_id)
    limit = getattr(center, key)
    if limit is None:
        return
    used = usage(center_id)[key]
    if used + adding > limit:
        raise ValidationError(f"Your plan allows at most {limit} {LIMIT_LABELS[key]}.", code="plan_limit_reached",
                              details={"limit": key, "max": limit, "used": used})


def role_limit_key(role):
    return {"doctor": "max_doctors", "receptionist": "max_receptionists"}.get(role)
