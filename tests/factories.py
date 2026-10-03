"""Direct-ORM builders for tests (bypass the API to set up worlds quickly).

build_center() returns a dict:
  center_id, departments {code: id}, clinics {"dent1","dent2","derm1","lab1","rad1","gen1","pharm1","oph1"},
  users {"manager","dent_head","dent_doc1","dent_doc2","derm_doc","lab_doc","rad_doc","gen_doc",
         "pharm_doc","oph_doc","rec_dent1"(clinic dent1 only),"rec_dent"(whole dentistry),
         "rec_center"(whole center),"rec_multi"(dentistry + derm1)}
  each user: {"id", "email"}
"""
from sqlalchemy import select

from backend.app.core import tenancy
from backend.app.extensions import db
from backend.app.models import Clinic, Department, DepartmentType, UserScope
from backend.app.services.accounts import create_user_record
from backend.app.services.centers import create_center

from tests.conftest import PASSWORD

MODULES = ["dentistry", "dermatology", "laboratory", "radiology", "general_medicine", "pharmacy", "ophthalmology"]


def build_center(name, tag, modules=MODULES, plan="enterprise"):
    with tenancy.scoped("platform"):
        c = create_center(name=name, plan_code=plan, module_codes=modules)
        cid = c.id
        types = {t.code: t for t in db.session.execute(select(DepartmentType)).scalars()}
        depts = {}
        for code in modules:
            d = Department(health_center_id=cid, department_type_id=types[code].id, name=types[code].name_en)
            db.session.add(d)
            db.session.flush()
            depts[code] = d.id

        def clinic(key, dept_code, cname):
            cl = Clinic(health_center_id=cid, department_id=depts[dept_code], name=cname, location=f"Room {key}")
            db.session.add(cl)
            db.session.flush()
            return cl.id

        clinics = {
            "dent1": clinic("dent1", "dentistry", "Dental Clinic 1"),
            "dent2": clinic("dent2", "dentistry", "Dental Clinic 2"),
            "derm1": clinic("derm1", "dermatology", "Dermatology Clinic 1"),
            "lab1": clinic("lab1", "laboratory", "Laboratory 1"),
            "rad1": clinic("rad1", "radiology", "Radiology 1"),
            "gen1": clinic("gen1", "general_medicine", "General Clinic 1"),
            "pharm1": clinic("pharm1", "pharmacy", "Pharmacy 1"),
            "oph1": clinic("oph1", "ophthalmology", "Eye Clinic 1"),
        }

        def user(key, role, **kw):
            u = create_user_record(center_id=cid, username=f"{key}_{tag}".replace("_", "."), name=f"{key} {tag}",
                                   role=role, password=PASSWORD, **kw)
            return {"id": u.id, "email": u.email}

        users = {
            "manager": user("manager", "center_manager"),
            "dent_head": user("dent_head", "department_manager", department_id=depts["dentistry"],
                              clinic_id=clinics["dent1"]),
            "dent_doc1": user("dent_doc1", "doctor", clinic_id=clinics["dent1"]),
            "dent_doc2": user("dent_doc2", "doctor", clinic_id=clinics["dent2"]),
            "derm_doc": user("derm_doc", "doctor", clinic_id=clinics["derm1"]),
            "lab_doc": user("lab_doc", "doctor", clinic_id=clinics["lab1"]),
            "rad_doc": user("rad_doc", "doctor", clinic_id=clinics["rad1"]),
            "gen_doc": user("gen_doc", "doctor", clinic_id=clinics["gen1"]),
            "pharm_doc": user("pharm_doc", "doctor", clinic_id=clinics["pharm1"]),
            "oph_doc": user("oph_doc", "doctor", clinic_id=clinics["oph1"]),
            "rec_dent1": user("rec_dent1", "receptionist"),
            "rec_dent": user("rec_dent", "receptionist"),
            "rec_center": user("rec_center", "receptionist"),
            "rec_multi": user("rec_multi", "receptionist"),
        }
        db.session.get(Department, depts["dentistry"]).head_user_id = users["dent_head"]["id"]
        for key, dept, clin in [("rec_dent1", None, clinics["dent1"]), ("rec_dent", depts["dentistry"], None),
                                ("rec_center", None, None), ("rec_multi", depts["dentistry"], None),
                                ("rec_multi", None, clinics["derm1"])]:
            db.session.add(UserScope(health_center_id=cid, user_id=users[key]["id"], department_id=dept,
                                     clinic_id=clin))
        db.session.commit()
    return {"center_id": cid, "departments": depts, "clinics": clinics, "users": users, "tag": tag}
