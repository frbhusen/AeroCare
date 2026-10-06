"""Superadmin: health center lifecycle (create, edit, status, plan/limits, modules, permanent
delete). All functions run in platform DB mode (superadmin portal) and commit."""
import logging
from datetime import datetime, time, timedelta

from sqlalchemy import delete, func, or_, select, update

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.storage import get_storage
from backend.app.core.timeutil import TZ, utcnow
from backend.app.core.validation import (COLOR_RE, PHONE_RE, Bool, Enum, Id, Int, List, Obj, Str, Text,
                                         validate)
from backend.app.extensions import db
from backend.app.models import (Department, DepartmentType, HealthCenter, HealthCenterModule, Plan, StoredFile,
                                User)
from backend.app.services import accounts, audit
from backend.app.services.centers import LIMIT_FIELDS, apply_plan, create_center, set_modules

from .serializers import center_json, effective_status

log = logging.getLogger("hc.admin")

SLUG_RE = r"[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?"
STATUS_ACTIONS = ("activate", "extend_trial", "expire", "suspend")


def get_center(center_id):
    c = db.session.get(HealthCenter, center_id)
    if c is None:
        raise NotFound("Health center not found")
    return c


def _storage_used(center_ids=None):
    stmt = select(StoredFile.health_center_id, func.coalesce(func.sum(StoredFile.size_bytes), 0)) \
        .group_by(StoredFile.health_center_id)
    if center_ids is not None:
        stmt = stmt.where(StoredFile.health_center_id.in_(list(center_ids) or [-1]))
    return {cid: int(v) for cid, v in db.session.execute(stmt).all()}


def _module_codes(center_id):
    return sorted(db.session.execute(
        select(DepartmentType.code).join(HealthCenterModule, HealthCenterModule.department_type_id == DepartmentType.id)
        .where(HealthCenterModule.health_center_id == center_id, HealthCenterModule.is_active.is_(True))).scalars())


def _user_counts(center_id):
    rows = db.session.execute(select(User.role, func.count()).where(
        User.health_center_id == center_id, User.status == "active").group_by(User.role)).all()
    return {r: n for r, n in rows}


def center_detail(c):
    return center_json(c, storage_used=_storage_used([c.id]).get(c.id, 0), modules=_module_codes(c.id),
                       usage=accounts.usage(c.id), user_counts=_user_counts(c.id))


def list_centers(args):
    stmt = select(HealthCenter).order_by(HealthCenter.name)
    q = (args.get("q") or "").strip()
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(HealthCenter.name.ilike(like), HealthCenter.slug.ilike(like)))
    status = args.get("status")
    now = utcnow()
    if status == "expired":
        stmt = stmt.where(or_(HealthCenter.status == "expired",
                              (HealthCenter.status == "trial") & (HealthCenter.trial_ends_at < now),
                              (HealthCenter.status == "active") & (HealthCenter.subscription_ends_at < now)))
    elif status == "trial":
        stmt = stmt.where(HealthCenter.status == "trial",
                          or_(HealthCenter.trial_ends_at.is_(None), HealthCenter.trial_ends_at >= now))
    elif status == "active":
        stmt = stmt.where(HealthCenter.status == "active",
                          or_(HealthCenter.subscription_ends_at.is_(None), HealthCenter.subscription_ends_at >= now))
    elif status == "suspended":
        stmt = stmt.where(HealthCenter.status == "suspended")
    elif status:
        raise ValidationError("Invalid status filter", details={"status": "unknown"})
    out = paginate(db.session, stmt, lambda c: c)
    used = _storage_used([c.id for c in out["items"]])
    out["items"] = [center_json(c, storage_used=used.get(c.id, 0)) for c in out["items"]]
    return out


MANAGER_SCHEMA = {"username": Str(required=True, max_len=50), "name": Str(required=True, max_len=200),
                  "password": Str(required=True, strip=False, max_len=200), "email": Str(max_len=255)}


def create_center_with_manager(p, body):
    data = validate(body, {
        "name": Str(required=True, max_len=200), "slug": Str(max_len=80, pattern=SLUG_RE),
        "plan_code": Str(max_len=40, default="basic"), "currency": Str(max_len=10, default="SYP"),
        "modules": List(Str(max_len=50), max_items=100, default=list),
        "manager": Obj(MANAGER_SCHEMA), "address": Str(max_len=300), "phone": Str(max_len=40, pattern=PHONE_RE),
        "notes": Text(max_len=5000)})
    if data.get("slug") and db.session.execute(select(HealthCenter.id).where(HealthCenter.slug == data["slug"])).first():
        raise Conflict("This slug is already used by another health center.", code="slug_taken")
    c = create_center(name=data["name"], plan_code=data["plan_code"] or "basic", module_codes=data["modules"],
                      slug=data.get("slug"), currency=data["currency"] or "SYP")
    c.address, c.phone, c.notes = data.get("address"), data.get("phone"), data.get("notes")
    manager = None
    if data.get("manager"):
        manager = _create_manager(p, c, data["manager"])
    db.session.commit()
    out = center_detail(c)
    if manager is not None:
        out["manager"] = {"id": manager.id, "email": manager.email, "username": manager.username}
    return out


def _create_manager(p, c, m):
    u = accounts.create_user_record(center_id=c.id, username=m["username"], name=m["name"], role="center_manager",
                                    password=m["password"], email=m.get("email"), must_change_password=True)
    audit.log_change(p, "user", "create", "user", u.id, f"{u.name} ({u.username})", center_id=c.id)
    return u


def create_manager(p, center_id, body):
    c = get_center(center_id)
    u = _create_manager(p, c, validate(body, MANAGER_SCHEMA))
    db.session.commit()
    return u


def update_center(center_id, body):
    c = get_center(center_id)
    data = validate(body, {
        "name": Str(max_len=200, nullable=False), "slug": Str(max_len=80, pattern=SLUG_RE, nullable=False),
        "currency": Str(max_len=10, nullable=False), "address": Str(max_len=300),
        "phone": Str(max_len=40, pattern=PHONE_RE), "notes": Text(max_len=5000),
        "primary_color": Str(pattern=COLOR_RE), "secondary_color": Str(pattern=COLOR_RE),
        "login_message": Str(max_len=300), "document_footer": Str(max_len=500), "version": Int()}, partial=True)
    check_version(c, data.pop("version", None))
    if "slug" in data and data["slug"] != c.slug and db.session.execute(
            select(HealthCenter.id).where(HealthCenter.slug == data["slug"])).first():
        raise Conflict("This slug is already used by another health center.", code="slug_taken")
    for k, v in data.items():
        if k in ("name", "slug", "currency") and not v:
            raise ValidationError("Invalid input", details={k: "is required"})
        setattr(c, k, v)
    db.session.commit()
    return center_detail(c)


def _end_of_local_day(value, field):
    """Accept 'YYYY-MM-DD' (end of that Damascus day) or an ISO datetime."""
    s = str(value or "").strip()
    try:
        if len(s) == 10:
            d = datetime.fromisoformat(s).date()
            return datetime.combine(d, time(23, 59, 59), tzinfo=TZ)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    except ValueError:
        raise ValidationError("Invalid input", details={field: "must be a date (YYYY-MM-DD) or ISO datetime"})


def change_status(center_id, body):
    c = get_center(center_id)
    data = validate(body, {"action": Enum(STATUS_ACTIONS, required=True), "subscription_ends_at": Str(max_len=40),
                           "trial_ends_at": Str(max_len=40), "days": Int(min_value=1, max_value=3650)})
    action, now = data["action"], utcnow()
    if action == "activate":
        if not data.get("subscription_ends_at"):
            raise ValidationError("Invalid input", details={"subscription_ends_at": "is required"})
        end = _end_of_local_day(data["subscription_ends_at"], "subscription_ends_at")
        if end <= now:
            raise ValidationError("Invalid input", details={"subscription_ends_at": "must be in the future"})
        c.status, c.subscription_ends_at = "active", end
    elif action == "extend_trial":
        if data.get("trial_ends_at"):
            end = _end_of_local_day(data["trial_ends_at"], "trial_ends_at")
        elif data.get("days"):
            base = c.trial_ends_at if c.trial_ends_at and c.trial_ends_at > now else now
            end = base + timedelta(days=data["days"])
        else:
            raise ValidationError("Invalid input", details={"days": "days or trial_ends_at is required"})
        if end <= now:
            raise ValidationError("Invalid input", details={"trial_ends_at": "must be in the future"})
        c.status, c.trial_ends_at = "trial", end
    elif action == "expire":
        c.status = "expired"
    else:
        c.status = "suspended"
    db.session.commit()
    return center_detail(c)


def assign_plan(center_id, body):
    c = get_center(center_id)
    data = validate(body, {"plan_id": Id(required=True)})
    plan = db.session.get(Plan, data["plan_id"])
    if plan is None:
        raise NotFound("Plan not found")
    apply_plan(c, plan)
    db.session.commit()
    return center_detail(c)


def update_limits(center_id, body):
    """Per-center overrides. A limit key sent as null means unlimited."""
    c = get_center(center_id)
    schema = {f: Int(min_value=0, max_value=100000) for f in LIMIT_FIELDS}
    schema["storage_quota_bytes"] = Int(min_value=1024 * 1024, max_value=2 ** 50, nullable=False)
    data = validate(body, schema, partial=True)
    if "storage_quota_bytes" in data:
        used = _storage_used([c.id]).get(c.id, 0)
        if data["storage_quota_bytes"] < used:
            raise ValidationError("The quota cannot be lower than the storage already used.",
                                  details={"storage_quota_bytes": f"must be >= {used}"})
    for k, v in data.items():
        setattr(c, k, v)
    db.session.commit()
    return center_detail(c)


def update_modules(center_id, body):
    c = get_center(center_id)
    data = validate(body, {"modules": List(Str(max_len=50), required=True, max_items=100)})
    active_codes = set(db.session.execute(select(DepartmentType.code).where(DepartmentType.is_active.is_(True)))
                       .scalars())
    current = set(_module_codes(c.id))
    inactive = [m for m in data["modules"] if m not in active_codes and m not in current]
    if inactive:
        raise ValidationError("Unknown or inactive modules", details={"modules": inactive})
    set_modules(c, list(dict.fromkeys(data["modules"])))
    db.session.commit()
    return center_detail(c)


def delete_center_permanently(center_id, body):
    """Irreversible: removes every tenant row of the center and its stored files. Audit log
    entries are kept (detached: health_center_id becomes NULL)."""
    c = get_center(center_id)
    data = validate(body, {"confirm": Str(required=True, max_len=80)})
    if data["confirm"] != c.slug:
        raise ValidationError("Type the health center slug to confirm.", code="confirmation_mismatch",
                              details={"confirm": "must equal the health center slug"})
    cid, slug = c.id, c.slug
    keys = list(db.session.execute(select(StoredFile.storage_key).where(StoredFile.health_center_id == cid))
                .scalars())
    db.session.execute(update(Department).where(Department.health_center_id == cid).values(head_user_id=None))
    for table in reversed(db.metadata.sorted_tables):
        if "health_center_id" in table.c and table.name not in ("audit_logs", "health_centers"):
            db.session.execute(table.delete().where(table.c.health_center_id == cid))
    db.session.execute(delete(HealthCenter).where(HealthCenter.id == cid))
    db.session.commit()
    storage = get_storage()
    failed = 0
    for k in keys:
        try:
            storage.delete(k)
        except Exception:  # bytes can be cleaned later with `flask ops storage-gc`
            failed += 1
    log.info("health center %s permanently deleted (%d files, %d byte deletions failed)", cid, len(keys), failed)
    return {"deleted": True, "id": cid, "slug": slug, "files_removed": len(keys) - failed}


def dashboard():
    now = utcnow()
    soon = now + timedelta(days=7)
    centers = db.session.execute(select(HealthCenter)).scalars().all()
    by_status = {s: 0 for s in ("trial", "active", "expired", "suspended")}
    expiring = []
    for c in centers:
        st = effective_status(c)
        by_status[st] = by_status.get(st, 0) + 1
        end = c.trial_ends_at if st == "trial" else c.subscription_ends_at if st == "active" else None
        if end and now <= end <= soon:
            expiring.append({"id": c.id, "name": c.name, "status": st, "ends_at": end.isoformat()})
    roles = dict(db.session.execute(select(User.role, func.count()).where(User.status == "active")
                                    .group_by(User.role)).all())
    used = sum(_storage_used().values())
    quota = sum(int(c.storage_quota_bytes) for c in centers)
    return {"centers_total": len(centers), "centers_by_status": by_status, "active_users_by_role": roles,
            "storage_used_bytes": used, "storage_quota_bytes": quota,
            "expiring_soon": sorted(expiring, key=lambda x: x["ends_at"])}


def storage_overview():
    centers = db.session.execute(select(HealthCenter).order_by(HealthCenter.name)).scalars().all()
    used = _storage_used()
    counts = dict(db.session.execute(select(StoredFile.health_center_id, func.count())
                                     .group_by(StoredFile.health_center_id)).all())
    items = []
    for c in centers:
        u, q = used.get(c.id, 0), int(c.storage_quota_bytes)
        items.append({"id": c.id, "name": c.name, "slug": c.slug, "used_bytes": u, "quota_bytes": q,
                      "remaining_bytes": max(0, q - u), "file_count": counts.get(c.id, 0),
                      "percent_used": round(100.0 * u / q, 1) if q else 0.0})
    return {"items": items, "total_used_bytes": sum(used.values()),
            "total_quota_bytes": sum(i["quota_bytes"] for i in items)}
