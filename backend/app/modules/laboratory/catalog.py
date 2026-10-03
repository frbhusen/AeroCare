"""Lab test catalog (categories + tests with units and reference ranges).

Management requires `lab.manage_tests` AND (center-wide principal OR manager of a laboratory
department). The Superadmin never manages tests (support mode lacks the permission, and it is
also rejected explicitly). Reading the catalog requires any laboratory permission.
"""
from decimal import Decimal

from sqlalchemy import or_, select

from backend.app.authz.principal import current_principal
from backend.app.core.api import check_version
from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.core.validation import Bool, Id, Int, List, Money, Num, Str, Text, Enum, validate
from backend.app.extensions import db
from backend.app.services import deletion

from .models import RESULT_TYPES, LabTest, LabTestCategory
from .routing import env_structure

deletion.register("lab_test", LabTest)
deletion.register("lab_test_category", LabTestCategory)

READ_PERMS = ("lab.request", "lab.process", "lab.manage_tests")

CATEGORY_SCHEMA = {
    "name": Str(required=True, max_len=150),
    "sort_order": Int(min_value=0, max_value=100000, default=100),
    "is_active": Bool(default=True),
}

_REF = Num(min_value=-10**9, max_value=10**9, places=4)
TEST_SCHEMA = {
    "code": Str(required=True, max_len=40, pattern=r"[A-Za-z0-9._\-]+"),
    "name": Str(required=True, max_len=200),
    "category_id": Id(),
    "unit": Str(max_len=40),
    "result_type": Enum(RESULT_TYPES, default="numeric"),
    "choices": List(Str(required=True, max_len=100), max_items=50),
    "normal_choices": List(Str(required=True, max_len=100), max_items=50),
    "ref_low": _REF, "ref_high": _REF,
    "ref_low_male": _REF, "ref_high_male": _REF,
    "ref_low_female": _REF, "ref_high_female": _REF,
    "ref_text": Str(max_len=255),
    "price": Money(),
    "is_active": Bool(default=True),
    "sort_order": Int(min_value=0, max_value=100000, default=100),
    "notes": Text(max_len=2000),
}
TEST_FIELDS = [k for k in TEST_SCHEMA]


def require_read(p):
    if not any(p.has(x) for x in READ_PERMS):
        raise Forbidden("You do not have permission to view the lab test catalog.",
                        details={"permission": "lab.request"})


def can_manage_tests(p):
    if p.is_superadmin or not p.has("lab.manage_tests"):
        return False
    if p.center_wide:
        return True
    return any(p.can_department(d) for d in env_structure(p.center_id, "laboratory"))


def require_manage(p):
    if not can_manage_tests(p):
        raise Forbidden("Only the Health Center Manager or a Laboratory manager can manage lab tests.",
                        details={"permission": "lab.manage_tests"})


def _num(v):
    return None if v is None else format(Decimal(v).normalize(), "f")


def category_json(c):
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active, "version": c.version}


def test_json(t, category_name=None):
    return {
        "id": t.id, "code": t.code, "name": t.name, "category_id": t.category_id, "category_name": category_name,
        "unit": t.unit, "result_type": t.result_type, "choices": t.choices or [],
        "normal_choices": t.normal_choices or [],
        "ref_low": _num(t.ref_low), "ref_high": _num(t.ref_high),
        "ref_low_male": _num(t.ref_low_male), "ref_high_male": _num(t.ref_high_male),
        "ref_low_female": _num(t.ref_low_female), "ref_high_female": _num(t.ref_high_female),
        "ref_text": t.ref_text, "price": None if t.price is None else str(t.price), "is_active": t.is_active,
        "sort_order": t.sort_order, "notes": t.notes, "version": t.version,
    }


# ---- categories -------------------------------------------------------------
def _get_category(p, cid):
    c = db.session.execute(select(LabTestCategory).where(LabTestCategory.id == cid, p.tenant(LabTestCategory),
                                                         LabTestCategory.live())).scalar_one_or_none()
    if c is None:
        raise NotFound("Category not found")
    return c


def list_categories(include_inactive=True):
    p = current_principal()
    require_read(p)
    stmt = select(LabTestCategory).where(p.tenant(LabTestCategory), LabTestCategory.live())
    if not include_inactive:
        stmt = stmt.where(LabTestCategory.is_active.is_(True))
    rows = db.session.execute(stmt.order_by(LabTestCategory.sort_order, LabTestCategory.name)).scalars()
    return [category_json(c) for c in rows]


def create_category(data):
    p = current_principal()
    require_manage(p)
    d = validate(data, CATEGORY_SCHEMA)
    c = LabTestCategory(health_center_id=p.center_id, **d)
    db.session.add(c)
    db.session.commit()
    return category_json(c)


def update_category(cid, data):
    p = current_principal()
    require_manage(p)
    c = _get_category(p, cid)
    check_version(c, data.get("version"))
    d = validate(data, CATEGORY_SCHEMA, partial=True)
    for k, v in d.items():
        if k == "name" and not v:
            raise ValidationError("Invalid input", details={"name": "is required"})
        setattr(c, k, v)
    db.session.commit()
    return category_json(c)


def delete_category(cid):
    p = current_principal()
    require_manage(p)
    c = _get_category(p, cid)
    return deletion.stage(p, c, "lab_test_category", c.name)


# ---- tests ------------------------------------------------------------------
def _get_test(p, tid):
    t = db.session.execute(select(LabTest).where(LabTest.id == tid, p.tenant(LabTest), LabTest.live())
                           ).scalar_one_or_none()
    if t is None:
        raise NotFound("Lab test not found")
    return t


def _check_test(p, t):
    errors = {}
    if t.result_type == "choice":
        if not t.choices:
            errors["choices"] = "is required for choice results"
        elif len(set(t.choices)) != len(t.choices):
            errors["choices"] = "must be unique"
        if t.normal_choices and not set(t.normal_choices) <= set(t.choices or []):
            errors["normal_choices"] = "must be a subset of choices"
    else:
        t.choices, t.normal_choices = None, None
    if t.result_type != "numeric":
        t.ref_low = t.ref_high = t.ref_low_male = t.ref_high_male = t.ref_low_female = t.ref_high_female = None
    for lo, hi in (("ref_low", "ref_high"), ("ref_low_male", "ref_high_male"), ("ref_low_female", "ref_high_female")):
        a, b = getattr(t, lo), getattr(t, hi)
        if a is not None and b is not None and Decimal(a) > Decimal(b):
            errors[hi] = f"must be >= {lo}"
    if t.category_id is not None:
        try:
            _get_category(p, t.category_id)
        except NotFound:
            errors["category_id"] = "is invalid"
    dup = db.session.execute(select(LabTest.id).where(p.tenant(LabTest), LabTest.live(), LabTest.code == t.code,
                                                      LabTest.id != (t.id or -1))).first()
    if dup:
        errors["code"] = "is already used by another test"
    if errors:
        raise ValidationError("Invalid input", details=errors)


def list_tests(category_id=None, active=None, q=None):
    p = current_principal()
    require_read(p)
    stmt = (select(LabTest, LabTestCategory.name)
            .outerjoin(LabTestCategory, (LabTestCategory.id == LabTest.category_id)
                       & (LabTestCategory.health_center_id == LabTest.health_center_id))
            .where(p.tenant(LabTest), LabTest.live()))
    if category_id:
        stmt = stmt.where(LabTest.category_id == category_id)
    if active is not None:
        stmt = stmt.where(LabTest.is_active.is_(active))
    if q:
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(LabTest.name.ilike(like), LabTest.code.ilike(like)))
    rows = db.session.execute(stmt.order_by(LabTest.sort_order, LabTest.name).limit(1000)).all()
    return [test_json(t, cn) for t, cn in rows]


def get_test(tid):
    p = current_principal()
    require_read(p)
    t = _get_test(p, tid)
    return test_json(t)


def create_test(data):
    p = current_principal()
    require_manage(p)
    d = validate(data, TEST_SCHEMA)
    t = LabTest(health_center_id=p.center_id)
    for k in TEST_FIELDS:
        setattr(t, k, d.get(k))
    _check_test(p, t)
    db.session.add(t)
    db.session.commit()
    return test_json(t)


def update_test(tid, data):
    p = current_principal()
    require_manage(p)
    t = _get_test(p, tid)
    check_version(t, data.get("version"))
    d = validate(data, TEST_SCHEMA, partial=True)
    for k in ("code", "name", "result_type", "is_active", "sort_order"):
        if k in d and d[k] is None:
            raise ValidationError("Invalid input", details={k: "is required"})
    for k, v in d.items():
        setattr(t, k, v)
    with db.session.no_autoflush:
        _check_test(p, t)
    db.session.commit()
    return test_json(t)


def delete_test(tid):
    p = current_principal()
    require_manage(p)
    t = _get_test(p, tid)
    return deletion.stage(p, t, "lab_test", f"{t.code} {t.name}")


def active_tests_by_id(p, ids):
    rows = db.session.execute(
        select(LabTest, LabTestCategory.name)
        .outerjoin(LabTestCategory, (LabTestCategory.id == LabTest.category_id)
                   & (LabTestCategory.health_center_id == LabTest.health_center_id))
        .where(p.tenant(LabTest), LabTest.live(), LabTest.is_active.is_(True), LabTest.id.in_(ids))).all()
    return {t.id: (t, cn) for t, cn in rows}
