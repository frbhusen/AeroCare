"""JSON serializers for the superadmin portal (explicit fields only)."""
from backend.app.core.timeutil import iso, utcnow
from backend.app.services.centers import LIMIT_FIELDS


def effective_status(c):
    """Status as enforced at login (expired trials/subscriptions read as 'expired')."""
    now = utcnow()
    if c.status == "trial" and c.trial_ends_at and c.trial_ends_at < now:
        return "expired"
    if c.status == "active" and c.subscription_ends_at and c.subscription_ends_at < now:
        return "expired"
    return c.status


def plan_json(pl):
    return {"id": pl.id, "code": pl.code, "name": pl.name, "is_active": pl.is_active,
            "storage_quota_bytes": pl.storage_quota_bytes, **{f: getattr(pl, f) for f in LIMIT_FIELDS}}


def center_json(c, *, storage_used=None, modules=None, usage=None, user_counts=None):
    out = {
        "id": c.id, "name": c.name, "slug": c.slug, "status": effective_status(c), "stored_status": c.status,
        "trial_ends_at": iso(c.trial_ends_at), "subscription_ends_at": iso(c.subscription_ends_at),
        "plan": {"id": c.plan.id, "code": c.plan.code, "name": c.plan.name} if c.plan else None,
        "limits": {f: getattr(c, f) for f in LIMIT_FIELDS},
        "storage_quota_bytes": int(c.storage_quota_bytes),
        "storage_used_bytes": int(storage_used if storage_used is not None else c.storage_used_bytes or 0),
        "currency": c.currency, "primary_color": c.primary_color, "secondary_color": c.secondary_color,
        "login_message": c.login_message, "document_footer": c.document_footer, "address": c.address,
        "phone": c.phone, "notes": c.notes, "created_at": iso(c.created_at), "version": c.version,
    }
    if modules is not None:
        out["modules"] = modules
    if usage is not None:
        out["usage"] = usage
    if user_counts is not None:
        out["user_counts"] = user_counts
    return out


def department_type_json(t):
    return {"id": t.id, "code": t.code, "name_en": t.name_en, "name_ar": t.name_ar, "environment": t.environment,
            "is_custom": t.is_custom, "icon": t.icon, "color": t.color, "is_active": t.is_active,
            "sort_order": t.sort_order}


def user_json(u, center_names=None):
    return {"id": u.id, "username": u.username, "name": u.name, "email": u.email,
            "email_is_generated": u.email_is_generated, "role": u.role, "status": u.status,
            "health_center_id": u.health_center_id,
            "center_name": (center_names or {}).get(u.health_center_id) if u.health_center_id else None,
            "clinic_id": u.clinic_id, "department_id": u.department_id, "phone": u.phone,
            "specialty_title": u.specialty_title, "last_login_at": iso(u.last_login_at),
            "created_at": iso(u.created_at), "version": u.version}


def audit_json(a, center_names=None):
    return {"id": a.id, "health_center_id": a.health_center_id,
            "center_name": (center_names or {}).get(a.health_center_id),
            "department_id": a.department_id, "category": a.category, "action": a.action,
            "actor_user_id": a.actor_user_id, "actor_name": a.actor_name, "actor_role": a.actor_role,
            "target_type": a.target_type, "target_id": a.target_id, "target_label": a.target_label,
            "details": a.details, "ip": a.ip, "created_at": iso(a.created_at)}
