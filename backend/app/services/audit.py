"""Immutable audit log. ONLY these categories are logged (spec §17):
login (success/failure), department create/edit/delete, clinic create/edit/delete,
user create/edit/delete. Never medical-record or financial activity/content."""
from flask import has_request_context, request

from backend.app.extensions import db
from backend.app.models import AuditLog


def _ip():
    return (request.remote_addr or "")[:64] if has_request_context() else None


def log_login(user, email, success):
    db.session.add(AuditLog(
        health_center_id=user.health_center_id if user else None,
        category="login", action="success" if success else "failure",
        actor_user_id=user.id if user else None, actor_name=user.name if user else None,
        actor_role=user.role if user else None, target_type="user", target_id=user.id if user else None,
        target_label=(email or "")[:255], ip=_ip()))


def log_change(principal, category, action, target_type, target_id, label, *, department_id=None,
               changed_fields=None, center_id=None):
    assert category in ("department", "clinic", "user") and action in ("create", "edit", "delete")
    details = {"fields": sorted(changed_fields)} if changed_fields else None
    db.session.add(AuditLog(
        health_center_id=center_id or principal.center_id, department_id=department_id, category=category,
        action=action, actor_user_id=principal.user.id, actor_name=principal.user.name, actor_role=principal.role,
        target_type=target_type, target_id=target_id, target_label=(label or "")[:255], details=details, ip=_ip()))
