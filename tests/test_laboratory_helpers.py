"""Shared setup helpers for laboratory/radiology tests (no test functions here)."""
import random

from backend.app.core import tenancy
from backend.app.extensions import db
from backend.app.models import Department, Patient, User, Visit
from backend.app.services.accounts import create_user_record
from backend.app.services.clinical import link_patient_to_clinic, normalize_name

from tests.conftest import PASSWORD

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(64)


def make_patient(app, center, *clinic_keys, name="Ali Hasan", gender="male"):
    with app.app_context(), tenancy.scoped("platform"):
        cid = center["center_id"]
        pt = Patient(health_center_id=cid, code=random.randint(1, 10**8), full_name=name,
                     search_name=normalize_name(name), gender=gender)
        db.session.add(pt)
        db.session.flush()
        for k in clinic_keys:
            link_patient_to_clinic(cid, pt.id, center["clinics"][k])
        db.session.commit()
        return pt.id


def make_dept_manager(app, center, dept_code, key):
    with app.app_context(), tenancy.scoped("platform"):
        dept_id = center["departments"][dept_code]
        u = create_user_record(center_id=center["center_id"], username=f"{key}.{center['tag']}", name=key,
                               role="department_manager", password=PASSWORD, department_id=dept_id)
        db.session.flush()
        db.session.get(Department, dept_id).head_user_id = u.id
        db.session.commit()
        return {"id": u.id, "email": u.email}


def make_visit(app, center, patient_id, clinic_key):
    with app.app_context(), tenancy.scoped("platform"):
        from backend.app.core.timeutil import utcnow
        clinic_id = center["clinics"][clinic_key]
        from backend.app.models import Clinic
        dept = db.session.get(Clinic, clinic_id).department_id
        v = Visit(health_center_id=center["center_id"], patient_id=patient_id, department_id=dept,
                  clinic_id=clinic_id, visit_at=utcnow(), visit_type="consultation", author_name="x")
        db.session.add(v)
        db.session.commit()
        return v.id


def principal_for(center, user_key_or_dict):
    user = center["users"][user_key_or_dict] if isinstance(user_key_or_dict, str) else user_key_or_dict
    from backend.app.authz.principal import build_principal
    return build_principal(db.session.get(User, user["id"]))


def notifications(client, type_):
    r = client.get("/api/v1/notifications")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    items = body["items"] if isinstance(body, dict) else body
    return [n for n in items if n["type"] == type_]
