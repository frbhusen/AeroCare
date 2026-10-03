"""Patient business logic: registration, search, duplicate lookup, linking, editing, deletion and
the "departments with records" indicator.

Scope rules (docs/PERMISSIONS.md): a patient is visible when linked to an accessible clinic
(`principal.patient_clause`); center-wide principals see every patient. Out of scope -> 404.
"""
import re
from datetime import date

from sqlalchemy import case, func, literal, or_, select

from backend.app.core.api import check_version, page_params
from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso, local_today
from backend.app.core.validation import (Date, Enum, Id, PHONE_RE, Str, Text, validate)
from backend.app.extensions import db
from backend.app.models.clinical import BLOOD_TYPES, GENDERS
from backend.app.models import (Patient, PatientClinicLink, PatientDepartmentLink, StoredFile,
                                Visit)
from backend.app.schema import register_sql
from backend.app.services import deletion
from backend.app.services.centers import next_sequence
from backend.app.services.clinical import (format_patient_code, get_clinic, get_patient, link_patient_to_clinic,
                                           normalize_name, phone_digits)

from .helpers import department_info, like_escape

# Prefix searches for very short (1-2 character) name queries, which trigram indexes cannot serve.
register_sql("patients_search_prefix", """
CREATE INDEX IF NOT EXISTS ix_patients_center_search_prefix
  ON patients (health_center_id, search_name text_pattern_ops);
""")

def _before_patient_purge(pt):
    """Detach visit references first: the core composite FKs (health_center_id, visit_id) are
    ON DELETE SET NULL, which would null health_center_id when cascaded visits are deleted."""
    from sqlalchemy import update as sa_update
    from backend.app.models import Prescription
    db.session.execute(sa_update(StoredFile).where(StoredFile.patient_id == pt.id).values(visit_id=None))
    db.session.execute(sa_update(Prescription).where(Prescription.patient_id == pt.id).values(visit_id=None))
    db.session.flush()


deletion.register("patient", Patient, files=lambda obj: StoredFile.patient_id == obj.id,
                  before_purge=_before_patient_purge)

PROFILE_FIELDS = ("full_name", "date_of_birth", "gender", "phone", "address", "blood_type", "allergies",
                  "chronic_conditions", "medications", "general_notes")
LINK_TABLES = {"patients", "patient_clinic_links", "patient_department_links"}


def _dob(v):
    if v is None:
        return None
    if v > local_today():
        raise ValidationError("Invalid input", details={"date_of_birth": "cannot be in the future"})
    if v < date(1900, 1, 1):
        raise ValidationError("Invalid input", details={"date_of_birth": "is too far in the past"})
    return v


def profile_schema():
    # full_name is "required" even for partial updates: partial skips absent keys, but a present
    # key must not be blank.
    return {
        "full_name": Str(required=True, min_len=2, max_len=200),
        "date_of_birth": Date(),
        "gender": Enum(GENDERS),
        "phone": Str(max_len=40, pattern=PHONE_RE),
        "address": Str(max_len=300),
        "blood_type": Enum(BLOOD_TYPES),
        "allergies": Text(max_len=5000),
        "chronic_conditions": Text(max_len=5000),
        "medications": Text(max_len=5000),
        "general_notes": Text(max_len=10000),
    }


# ------------------------------------------------------------------ serialization
def patient_brief(pt):
    return {"id": pt.id, "code": pt.code, "display_code": pt.display_code, "full_name": pt.full_name,
            "date_of_birth": iso(pt.date_of_birth), "gender": pt.gender, "phone": pt.phone}


def patient_json(pt):
    out = patient_brief(pt)
    out.update({"address": pt.address, "blood_type": pt.blood_type, "allergies": pt.allergies,
                "chronic_conditions": pt.chronic_conditions, "medications": pt.medications,
                "general_notes": pt.general_notes, "created_at": iso(pt.created_at),
                "updated_at": iso(pt.updated_at), "version": pt.version})
    return out


def mask_phone(phone):
    d = phone_digits(phone) or ""
    if not d:
        return None
    if len(d) <= 3:
        return "*" * len(d)
    return "*" * (len(d) - 3) + d[-3:]


# ------------------------------------------------------------------ search
_PHONE_TOKEN = re.compile(r"[+\d()\-]+")


def search_terms(q):
    """Split a query into normalized name terms and phone digit terms."""
    names, phones = [], []
    for tok in (q or "").split()[:8]:
        digits = re.sub(r"\D", "", tok)
        if _PHONE_TOKEN.fullmatch(tok) and len(digits) >= 3:
            phones.append(digits)
        else:
            t = normalize_name(tok)
            if t:
                names.append(t)
    return names, phones


def search_filter(q):
    """(where-clauses, order-by) implementing name/phone search. Name terms are ANDed substring
    matches on the normalized name (trigram GIN index); 1-2 character single-term queries use a
    word-prefix match. Ordered by relevance: whole-name prefix, trigram similarity, newest."""
    names, phones = search_terms(q)
    if not names and not phones:
        raise ValidationError("Enter a name or phone number to search.", details={"q": "is too short"})
    conds, order = [], []
    for t in names:
        e = like_escape(t)
        if len(t) < 3:
            conds.append(or_(Patient.search_name.like(f"{e}%", escape="\\"),
                             Patient.search_name.like(f"% {e}%", escape="\\")))
        else:
            conds.append(Patient.search_name.like(f"%{e}%", escape="\\"))
    for d in phones:
        conds.append(Patient.phone_digits.like(f"%{d}%"))
    if names:
        full = " ".join(names)
        order += [case((Patient.search_name.like(f"{like_escape(full)}%", escape="\\"), 0), else_=1),
                  func.similarity(Patient.search_name, full).desc()]
    if phones:
        order.append(case((Patient.phone_digits.like(f"{phones[0]}%"), 0), else_=1))
    order.append(Patient.id.desc())
    return conds, order


def _page(stmt, serialize):
    """Pagination without COUNT(*): fetch one extra row to compute has_more (fast on 100k+ rows)."""
    page, per_page = page_params(25)
    rows = db.session.execute(stmt.limit(per_page + 1).offset((page - 1) * per_page)).scalars().all()
    return {"items": [serialize(r) for r in rows[:per_page]], "page": page, "per_page": per_page,
            "has_more": len(rows) > per_page, "total": None}


def list_patients(p, args):
    p.require("patients.view")
    a = validate(args, {"q": Str(max_len=100), "clinic_id": Id(), "department_id": Id()})
    stmt = select(Patient).where(p.tenant(Patient), Patient.live(), p.patient_clause(Patient.id))
    if a.get("clinic_id"):
        p.require(clinic_id=a["clinic_id"])
        stmt = stmt.where(Patient.id.in_(select(PatientClinicLink.patient_id).where(
            PatientClinicLink.clinic_id == a["clinic_id"])))
    if a.get("department_id"):
        p.require(department_id=a["department_id"])
        if not p.center_wide and not p.can_department(a["department_id"]):
            # Clinic-level staff: only patients of their own clinics in that department.
            clinics = [c for c, d in p.clinic_department.items() if d == a["department_id"]] or [-1]
            stmt = stmt.where(Patient.id.in_(select(PatientClinicLink.patient_id).where(
                PatientClinicLink.clinic_id.in_(clinics))))
        else:
            stmt = stmt.where(Patient.id.in_(select(PatientDepartmentLink.patient_id).where(
                PatientDepartmentLink.department_id == a["department_id"])))
    if a.get("q"):
        conds, order = search_filter(a["q"])
        stmt = stmt.where(*conds).order_by(*order)
    else:
        stmt = stmt.order_by(Patient.created_at.desc(), Patient.id.desc())
    return _page(stmt, patient_brief)


def lookup(p, args):
    """Center-wide duplicate check before registering: minimal identity only (decision 2026-10-03)."""
    p.require("patients.create")
    a = validate(args, {"q": Str(required=True, max_len=100), "date_of_birth": Date()})
    conds, order = search_filter(a["q"])
    stmt = select(Patient).where(p.tenant(Patient), Patient.live(), *conds)
    if a.get("date_of_birth"):
        stmt = stmt.where(Patient.date_of_birth == a["date_of_birth"])
    rows = db.session.execute(stmt.order_by(*order).limit(10)).scalars().all()
    visible = set()
    if rows:
        visible = set(db.session.execute(select(Patient.id).where(
            Patient.id.in_([r.id for r in rows]), p.patient_clause(Patient.id))).scalars())
    return {"items": [{"id": r.id, "code": r.code, "display_code": r.display_code, "full_name": r.full_name,
                       "date_of_birth": iso(r.date_of_birth), "gender": r.gender, "phone_masked": mask_phone(r.phone),
                       "accessible": r.id in visible} for r in rows]}


# ------------------------------------------------------------------ create / edit / link
def create_patient(p, body):
    schema = profile_schema()
    schema["clinic_id"] = Id(required=True)
    data = validate(body, schema)
    clinic_id = data.pop("clinic_id")
    p.require("patients.create", clinic_id=clinic_id)
    clinic = get_clinic(p, clinic_id)
    data["date_of_birth"] = _dob(data.get("date_of_birth"))
    code = next_sequence(p.center_id, "patient_seq")
    pt = Patient(health_center_id=p.center_id, code=code, created_by=p.user.id)
    _apply_profile(pt, data)
    db.session.add(pt)
    db.session.flush()
    link_patient_to_clinic(p.center_id, pt.id, clinic.id, clinic.department_id)
    db.session.commit()
    return pt


def _apply_profile(pt, data):
    for k in PROFILE_FIELDS:
        if k in data:
            setattr(pt, k, data[k])
    if "full_name" in data:
        pt.search_name = normalize_name(pt.full_name)
    if "phone" in data:
        pt.phone_digits = phone_digits(pt.phone)


def update_patient(p, patient_id, body):
    pt = get_patient(p, patient_id, perm="patients.edit")
    schema = profile_schema()
    schema["version"] = Id(required=True)
    data = validate(body, schema, partial=True)
    check_version(pt, data.pop("version", None))
    if "date_of_birth" in data:
        data["date_of_birth"] = _dob(data["date_of_birth"])
    _apply_profile(pt, data)
    db.session.commit()
    return pt


def link_to_clinic(p, patient_id, body):
    """Link an existing center patient (found via lookup) to a clinic in the caller's scope."""
    data = validate(body, {"clinic_id": Id(required=True)})
    p.require("patients.create", clinic_id=data["clinic_id"])
    clinic = get_clinic(p, data["clinic_id"])
    pt = db.session.execute(select(Patient).where(Patient.id == patient_id, p.tenant(Patient), Patient.live())
                            ).scalar_one_or_none()
    if pt is None:
        raise NotFound("Patient not found")
    link_patient_to_clinic(p.center_id, pt.id, clinic.id, clinic.department_id)
    db.session.commit()
    return pt


# ------------------------------------------------------------------ delete
def history_tables(patient_id):
    """Names of tables (core + every module) holding rows for this patient, other than links.
    Any table with a `patient_id` column counts as history (visits, records, files,
    prescriptions, appointments, invoices, ...), so new modules are covered automatically."""
    found = []
    for table in db.metadata.sorted_tables:
        if table.name in LINK_TABLES or "patient_id" not in table.c:
            continue
        hit = db.session.execute(select(literal(1)).select_from(table).where(table.c.patient_id == patient_id)
                                 .limit(1)).first()
        if hit:
            found.append(table.name)
    return found


def delete_patient(p, patient_id):
    pt = get_patient(p, patient_id, perm="patients.delete")
    if not p.center_wide:
        outside = db.session.execute(select(PatientClinicLink.id).where(
            PatientClinicLink.patient_id == pt.id, PatientClinicLink.clinic_id.notin_(sorted(p.clinic_ids) or [-1]))
            .limit(1)).first()
        if outside:
            raise Forbidden("This patient is also registered in clinics outside your scope. "
                            "Ask the health center manager to delete the profile.", code="patient_outside_scope")
    history = history_tables(pt.id)
    if history:
        p.require("patients.delete_with_history")
    return deletion.stage(p, pt, "patient", f"{pt.display_code} {pt.full_name}")


# ------------------------------------------------------------------ departments indicator
def departments_indicator(p, pt):
    """Departments where the patient has a record/relationship. Accessible ones carry the
    accessible clinics and visit counts; restricted ones only carry the department identity."""
    dept_ids = list(db.session.execute(select(PatientDepartmentLink.department_id).where(
        PatientDepartmentLink.patient_id == pt.id, p.tenant(PatientDepartmentLink))).scalars())
    info = department_info(p.center_id, dept_ids)
    linked_clinics = list(db.session.execute(select(PatientClinicLink.clinic_id).where(
        PatientClinicLink.patient_id == pt.id, p.tenant(PatientClinicLink))).scalars())
    accessible_clinics = [c for c in linked_clinics if p.can_clinic(c)]
    counts = dict(db.session.execute(
        select(Visit.clinic_id, func.count()).where(Visit.patient_id == pt.id, p.tenant(Visit), Visit.live(),
                                                    p.clinic_clause(Visit.clinic_id)).group_by(Visit.clinic_id)).all())
    from .helpers import clinic_names
    names = clinic_names(p.center_id, accessible_clinics)
    out = []
    for d in sorted(dept_ids, key=lambda x: (info.get(x, {}).get("name") or "")):
        i = info.get(d, {})
        clinics = [c for c in accessible_clinics if p.clinic_department.get(c) == d]
        accessible = bool(clinics) and p.sees_department(d)
        row = {"department_id": d, "name": i.get("name"), "type_code": i.get("type_code"),
               "environment": i.get("environment"), "color": i.get("color"), "accessible": accessible}
        if accessible:
            row["clinics"] = [{"clinic_id": c, "name": names.get(c), "visit_count": int(counts.get(c, 0))}
                              for c in clinics]
            row["visit_count"] = sum(int(counts.get(c, 0)) for c in clinics)
        out.append(row)
    return out


def patient_detail(p, pt):
    out = patient_json(pt)
    out["departments"] = departments_indicator(p, pt)
    out["permissions"] = {k: p.has(k) for k in ("patients.edit", "patients.delete", "patients.delete_with_history",
                                                "medical_records.view", "medical_records.create", "files.view",
                                                "files.upload", "billing.view")}
    return out


__all__ = ["format_patient_code", "get_patient"]
