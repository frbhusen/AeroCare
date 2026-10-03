"""Shared helpers for billing / PDF tests."""
from backend.app.core import tenancy
from backend.app.extensions import db

BASE = "/api/v1/billing"


def make_patient(app, center, clinic_key="dent1", name="Ali Hassan"):
    """Create a patient linked to a clinic directly via the ORM; returns its id."""
    from backend.app.models import Patient
    from backend.app.services.centers import next_sequence
    from backend.app.services.clinical import link_patient_to_clinic, normalize_name
    with app.app_context(), tenancy.scoped("tenant", center["center_id"]):
        code = next_sequence(center["center_id"], "patient_seq")
        pt = Patient(health_center_id=center["center_id"], code=code, full_name=name,
                     search_name=normalize_name(name))
        db.session.add(pt)
        db.session.flush()
        link_patient_to_clinic(center["center_id"], pt.id, center["clinics"][clinic_key])
        db.session.commit()
        return pt.id


def new_invoice(client, center, patient_id, clinic_key="dent1", items=None, **extra):
    body = {"patient_id": patient_id, "clinic_id": center["clinics"][clinic_key],
            "items": items if items is not None else [{"description": "Consultation", "qty": 1,
                                                       "unit_price": "100.00"}]}
    body.update(extra)
    return client.post(f"{BASE}/invoices", json=body)
