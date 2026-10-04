"""Favorites service. Visible: center-wide favorites + those of departments the principal sees.
Manage (create/edit/delete): medical_records.create, and department-level favorites only for a
department the principal sees; center-wide favorites only for center-wide principals or settings.edit."""
from sqlalchemy import func, or_, select

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso
from backend.app.core.validation import Enum, Id, Int, JsonDict, List, Money, Obj, Str, Text, validate
from backend.app.extensions import db
from backend.app.services import deletion
from .models import KINDS, ClinicalFavorite

deletion.register("clinical_favorite", ClinicalFavorite)

RX_ITEM = {"medication_name": Str(required=True, max_len=200), "dose": Str(max_len=100), "frequency": Str(max_len=100),
           "duration": Str(max_len=100), "instructions": Text(max_len=1000), "quantity": Money(max_value=100000),
           "inventory_item_id": Id()}
SCHEMA = {
    "kind": Enum(KINDS, required=True), "department_id": Id(), "field": Str(max_len=60, pattern=r"[a-z0-9_]+"),
    "title": Str(required=True, max_len=200), "body": Text(max_len=10000),
    "sort_order": Int(min_value=0, max_value=10000), "payload": JsonDict(max_keys=20),
}


def _can_manage(p, department_id):
    if not p.has("medical_records.create"):
        return False
    if department_id is None:
        return p.center_wide or p.has("settings.edit")
    return p.sees_department(department_id)


def to_json(f, p=None):
    return {"id": f.id, "kind": f.kind, "department_id": f.department_id, "field": f.field, "title": f.title,
            "body": f.body, "payload": f.payload or {}, "sort_order": f.sort_order, "author_name": f.author_name,
            "version": f.version, "created_at": iso(f.created_at),
            "can_manage": _can_manage(p, f.department_id) if p else None}


def _visible(p):
    depts = sorted(p.visible_department_ids) or [-1]
    return [p.tenant(ClinicalFavorite), ClinicalFavorite.live(),
            or_(ClinicalFavorite.department_id.is_(None), ClinicalFavorite.department_id.in_(depts))]


def _clean_payload(kind, payload):
    payload = payload or {}
    if kind == "rx_set":
        items = validate(payload, {"items": List(Obj(RX_ITEM), min_items=1, max_items=30, required=True)})["items"]
        return {"items": [{k: (str(v) if k == "quantity" else v) for k, v in i.items() if v is not None}
                          for i in items]}
    if kind == "procedure":
        d = validate(payload, {"price": Money(), "code": Str(max_len=40),
                               "duration_minutes": Int(min_value=0, max_value=1440)})
        return {k: (str(v) if k == "price" else v) for k, v in d.items() if v is not None}
    return {}


def list_favorites(p, args):
    p.require("medical_records.view")
    a = validate(args, {"kind": Enum(KINDS), "field": Str(max_len=60), "department_id": Id(), "q": Str(max_len=100)})
    stmt = select(ClinicalFavorite).where(*_visible(p))
    if a.get("kind"):
        stmt = stmt.where(ClinicalFavorite.kind == a["kind"])
    if a.get("field"):
        stmt = stmt.where(or_(ClinicalFavorite.field.is_(None), ClinicalFavorite.field == a["field"]))
    if a.get("department_id"):
        stmt = stmt.where(or_(ClinicalFavorite.department_id.is_(None),
                              ClinicalFavorite.department_id == a["department_id"]))
    if a.get("q"):
        like = f"%{a['q'].lower()}%"
        stmt = stmt.where(or_(func.lower(ClinicalFavorite.title).like(like),
                              func.lower(ClinicalFavorite.body).like(like)))
    stmt = stmt.order_by(ClinicalFavorite.sort_order, ClinicalFavorite.title, ClinicalFavorite.id)
    return paginate(db.session, stmt, lambda f: to_json(f, p), default_per_page=100)


def _get(p, fav_id):
    f = db.session.execute(select(ClinicalFavorite).where(ClinicalFavorite.id == fav_id, *_visible(p))
                           ).scalar_one_or_none()
    if f is None:
        raise NotFound("Favorite not found")
    return f


def create(p, body):
    data = validate(body, SCHEMA)
    if data.get("department_id") is not None and not p.sees_department(data["department_id"]):
        raise NotFound("Department not found")
    if not _can_manage(p, data.get("department_id")):
        raise Forbidden("You cannot manage favorites here.")
    if data["kind"] in ("snippet", "diagnosis") and not data.get("body"):
        raise ValidationError("Invalid input", details={"body": "is required"})
    f = ClinicalFavorite(health_center_id=p.center_id, department_id=data.get("department_id"), kind=data["kind"],
                         field=data.get("field"), title=data["title"], body=data.get("body"),
                         payload=_clean_payload(data["kind"], data.get("payload")),
                         sort_order=data.get("sort_order") or 100)
    f.set_author(p.user)
    db.session.add(f)
    db.session.commit()
    return f


def update(p, fav_id, body):
    f = _get(p, fav_id)
    if not _can_manage(p, f.department_id):
        raise Forbidden("You cannot manage this favorite.")
    check_version(f, (body or {}).get("version"))
    data = validate(body, {k: v for k, v in SCHEMA.items() if k not in ("kind", "department_id")}, partial=True)
    for k in ("field", "title", "body", "sort_order"):
        if k in data:
            setattr(f, k, data[k])
    if "payload" in data:
        f.payload = _clean_payload(f.kind, data["payload"])
    db.session.commit()
    return f


def delete(p, fav_id):
    f = _get(p, fav_id)
    if not _can_manage(p, f.department_id):
        raise Forbidden("You cannot manage this favorite.")
    return deletion.stage(p, f, "clinical_favorite", f.title)
