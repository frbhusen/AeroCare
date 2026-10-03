"""Shared clinical helpers used by every specialty module (owned by core; stable interface).

    patient = get_patient(p, patient_id)                       # tenant + visibility checked (404 otherwise)
    link_patient_to_clinic(center_id, patient_id, clinic_id)   # idempotent dept + clinic links
    visit = create_visit(p, patient_id=..., clinic_id=..., visit_type="consultation", ...)
    visit = get_visit(p, visit_id, perm="medical_records.view")  # clinic-scoped
    normalize_name("أحمد") / phone_digits("+963 944")          # search normalization
"""
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import utcnow
from backend.app.extensions import db
from backend.app.models import Clinic, Patient, PatientClinicLink, PatientDepartmentLink, Visit

_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def normalize_name(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = _AR_DIACRITICS.sub("", s).translate(_AR_FOLD)
    return re.sub(r"\s+", " ", s).strip()


def phone_digits(s):
    return re.sub(r"\D", "", s or "")[:40] or None


def format_patient_code(code):
    return f"PAT-{code:06d}"


def get_patient(p, patient_id, perm="patients.view"):
    stmt = select(Patient).where(Patient.id == patient_id, p.tenant(Patient), Patient.live(),
                                 p.patient_clause(Patient.id))
    patient = db.session.execute(stmt).scalar_one_or_none()
    if patient is None:
        raise NotFound("Patient not found")
    if perm:
        p.require(perm)
    return patient


def get_clinic(p, clinic_id):
    """Clinic in the principal's scope (404 otherwise)."""
    if not p.can_clinic(clinic_id):
        raise NotFound("Clinic not found")
    c = db.session.execute(select(Clinic).where(Clinic.id == clinic_id, p.tenant(Clinic), Clinic.live())
                           ).scalar_one_or_none()
    if c is None:
        raise NotFound("Clinic not found")
    return c


def link_patient_to_clinic(center_id, patient_id, clinic_id, department_id=None):
    """Idempotent: create patient<->clinic and patient<->department links (race-safe upserts)."""
    if department_id is None:
        department_id = db.session.execute(select(Clinic.department_id).where(Clinic.id == clinic_id)).scalar_one()
    db.session.execute(pg_insert(PatientDepartmentLink).values(
        health_center_id=center_id, patient_id=patient_id, department_id=department_id)
        .on_conflict_do_nothing(index_elements=["patient_id", "department_id"]))
    db.session.execute(pg_insert(PatientClinicLink).values(
        health_center_id=center_id, patient_id=patient_id, clinic_id=clinic_id, department_id=department_id)
        .on_conflict_do_nothing(index_elements=["patient_id", "clinic_id"]))


def require_environment(p, clinic_id, environments):
    """Ensure the clinic belongs to a department of one of the given environments."""
    dept = p.clinic_department.get(clinic_id)
    if dept is None:
        raise NotFound("Clinic not found")
    env = p.department_env.get(dept)
    if env not in (environments if isinstance(environments, (list, tuple, set)) else [environments]):
        raise ValidationError("This clinic does not support this record type.", code="wrong_environment")
    return dept


def create_visit(p, *, patient_id, clinic_id, visit_type="consultation", visit_at=None, title=None, notes=None,
                 appointment_id=None, status="open", environments=None, commit=False):
    """Create an encounter in a clinic within scope. Links the patient to the clinic.
    Does not commit unless commit=True (callers usually add specialty rows first)."""
    p.require("medical_records.create", clinic_id=clinic_id)
    if environments:
        require_environment(p, clinic_id, environments)
    clinic = get_clinic(p, clinic_id)
    # The patient must exist in this center; visibility is granted by the link we create.
    patient = db.session.execute(select(Patient).where(Patient.id == patient_id, p.tenant(Patient), Patient.live())
                                 ).scalar_one_or_none()
    if patient is None:
        raise NotFound("Patient not found")
    link_patient_to_clinic(p.center_id, patient.id, clinic.id, clinic.department_id)
    v = Visit(health_center_id=p.center_id, patient_id=patient.id, department_id=clinic.department_id,
              clinic_id=clinic.id, visit_at=visit_at or utcnow(), visit_type=visit_type, title=title, notes=notes,
              appointment_id=appointment_id, status=status)
    v.set_author(p.user)
    db.session.add(v)
    db.session.flush()
    if commit:
        db.session.commit()
    return v


def get_visit(p, visit_id, perm="medical_records.view"):
    v = db.session.execute(select(Visit).where(Visit.id == visit_id, p.tenant(Visit), Visit.live(),
                                               p.clinic_clause(Visit.clinic_id))).scalar_one_or_none()
    if v is None:
        raise NotFound("Visit not found")
    if perm:
        p.require(perm)
    return v
