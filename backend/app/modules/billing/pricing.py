"""Services catalog and price overrides.

Visibility: a center-wide service (department NULL) is visible to everyone with billing.view;
a department service to principals that see that department; a clinic service to principals with
that clinic. Management (services.manage): center-wide services need center-wide scope, department
services need department-level access, clinic services need the clinic.

Effective price for a clinic: clinic override -> department override -> service.price.
"""
from decimal import Decimal

from sqlalchemy import or_, select

from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.extensions import db
from backend.app.models import Clinic, Department
from .models import Service, ServicePrice

CENTS = Decimal("0.01")


def money(v):
    return (Decimal(str(v)) if v is not None else Decimal("0")).quantize(CENTS)


def m(v):
    """Serialize money."""
    return None if v is None else str(money(v))


def visible_clause(p):
    dept_ok = or_(Service.department_id.is_(None), p.department_clause(Service.department_id))
    clinic_ok = or_(Service.clinic_id.is_(None), p.clinic_clause(Service.clinic_id))
    return p.tenant(Service) & Service.live() & dept_ok & clinic_ok


def applicable_clause(clinic):
    """Services usable on an invoice for `clinic`."""
    return (or_(Service.department_id.is_(None), Service.department_id == clinic.department_id)
            & or_(Service.clinic_id.is_(None), Service.clinic_id == clinic.id))


def get_service(p, service_id):
    s = db.session.execute(select(Service).where(Service.id == service_id, visible_clause(p))).scalar_one_or_none()
    if s is None:
        raise NotFound("Service not found")
    return s


def require_manage(p, department_id, clinic_id):
    """services.manage + scope for the service level."""
    if clinic_id is not None:
        p.require("services.manage", clinic_id=clinic_id)
    elif department_id is not None:
        p.require("services.manage", department_id=department_id, department_level=True)
    else:
        p.require("services.manage")
        if not p.center_wide:
            raise Forbidden("Only center-wide staff can manage center-wide services.")


def _scoped_clinic(p, clinic_id):
    c = db.session.execute(select(Clinic).where(Clinic.id == clinic_id, p.tenant(Clinic), Clinic.live())
                           ).scalar_one_or_none()
    if c is None or not p.can_clinic(c.id):
        raise NotFound("Clinic not found")
    return c


def _scoped_department(p, department_id):
    d = db.session.execute(select(Department).where(Department.id == department_id, p.tenant(Department),
                                                    Department.live())).scalar_one_or_none()
    if d is None or not p.sees_department(d.id):
        raise NotFound("Department not found")
    return d


def resolve_level(p, department_id, clinic_id):
    """Validate the (department, clinic) level; returns (department_id, clinic_id)."""
    if clinic_id is not None:
        c = _scoped_clinic(p, clinic_id)
        if department_id is not None and department_id != c.department_id:
            raise ValidationError("Clinic does not belong to that department",
                                  details={"clinic_id": "does not belong to department"})
        return c.department_id, c.id
    if department_id is not None:
        _scoped_department(p, department_id)
    return department_id, None


SERVICE_FIELDS = ("name", "category", "kind", "cost", "price", "duration_minutes", "is_active", "notes")


def create_service(p, data):
    dept_id, clinic_id = resolve_level(p, data.get("department_id"), data.get("clinic_id"))
    require_manage(p, dept_id, clinic_id)
    s = Service(health_center_id=p.center_id, department_id=dept_id, clinic_id=clinic_id)
    for f in SERVICE_FIELDS:
        if f in data and data[f] is not None:
            setattr(s, f, data[f])
    if s.is_active is None:
        s.is_active = True
    db.session.add(s)
    db.session.commit()
    return s


def update_service(p, s, data):
    require_manage(p, s.department_id, s.clinic_id)
    for f in SERVICE_FIELDS:
        if f in data:
            if f in ("name", "price", "kind", "is_active") and data[f] is None:
                raise ValidationError("Invalid input", details={f: "is required"})
            setattr(s, f, data[f])
    db.session.commit()
    return s


# ---------------------------------------------------------------- prices
def effective_price(service, clinic):
    """(price, source) for `service` billed in `clinic`."""
    rows = db.session.execute(select(ServicePrice).where(
        ServicePrice.health_center_id == service.health_center_id, ServicePrice.service_id == service.id,
        or_(ServicePrice.clinic_id == clinic.id, ServicePrice.department_id == clinic.department_id))).scalars().all()
    by_clinic = next((r for r in rows if r.clinic_id == clinic.id), None)
    if by_clinic:
        return money(by_clinic.price), "clinic"
    by_dept = next((r for r in rows if r.department_id == clinic.department_id), None)
    if by_dept:
        return money(by_dept.price), "department"
    return money(service.price), "service"


def effective_prices(services, clinic):
    """Bulk version: {service_id: (price, source)}."""
    ids = [s.id for s in services]
    if not ids:
        return {}
    rows = db.session.execute(select(ServicePrice).where(
        ServicePrice.service_id.in_(ids),
        or_(ServicePrice.clinic_id == clinic.id, ServicePrice.department_id == clinic.department_id))).scalars().all()
    clin = {r.service_id: r.price for r in rows if r.clinic_id == clinic.id}
    dept = {r.service_id: r.price for r in rows if r.department_id == clinic.department_id}
    out = {}
    for s in services:
        if s.id in clin:
            out[s.id] = (money(clin[s.id]), "clinic")
        elif s.id in dept:
            out[s.id] = (money(dept[s.id]), "department")
        else:
            out[s.id] = (money(s.price), "service")
    return out


def list_prices(p, s):
    rows = db.session.execute(select(ServicePrice).where(
        ServicePrice.service_id == s.id, p.tenant(ServicePrice),
        or_(ServicePrice.clinic_id.is_(None), p.clinic_clause(ServicePrice.clinic_id)),
        or_(ServicePrice.department_id.is_(None), p.department_clause(ServicePrice.department_id)))
        .order_by(ServicePrice.id)).scalars().all()
    return rows


def set_price(p, s, data):
    """Upsert an override for a department or clinic (exactly one)."""
    dept_id, clinic_id = data.get("department_id"), data.get("clinic_id")
    if (dept_id is None) == (clinic_id is None):
        raise ValidationError("Give exactly one of department_id or clinic_id",
                              details={"clinic_id": "exactly one of department_id/clinic_id"})
    if clinic_id is not None:
        c = _scoped_clinic(p, clinic_id)
        p.require("services.manage", clinic_id=c.id)
        if (s.clinic_id and s.clinic_id != c.id) or (s.department_id and s.department_id != c.department_id):
            raise ValidationError("Service is not available in that clinic", details={"clinic_id": "not applicable"})
        cond = ServicePrice.clinic_id == c.id
    else:
        _scoped_department(p, dept_id)
        p.require("services.manage", department_id=dept_id, department_level=True)
        if s.clinic_id or (s.department_id and s.department_id != dept_id):
            raise ValidationError("Service is not available in that department",
                                  details={"department_id": "not applicable"})
        cond = ServicePrice.department_id == dept_id
    row = db.session.execute(select(ServicePrice).where(ServicePrice.service_id == s.id, p.tenant(ServicePrice),
                                                        cond).with_for_update()).scalar_one_or_none()
    if row is None:
        row = ServicePrice(health_center_id=p.center_id, service_id=s.id, department_id=dept_id,
                           clinic_id=clinic_id)
        db.session.add(row)
    row.price = data["price"]
    db.session.commit()
    return row


def delete_price(p, s, price_id):
    row = db.session.execute(select(ServicePrice).where(ServicePrice.id == price_id, ServicePrice.service_id == s.id,
                                                        p.tenant(ServicePrice))).scalar_one_or_none()
    if row is None:
        raise NotFound("Price override not found")
    if row.clinic_id is not None:
        p.require("services.manage", clinic_id=row.clinic_id)
    else:
        p.require("services.manage", department_id=row.department_id, department_level=True)
    db.session.delete(row)
    db.session.commit()


def list_services(p, args):
    stmt = select(Service).where(visible_clause(p))
    clinic = None
    if args.get("clinic_id"):
        clinic = _scoped_clinic(p, args["clinic_id"])
        stmt = stmt.where(applicable_clause(clinic))
    elif args.get("department_id"):
        stmt = stmt.where(Service.department_id == args["department_id"])
    if args.get("level") == "center":
        stmt = stmt.where(Service.department_id.is_(None))
    if args.get("active") is not None:
        stmt = stmt.where(Service.is_active.is_(args["active"]))
    if args.get("category"):
        stmt = stmt.where(Service.category == args["category"])
    if args.get("q"):
        stmt = stmt.where(Service.name.ilike("%" + args["q"].replace("%", r"\%").replace("_", r"\_") + "%"))
    return stmt.order_by(Service.name, Service.id), clinic


def categories(p):
    return sorted(c for c in db.session.execute(select(Service.category).where(
        visible_clause(p), Service.category.isnot(None)).distinct()).scalars() if c)


def serialize_service(s, eff=None):
    out = {"id": s.id, "name": s.name, "category": s.category, "kind": s.kind, "department_id": s.department_id,
           "clinic_id": s.clinic_id, "cost": m(s.cost), "price": m(s.price), "duration_minutes": s.duration_minutes,
           "is_active": s.is_active, "notes": s.notes, "version": s.version,
           "level": "clinic" if s.clinic_id else ("department" if s.department_id else "center")}
    if eff is not None:
        out["effective_price"], out["price_source"] = str(eff[0]), eff[1]
    return out


def serialize_price(r):
    return {"id": r.id, "service_id": r.service_id, "department_id": r.department_id, "clinic_id": r.clinic_id,
            "price": m(r.price), "level": "clinic" if r.clinic_id else "department", "version": r.version}


