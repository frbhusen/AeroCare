"""Document template CRUD (settings.view to read, settings.edit to change).
Center templates (department_id NULL) need center-wide scope; department templates need
department-level access to that department."""
from sqlalchemy import select

from backend.app.core.api import check_version
from backend.app.core.errors import Forbidden, NotFound
from backend.app.core.timeutil import iso
from backend.app.extensions import db
from backend.app.models import Department
from backend.app.services import documents
from .models import DocumentTemplate

FIELDS = ("title", "header_text", "footer_text", "show_logo", "accent_color", "extra")


def require_level(p, department_id, perm):
    if department_id is None:
        p.require(perm)
        if perm != "settings.view" and not p.center_wide:
            raise Forbidden("Only center-wide staff can edit center templates.")
    else:
        p.require(perm, department_id=department_id, department_level=perm != "settings.view")


def visible_clause(p):
    from sqlalchemy import or_
    return (p.tenant(DocumentTemplate) & DocumentTemplate.live()
            & or_(DocumentTemplate.department_id.is_(None), p.department_clause(DocumentTemplate.department_id)))


def get(p, template_id):
    t = db.session.execute(select(DocumentTemplate).where(DocumentTemplate.id == template_id, visible_clause(p))
                           ).scalar_one_or_none()
    if t is None:
        raise NotFound("Template not found")
    return t


def list_templates(p, department_id=None, kind=None):
    p.require("settings.view")
    stmt = select(DocumentTemplate).where(visible_clause(p))
    if department_id == "center":
        stmt = stmt.where(DocumentTemplate.department_id.is_(None))
    elif department_id:
        stmt = stmt.where(DocumentTemplate.department_id == department_id)
    if kind:
        stmt = stmt.where(DocumentTemplate.kind == kind)
    return db.session.execute(stmt.order_by(DocumentTemplate.kind, DocumentTemplate.department_id.nulls_first())
                              ).scalars().all()


def create(p, data):
    dept_id = data.get("department_id")
    if dept_id is not None:
        d = db.session.execute(select(Department).where(Department.id == dept_id, p.tenant(Department),
                                                        Department.live())).scalar_one_or_none()
        if d is None:
            raise NotFound("Department not found")
    require_level(p, dept_id, "settings.edit")
    t = DocumentTemplate(health_center_id=p.center_id, department_id=dept_id, kind=data["kind"])
    for f in FIELDS:
        if f in data:
            setattr(t, f, data[f])
    if t.extra is None:
        t.extra = {}
    db.session.add(t)
    db.session.commit()
    return t


def update(p, t, data):
    require_level(p, t.department_id, "settings.edit")
    check_version(t, data.get("version"))
    for f in FIELDS:
        if f in data:
            setattr(t, f, data[f] if f != "extra" else (data[f] or {}))
    db.session.commit()
    return t


def effective(p, kind, department_id=None):
    p.require("settings.view")
    if department_id is not None and not p.sees_department(department_id):
        raise NotFound("Department not found")
    return documents.get_template(p.center_id, department_id, kind)


def serialize(t):
    return {"id": t.id, "department_id": t.department_id, "kind": t.kind, "title": t.title,
            "header_text": t.header_text, "footer_text": t.footer_text, "show_logo": t.show_logo,
            "accent_color": t.accent_color, "extra": t.extra or {}, "version": t.version,
            "level": "department" if t.department_id else "center", "updated_at": iso(t.updated_at)}
