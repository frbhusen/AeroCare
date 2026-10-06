"""/api/v1/billing — services & pricing, invoices, payments, financial history, summaries,
invoice/receipt PDFs and document templates. Thin routes; logic lives in service/pricing/summary."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.api import page_params, paginate
from backend.app.core.errors import ValidationError
from backend.app.core.timeutil import local_day_bounds
from backend.app.core.validation import (COLOR_RE, Bool, Date, DateTime, Enum, Id, Int, JsonDict, List, Money, Num,
                                         Obj, Str, Text, query_args, request_json, validate)
from backend.app.extensions import db
from backend.app.services import deletion, documents
from . import pricing, printing, service, sources, summary as summary_svc, templates
from .models import (INVOICE_STATUSES, ITEM_KINDS, PAYMENT_METHODS, TEMPLATE_KINDS, DocumentTemplate, Invoice,
                     InvoiceItem, Service)

bp = Blueprint("billing", __name__, url_prefix="/billing")


def _null_service_refs(svc):
    db.session.execute(InvoiceItem.__table__.update().where(
        InvoiceItem.service_id == svc.id, InvoiceItem.health_center_id == svc.health_center_id).values(service_id=None))


deletion.register("billing_service", Service, before_purge=_null_service_refs)
deletion.register("invoice", Invoice)
deletion.register("document_template", DocumentTemplate)
sources.register_summary()


def _lang():
    return "ar" if request.args.get("lang") == "ar" else "en"


def _range(args):
    start = local_day_bounds(args["date_from"])[0] if args.get("date_from") else None
    end = local_day_bounds(args["date_to"])[1] if args.get("date_to") else None
    if start and end and end <= start:
        raise ValidationError("Invalid date range", details={"date_to": "must be on or after date_from"})
    return start, end


@bp.get("/meta")
@login_required(perm="billing.view")
def meta():
    from backend.app.models import HealthCenter
    p = current_principal()
    c = db.session.get(HealthCenter, p.center_id)
    return jsonify({"currency": c.currency, "invoice_statuses": list(INVOICE_STATUSES), "item_kinds": list(ITEM_KINDS),
                    "payment_methods": list(PAYMENT_METHODS), "template_kinds": list(TEMPLATE_KINDS),
                    "categories": pricing.categories(p), "summary_groups": list(summary_svc.GROUPS),
                    "can": {k: p.has(k) for k in ("billing.view", "billing.create", "billing.edit", "billing.delete",
                                                  "services.manage", "settings.edit")}})


@bp.get("/doctors")
@login_required(perm="billing.view")
def doctors():
    """Doctors selectable on an invoice for a clinic: its doctors + its department's manager."""
    from sqlalchemy import or_, select
    from backend.app.models import User
    p = current_principal()
    args = query_args({"clinic_id": Id(required=True)})
    clinic = pricing._scoped_clinic(p, args["clinic_id"])
    rows = db.session.execute(select(User.id, User.name, User.role).where(
        User.health_center_id == p.center_id, User.status == "active",
        or_((User.role == "doctor") & (User.clinic_id == clinic.id),
            (User.role == "department_manager") & (User.department_id == clinic.department_id)))
        .order_by(User.name)).all()
    return jsonify({"items": [{"id": i, "name": n, "role": r} for i, n, r in rows]})


# ---------------------------------------------------------------- services
SERVICE_SCHEMA = {
    "name": Str(required=True, max_len=200), "category": Str(max_len=100), "kind": Enum(ITEM_KINDS),
    "cost": Money(), "price": Money(required=True), "duration_minutes": Int(min_value=1, max_value=1440),
    "is_active": Bool(), "notes": Text(max_len=2000), "department_id": Id(), "clinic_id": Id(),
}


@bp.get("/services")
@login_required(perm="billing.view")
def list_services():
    p = current_principal()
    args = query_args({"clinic_id": Id(), "department_id": Id(), "level": Enum(["center"]), "active": Bool(),
                       "category": Str(max_len=100), "q": Str(max_len=100)})
    stmt, clinic = pricing.list_services(p, args)
    out = paginate(db.session, stmt, lambda s: s, default_per_page=50)
    eff = pricing.effective_prices(out["items"], clinic) if clinic else {}
    out["items"] = [pricing.serialize_service(s, eff.get(s.id)) for s in out["items"]]
    return jsonify(out)


@bp.post("/services")
@login_required(perm="services.manage")
def create_service():
    data = validate(request_json(), SERVICE_SCHEMA)
    return jsonify(pricing.serialize_service(pricing.create_service(current_principal(), data))), 201


@bp.get("/services/<int:sid>")
@login_required(perm="billing.view")
def get_service(sid):
    return jsonify(pricing.serialize_service(pricing.get_service(current_principal(), sid)))


@bp.put("/services/<int:sid>")
@login_required(perm="services.manage")
def update_service(sid):
    from backend.app.core.api import check_version
    p = current_principal()
    s = pricing.get_service(p, sid)
    schema = {k: v for k, v in SERVICE_SCHEMA.items() if k not in ("department_id", "clinic_id")}
    schema["version"] = Int(required=True)
    data = validate(request_json(), schema, partial=True)
    check_version(s, data.get("version"))
    return jsonify(pricing.serialize_service(pricing.update_service(p, s, data)))


@bp.delete("/services/<int:sid>")
@login_required(perm="services.manage")
def delete_service(sid):
    p = current_principal()
    s = pricing.get_service(p, sid)
    pricing.require_manage(p, s.department_id, s.clinic_id)
    return jsonify(deletion.stage(p, s, "billing_service", s.name)), 202


@bp.get("/services/<int:sid>/prices")
@login_required(perm="billing.view")
def list_prices(sid):
    p = current_principal()
    s = pricing.get_service(p, sid)
    return jsonify({"items": [pricing.serialize_price(r) for r in pricing.list_prices(p, s)],
                    "service": pricing.serialize_service(s)})


@bp.put("/services/<int:sid>/prices")
@login_required(perm="services.manage")
def set_price(sid):
    p = current_principal()
    s = pricing.get_service(p, sid)
    data = validate(request_json(), {"clinic_id": Id(), "department_id": Id(), "price": Money(required=True)})
    return jsonify(pricing.serialize_price(pricing.set_price(p, s, data)))


@bp.delete("/services/<int:sid>/prices/<int:pid>")
@login_required(perm="services.manage")
def delete_price(sid, pid):
    p = current_principal()
    pricing.delete_price(p, pricing.get_service(p, sid), pid)
    return jsonify({"ok": True})


@bp.get("/services/<int:sid>/effective-price")
@login_required(perm="billing.view")
def effective_price(sid):
    p = current_principal()
    args = query_args({"clinic_id": Id(required=True)})
    s = pricing.get_service(p, sid)
    clinic = pricing._scoped_clinic(p, args["clinic_id"])
    if not db.session.execute(db.select(Service.id).where(Service.id == s.id, pricing.applicable_clause(clinic))
                              ).first():
        raise ValidationError("Service is not available in that clinic", details={"clinic_id": "not applicable"})
    price, source = pricing.effective_price(s, clinic)
    return jsonify({"service_id": s.id, "clinic_id": clinic.id, "price": str(price), "source": source})


# ---------------------------------------------------------------- invoices
ITEM_SCHEMA = {
    "kind": Enum(ITEM_KINDS), "service_id": Id(), "description": Str(max_len=300),
    "qty": Num(min_value="0.01", max_value=100000, places=2), "unit_price": Money(),
    "discount_amount": Money(), "discount_percent": Num(min_value=0, max_value=100, places=2),
    "reference_type": Str(max_len=40, pattern=r"[a-z_]{1,40}"), "reference_id": Id(),
}
INVOICE_SCHEMA = {
    "patient_id": Id(required=True), "clinic_id": Id(required=True), "doctor_user_id": Id(),
    "notes": Text(max_len=4000), "invoice_discount": Money(),
    "items": List(Obj(ITEM_SCHEMA), max_items=200), "issue": Bool(),
}


@bp.get("/invoices")
@login_required(perm="billing.view")
def list_invoices():
    p = current_principal()
    args = query_args({"patient_id": Id(), "clinic_id": Id(), "department_id": Id(), "doctor_user_id": Id(),
                       "status": Str(max_len=100), "date_from": Date(), "date_to": Date(), "q": Str(max_len=100)})
    if args.get("status"):
        sts = [s.strip() for s in args["status"].split(",") if s.strip()]
        bad = [s for s in sts if s not in INVOICE_STATUSES]
        if bad:
            raise ValidationError("Invalid input", details={"status": "unknown status"})
        args["status"] = sts
    args["date_from"], args["date_to"] = _range(args)
    page, per_page = page_params()
    rows, total, sums = service.list_invoices(p, args, page, per_page)
    names = printing.list_names(rows)
    return jsonify({"items": [printing.serialize_invoice(i, brief=True, names=names) for i in rows], "page": page,
                    "per_page": per_page, "total": total, "sums": sums})


@bp.post("/invoices")
@login_required(perm="billing.create")
def create_invoice():
    data = validate(request_json(), INVOICE_SCHEMA)
    inv = service.create_invoice(current_principal(), data)
    return jsonify(printing.serialize_invoice(inv)), 201


@bp.get("/sources/<source_type>/<int:source_id>")
@login_required(perm="billing.view")
def preview_source(source_type, source_id):
    return jsonify(sources.preview_source(current_principal(), source_type, source_id))


@bp.post("/invoices/from-source")
@login_required(perm="billing.create")
def invoice_from_source():
    data = validate(request_json(), {"source_type": Enum(sources.SOURCE_TYPES, required=True),
                                     "source_id": Id(required=True), "clinic_id": Id(), "unit_price": Money(),
                                     "issue": Bool(), "notes": Text(max_len=4000), "allow_duplicate": Bool()})
    inv = sources.create_from_source(current_principal(), data)
    return jsonify(printing.serialize_invoice(inv)), 201


@bp.get("/invoices/<int:iid>")
@login_required(perm="billing.view")
def get_invoice(iid):
    return jsonify(printing.serialize_invoice(service.get_invoice(current_principal(), iid)))


@bp.put("/invoices/<int:iid>")
@login_required(perm="billing.edit")
def update_invoice(iid):
    p = current_principal()
    schema = {k: v for k, v in INVOICE_SCHEMA.items() if k not in ("patient_id", "clinic_id", "issue")}
    schema["version"] = Int(required=True)
    data = validate(request_json(), schema, partial=True)
    inv = service.update_invoice(p, service.get_invoice(p, iid, lock=True), data)
    return jsonify(printing.serialize_invoice(inv))


@bp.post("/invoices/<int:iid>/issue")
@login_required(perm="billing.create")
def issue_invoice(iid):
    p = current_principal()
    data = validate(request_json(), {"version": Int()})
    inv = service.issue_invoice(p, service.get_invoice(p, iid, lock=True), data.get("version"))
    return jsonify(printing.serialize_invoice(inv))


@bp.post("/invoices/<int:iid>/void")
@login_required(perm="billing.edit")
def void_invoice(iid):
    p = current_principal()
    data = validate(request_json(), {"version": Int(), "reason": Str(max_len=300)})
    inv = service.void_invoice(p, service.get_invoice(p, iid, lock=True), data.get("reason"), data.get("version"))
    return jsonify(printing.serialize_invoice(inv))


@bp.delete("/invoices/<int:iid>")
@login_required(perm="billing.delete")
def delete_invoice(iid):
    p = current_principal()
    inv = service.get_invoice(p, iid)
    p.require("billing.delete", clinic_id=inv.clinic_id)
    return jsonify(deletion.stage(p, inv, "invoice", inv.display_number)), 202


@bp.post("/invoices/<int:iid>/payments")
@login_required(perm="billing.create")
def add_payment(iid):
    data = validate(request_json(), {"amount": Money(required=True), "method": Enum(PAYMENT_METHODS),
                                     "paid_at": DateTime(), "notes": Str(max_len=500)})
    inv, pay = service.add_payment(current_principal(), iid, data)
    return jsonify({"payment": printing.serialize_payment(pay, inv), "invoice": printing.serialize_invoice(inv)}), 201


@bp.post("/invoices/<int:iid>/payments/<int:pid>/void")
@login_required(perm="billing.edit")
def void_payment(iid, pid):
    data = validate(request_json(), {"reason": Str(max_len=300)})
    inv, pay = service.void_payment(current_principal(), iid, pid, data.get("reason"))
    return jsonify({"payment": printing.serialize_payment(pay, inv), "invoice": printing.serialize_invoice(inv)})


@bp.get("/invoices/<int:iid>/pdf")
@login_required(perm="billing.view")
def invoice_pdf(iid):
    inv = service.get_invoice(current_principal(), iid)
    return documents.pdf_response(printing.invoice_pdf(inv, _lang()), f"{inv.display_number}.pdf")


@bp.get("/invoices/<int:iid>/receipt")
@login_required(perm="billing.view")
def receipt_pdf(iid):
    args = query_args({"payment_id": Id()})
    inv = service.get_invoice(current_principal(), iid)
    data = printing.receipt_pdf(inv, args.get("payment_id"), _lang())
    return documents.pdf_response(data, f"receipt-{inv.display_number}.pdf")


@bp.get("/patients/<int:patient_id>/history")
@login_required(perm="billing.view")
def patient_history(patient_id):
    p = current_principal()
    patient, invoices, payments, totals = service.patient_history(p, patient_id)
    by_id = {i.id: i for i in invoices}
    names = printing.list_names(invoices)
    return jsonify({"patient": {"id": patient.id, "name": patient.full_name, "code": patient.display_code},
                    "totals": totals, "invoices": [printing.serialize_invoice(i, brief=True, names=names)
                                                   for i in invoices],
                    "payments": [printing.serialize_payment(x, by_id.get(x.invoice_id)) for x in payments]})


@bp.get("/summary")
@login_required(perm="billing.view")
def summary():
    p = current_principal()
    args = query_args({"date_from": Date(), "date_to": Date(), "department_id": Id(), "clinic_id": Id(),
                       "doctor_user_id": Id(), "group_by": Enum(summary_svc.GROUPS)})
    start, end = _range(args)
    out = summary_svc.summary(p, args, start, end)
    out["date_from"] = args["date_from"].isoformat() if args.get("date_from") else None
    out["date_to"] = args["date_to"].isoformat() if args.get("date_to") else None
    return jsonify(out)


# ---------------------------------------------------------------- document templates
TEMPLATE_SCHEMA = {
    "title": Str(max_len=200), "header_text": Text(max_len=2000), "footer_text": Text(max_len=2000),
    "show_logo": Bool(), "accent_color": Str(pattern=COLOR_RE, max_len=7), "extra": JsonDict(max_keys=50),
}


@bp.get("/templates")
@login_required(perm="settings.view")
def list_templates():
    p = current_principal()
    dept = request.args.get("department_id")
    if dept not in (None, "", "center"):
        dept = validate({"d": dept}, {"d": Id()})["d"]
    kind = query_args({"kind": Enum(TEMPLATE_KINDS)}).get("kind")
    return jsonify({"items": [templates.serialize(t) for t in templates.list_templates(p, dept or None, kind)],
                    "kinds": list(TEMPLATE_KINDS)})


@bp.get("/templates/effective")
@login_required(perm="settings.view")
def effective_template():
    args = query_args({"kind": Enum(TEMPLATE_KINDS, required=True), "department_id": Id()})
    return jsonify(templates.effective(current_principal(), args["kind"], args.get("department_id")))


@bp.post("/templates")
@login_required(perm="settings.edit")
def create_template():
    schema = dict(TEMPLATE_SCHEMA, kind=Enum(TEMPLATE_KINDS, required=True), department_id=Id())
    data = validate(request_json(), schema)
    return jsonify(templates.serialize(templates.create(current_principal(), data))), 201


@bp.get("/templates/<int:tid>")
@login_required(perm="settings.view")
def get_template(tid):
    return jsonify(templates.serialize(templates.get(current_principal(), tid)))


@bp.put("/templates/<int:tid>")
@login_required(perm="settings.edit")
def update_template(tid):
    p = current_principal()
    data = validate(request_json(), dict(TEMPLATE_SCHEMA, version=Int(required=True)), partial=True)
    return jsonify(templates.serialize(templates.update(p, templates.get(p, tid), data)))


@bp.delete("/templates/<int:tid>")
@login_required(perm="settings.edit")
def delete_template(tid):
    p = current_principal()
    t = templates.get(p, tid)
    templates.require_level(p, t.department_id, "settings.edit")
    return jsonify(deletion.stage(p, t, "document_template", f"{t.kind} template")), 202


# ------------------------------------------------------------------ packages & installments
@bp.get("/packages")
@login_required(perm="billing.view")
def list_billing_packages():
    from . import packages
    return jsonify(packages.list_packages(current_principal(), request.args.to_dict()))


@bp.post("/packages")
@login_required(perm="billing.create")
def create_billing_package():
    from . import packages
    return jsonify(packages.create_package(current_principal(), request_json())), 201


@bp.post("/packages/<int:package_id>/session")
@login_required(perm="billing.edit")
def record_package_session(package_id):
    from . import packages
    return jsonify(packages.record_session(current_principal(), package_id, request_json()))


@bp.patch("/packages/<int:package_id>")
@login_required(perm="billing.edit")
def update_billing_package(package_id):
    from . import packages
    return jsonify(packages.update_package(current_principal(), package_id, request_json()))

