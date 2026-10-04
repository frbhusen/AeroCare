"""Fixture data for report tests: a small, fully known data set created directly via the ORM.

All activity is in January 2026 (local Asia/Damascus dates) unless noted. Center A layout comes
from tests/factories.py. Expected numbers are asserted in tests/test_reports_*.py.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from backend.app.core import tenancy
from backend.app.core.timeutil import TZ, local_today
from backend.app.extensions import db

BASE = "/api/v1/reports"
JAN = {"date_from": "2026-01-01", "date_to": "2026-01-31"}


def L(y, m, d, h=10, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def q(params):
    return "&".join(f"{k}={v}" for k, v in params.items())


def seed(app, center, names=None):
    """Creates the standard report data set in `center`; returns a dict of ids."""
    from backend.app.models import Patient, Prescription, UserScope, Visit  # noqa: F401
    from backend.app.modules.appointments.models import Appointment
    from backend.app.modules.billing.models import Invoice, InvoiceItem, Payment
    from backend.app.modules.dentistry.models import Treatment
    from backend.app.modules.inventory.models import InventoryItem, InventoryLocation, StockLot, StockMovement
    from backend.app.modules.laboratory.models import LabRequest, LabRequestItem
    from backend.app.modules.radiology.models import RadiologyStudy
    from backend.app.services.centers import next_sequence
    from backend.app.services.clinical import link_patient_to_clinic, normalize_name

    cid = center["center_id"]
    cl, dp, us = center["clinics"], center["departments"], center["users"]
    names = names or {}
    out = {}
    with app.app_context(), tenancy.scoped("tenant", cid):
        def patient(key, clinic, created, gender=None):
            name = names.get(key, f"Patient {key}")
            pt = Patient(health_center_id=cid, code=next_sequence(cid, "patient_seq"), full_name=name,
                         search_name=normalize_name(name), gender=gender, created_at=created)
            db.session.add(pt)
            db.session.flush()
            link_patient_to_clinic(cid, pt.id, cl[clinic])
            out[key] = pt.id
            return pt.id

        p1 = patient("P1", "dent1", L(2026, 1, 10), "male")
        p2 = patient("P2", "dent2", L(2026, 1, 15), "male")
        p3 = patient("P3", "derm1", L(2026, 1, 20), "female")
        patient("P4", "dent1", L(2025, 12, 31, 23, 30))   # before the range (local date Dec 31)
        p5 = patient("P5", "dent1", L(2026, 1, 31, 23, 30))  # last local minute-ish of the range

        def appt(clinic, dept, doctor, pid, start, status):
            a = Appointment(health_center_id=cid, department_id=dp[dept], clinic_id=cl[clinic],
                            doctor_id=us[doctor]["id"], patient_id=pid, starts_at=start,
                            ends_at=start + timedelta(minutes=30), status=status, author_name="seed")
            db.session.add(a)

        appt("dent1", "dentistry", "dent_doc1", p1, L(2026, 1, 11, 9), "completed")
        appt("dent1", "dentistry", "dent_doc1", p5, L(2026, 1, 12, 9), "no_show")
        appt("dent1", "dentistry", "dent_doc1", p1, L(2026, 1, 13, 9), "cancelled")
        appt("dent2", "dentistry", "dent_doc2", p2, L(2026, 1, 16, 9), "completed")
        appt("derm1", "dermatology", "derm_doc", p3, L(2026, 1, 21, 9), "no_show")
        appt("dent1", "dentistry", "dent_doc1", p1, L(2026, 2, 2, 9), "scheduled")  # outside range

        def visit(clinic, dept, doctor, pid, at):
            v = Visit(health_center_id=cid, patient_id=pid, department_id=dp[dept], clinic_id=cl[clinic],
                      visit_at=at, author_user_id=us[doctor]["id"], author_name=doctor)
            db.session.add(v)

        visit("dent1", "dentistry", "dent_doc1", p1, L(2026, 1, 11, 9, 10))
        visit("dent1", "dentistry", "dent_doc1", p1, L(2026, 1, 14, 9))
        visit("dent1", "dentistry", "dent_doc1", p5, L(2026, 1, 31, 12))
        visit("derm1", "dermatology", "derm_doc", p3, L(2026, 1, 21, 9, 10))

        def treat(clinic, doctor, pid, proc, status, fee, d):
            db.session.add(Treatment(health_center_id=cid, department_id=dp["dentistry"], clinic_id=cl[clinic],
                                     patient_id=pid, procedure=proc, status=status, fee=Decimal(fee),
                                     doctor_user_id=us[doctor]["id"], doctor_name=doctor, date=d,
                                     author_name="seed"))

        treat("dent1", "dent_doc1", p1, "filling", "completed", "100", date(2026, 1, 11))
        treat("dent1", "dent_doc1", p1, "crown", "planned", "300", date(2026, 1, 14))
        treat("dent2", "dent_doc2", p2, "filling", "completed", "50", date(2026, 1, 16))

        def invoice(clinic, dept, doctor, pid, issued, desc, kind, amount, paid):
            amount, paid = Decimal(amount), Decimal(paid)
            status = "paid" if paid == amount else ("partially_paid" if paid else "issued")
            inv = Invoice(health_center_id=cid, number=next_sequence(cid, "invoice_seq"), patient_id=pid,
                          department_id=dp[dept], clinic_id=cl[clinic], doctor_user_id=us[doctor]["id"],
                          doctor_name=doctor, status=status, subtotal=amount, invoice_discount=0, discount_total=0,
                          total=amount, paid_total=paid, balance=amount - paid, currency="SYP", issued_at=issued,
                          payment_seq=1 if paid else 0, author_name="seed")
            db.session.add(inv)
            db.session.flush()
            db.session.add(InvoiceItem(health_center_id=cid, invoice_id=inv.id, kind=kind, description=desc,
                                       qty=Decimal("1"), unit_price=amount, line_total=amount, discount_amount=0))
            if paid:
                db.session.add(Payment(health_center_id=cid, invoice_id=inv.id, seq=1, amount=paid, method="cash",
                                       paid_at=issued + timedelta(hours=1), author_name="seed"))
            return inv.id

        invoice("dent1", "dentistry", "dent_doc1", p1, L(2026, 1, 11, 10), "Filling", "treatment", "200", "150")
        invoice("dent2", "dentistry", "dent_doc2", p2, L(2026, 1, 16, 10), "Cleaning", "treatment", "80", "0")
        invoice("derm1", "dermatology", "derm_doc", p3, L(2026, 1, 21, 10), "Consultation", "consultation",
                "120", "120")

        lab = LabRequest(health_center_id=cid, patient_id=p1, requesting_department_id=dp["dentistry"],
                         requesting_clinic_id=cl["dent1"], lab_department_id=dp["laboratory"],
                         lab_clinic_id=cl["lab1"], status="completed", priority="urgent",
                         requested_at=L(2026, 1, 11, 8), finalized_at=L(2026, 1, 11, 13),
                         author_user_id=us["dent_doc1"]["id"], author_name="dent_doc1")
        db.session.add(lab)
        db.session.flush()
        for n, (code, nm, flag) in enumerate((("HB", "Hemoglobin", "H"), ("GLU", "Glucose", "N"))):
            db.session.add(LabRequestItem(health_center_id=cid, request_id=lab.id, test_code=code, test_name=nm,
                                          result_type="numeric", result_value="1", abnormal_flag=flag, sort_order=n))
        lab2 = LabRequest(health_center_id=cid, patient_id=p1, requesting_department_id=dp["dentistry"],
                          requesting_clinic_id=cl["dent1"], lab_department_id=dp["laboratory"],
                          status="requested", requested_at=L(2026, 1, 14, 8),
                          author_user_id=us["dent_doc1"]["id"], author_name="dent_doc1")
        db.session.add(lab2)
        db.session.flush()
        db.session.add(LabRequestItem(health_center_id=cid, request_id=lab2.id, test_code="HB",
                                      test_name="Hemoglobin", result_type="numeric", sort_order=0))

        for exam, status, fin in (("x_ray", "finalized", L(2026, 1, 12, 10)), ("ct", "requested", None)):
            db.session.add(RadiologyStudy(
                health_center_id=cid, patient_id=p1, requesting_department_id=dp["dentistry"],
                requesting_clinic_id=cl["dent1"], radiology_department_id=dp["radiology"],
                radiology_clinic_id=cl["rad1"] if fin else None, exam_type=exam, status=status,
                requested_at=L(2026, 1, 12, 8), finalized_at=fin, author_user_id=us["dent_doc1"]["id"],
                author_name="dent_doc1"))

        gloves = InventoryItem(health_center_id=cid, name=names.get("item", "Gloves"), unit="box",
                               low_stock_threshold=Decimal("10"))
        db.session.add(gloves)
        db.session.flush()
        locs = {}
        for key in ("dent1", "derm1"):
            loc = InventoryLocation(health_center_id=cid, kind="clinic", clinic_id=cl[key],
                                    department_id=dp["dentistry" if key == "dent1" else "dermatology"])
            db.session.add(loc)
            db.session.flush()
            locs[key] = loc.id
        soon = local_today() + timedelta(days=10)
        lot = StockLot(health_center_id=cid, item_id=gloves.id, location_id=locs["dent1"], quantity=Decimal("5"),
                       lot_code="L-1", expiry_date=soon)
        lot2 = StockLot(health_center_id=cid, item_id=gloves.id, location_id=locs["derm1"], quantity=Decimal("50"))
        db.session.add_all([lot, lot2])
        db.session.flush()
        db.session.add(StockMovement(health_center_id=cid, item_id=gloves.id, location_id=locs["dent1"],
                                     lot_id=lot.id, type="receive", quantity=Decimal("10"), author_name="seed",
                                     created_at=L(2026, 1, 5)))
        db.session.add(StockMovement(health_center_id=cid, item_id=gloves.id, location_id=locs["dent1"],
                                     lot_id=lot.id, type="use", quantity=Decimal("-5"), author_name="seed",
                                     created_at=L(2026, 1, 6)))
        db.session.add(StockMovement(health_center_id=cid, item_id=gloves.id, location_id=locs["derm1"],
                                     lot_id=lot2.id, type="receive", quantity=Decimal("50"), author_name="seed",
                                     created_at=L(2026, 1, 7)))
        db.session.commit()
        out["locations"] = locs
        out["item"] = gloves.id
    return out


def set_perm(app, center, user_key, perm, allowed):
    from backend.app.models import UserPermission
    with app.app_context(), tenancy.scoped("tenant", center["center_id"]):
        db.session.add(UserPermission(health_center_id=center["center_id"], user_id=center["users"][user_key]["id"],
                                      permission=perm, allowed=allowed))
        db.session.commit()
