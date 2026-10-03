"""`flask --app backend.wsgi dev seed-demo`: a demo health center with all 11 department modules,
a few clinics and one account of every role. No medical data is created. Development only."""
from datetime import timedelta

from sqlalchemy import select

from backend.app.core import tenancy
from backend.app.core.timeutil import utcnow
from backend.app.extensions import db
from backend.app.models import Clinic, Department, DepartmentType, HealthCenter, UserScope
from backend.app.services.accounts import create_user_record
from backend.app.services.centers import create_center

CLINICS = {
    "dentistry": ["Dental Clinic 1", "Dental Clinic 2"], "general_medicine": ["General Clinic"],
    "dermatology": ["Dermatology Clinic", "Laser Room"], "pediatrics": ["Pediatrics Clinic"],
    "cardiology": ["Cardiology Clinic"], "ophthalmology": ["Eye Clinic"], "neurology": ["Neurology Clinic"],
    "nutrition": ["Nutrition Clinic"], "laboratory": ["Main Laboratory"], "pharmacy": ["Main Pharmacy"],
    "radiology": ["Radiology Unit"],
}


def seed_demo_center(password, name="Demo Health Center"):
    """Create the demo center and return printable lines with the login emails."""
    from backend.app.auth.service import validate_password
    validate_password(password)
    with tenancy.scoped("platform"):
        types = {t.code: t for t in db.session.execute(select(DepartmentType)).scalars()}
        codes = [c for c in CLINICS if c in types]
        c = create_center(name=name, plan_code="enterprise", module_codes=codes)
        c.status, c.subscription_ends_at = "active", utcnow() + timedelta(days=365)
        cid = c.id
        depts, clinics = {}, {}
        for code in codes:
            d = Department(health_center_id=cid, department_type_id=types[code].id, name=types[code].name_en)
            db.session.add(d)
            db.session.flush()
            depts[code] = d
            for i, cname in enumerate(CLINICS[code]):
                cl = Clinic(health_center_id=cid, department_id=d.id, name=cname, location=f"Room {len(clinics) + 101}",
                            working_hours={day: [["09:00", "17:00"]] for day in ("sat", "sun", "mon", "tue", "wed", "thu")})
                db.session.add(cl)
                db.session.flush()
                clinics[(code, i)] = cl

        lines = [f"Demo health center '{c.name}' (id {cid}, slug {c.slug}) created. Accounts (password as given):"]

        def user(username, label, role, **kw):
            u = create_user_record(center_id=cid, username=username, name=label, role=role, password=password, **kw)
            lines.append(f"  {role:<19} {label:<28} {u.email}")
            return u

        user("manager", "Center Manager", "center_manager")
        head = user("dent.head", "Head Dentist", "department_manager", department_id=depts["dentistry"].id,
                    clinic_id=clinics[("dentistry", 0)].id)
        depts["dentistry"].head_user_id = head.id
        lab_head = user("lab.head", "Head of Laboratory", "department_manager", department_id=depts["laboratory"].id)
        depts["laboratory"].head_user_id = lab_head.id
        for (code, i), cl in clinics.items():
            user(f"dr.{code.replace('_', '.')}.{i + 1}", f"Dr. {cl.name}", "doctor", clinic_id=cl.id)
        rec_c = user("reception", "Front Desk (center)", "receptionist")
        rec_d = user("reception.dental", "Dental Reception", "receptionist")
        rec_k = user("reception.derm", "Dermatology Desk (clinic)", "receptionist")
        for u, d_id, c_id in ((rec_c, None, None), (rec_d, depts["dentistry"].id, None),
                              (rec_k, None, clinics[("dermatology", 0)].id)):
            db.session.add(UserScope(health_center_id=cid, user_id=u.id, department_id=d_id, clinic_id=c_id))
        db.session.commit()
    lines.append("Superadmin accounts are created with: flask --app backend.wsgi admin create-superadmin")
    return lines
