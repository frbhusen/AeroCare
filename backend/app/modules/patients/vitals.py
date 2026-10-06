"""Patient Vital Signs service (BP, Heart Rate, Temperature, Resp Rate, SpO2, Weight, Height, BMI)."""
from sqlalchemy import select

from backend.app.core.errors import NotFound, ValidationError
from backend.app.core.timeutil import iso, utcnow
from backend.app.core.validation import DateTime, Id, Int, Num, Str, Text, validate
from backend.app.extensions import db
from backend.app.models.clinical import Patient, PatientVital
from backend.app.services import deletion
from backend.app.services.clinical import get_patient

deletion.register("vital", PatientVital)

VITALS_SCHEMA = {
    "bp_systolic": Int(min_value=30, max_value=300),
    "bp_diastolic": Int(min_value=10, max_value=200),
    "heart_rate": Int(min_value=10, max_value=300),
    "temperature": Num(min_value=25.0, max_value=45.0, places=1),
    "resp_rate": Int(min_value=1, max_value=100),
    "spo2": Int(min_value=0, max_value=100),
    "weight": Num(min_value=0.2, max_value=500.0, places=2),
    "height": Num(min_value=20.0, max_value=260.0, places=1),
    "notes": Text(max_len=2000),
    "clinic_id": Id(),
    "visit_id": Id(),
    "recorded_at": DateTime(),
}


def calc_bmi(weight, height):
    if weight and height and float(height) > 0:
        h_m = float(height) / 100.0
        return round(float(weight) / (h_m * h_m), 1)
    return None


def vital_json(v):
    if v is None:
        return None
    w = float(v.weight) if v.weight is not None else None
    h = float(v.height) if v.height is not None else None
    bmi = float(v.bmi) if v.bmi is not None else calc_bmi(w, h)
    return {
        "id": v.id,
        "patient_id": v.patient_id,
        "clinic_id": v.clinic_id,
        "visit_id": v.visit_id,
        "recorded_at": iso(v.recorded_at),
        "bp_systolic": v.bp_systolic,
        "bp_diastolic": v.bp_diastolic,
        "heart_rate": v.heart_rate,
        "temperature": float(v.temperature) if v.temperature is not None else None,
        "resp_rate": v.resp_rate,
        "spo2": v.spo2,
        "weight": w,
        "height": h,
        "bmi": bmi,
        "notes": v.notes,
        "author_name": v.author_name,
        "author_role": v.author_role,
        "created_at": iso(v.created_at),
        "version": v.version,
    }


def list_vitals(p, patient_id):
    p.require("medical_records.view")
    get_patient(p, patient_id)
    stmt = (select(PatientVital)
            .where(p.tenant(PatientVital), PatientVital.patient_id == patient_id, PatientVital.live())
            .order_by(PatientVital.recorded_at.desc(), PatientVital.id.desc()))
    items = db.session.execute(stmt).scalars().all()
    serialized = [vital_json(v) for v in items]
    latest = serialized[0] if serialized else None

    # Trend sparkline data (oldest to newest)
    chronological = list(reversed(serialized))
    trends = {
        "bp_systolic": [{"date": v["recorded_at"], "val": v["bp_systolic"]} for v in chronological if v["bp_systolic"] is not None],
        "bp_diastolic": [{"date": v["recorded_at"], "val": v["bp_diastolic"]} for v in chronological if v["bp_diastolic"] is not None],
        "heart_rate": [{"date": v["recorded_at"], "val": v["heart_rate"]} for v in chronological if v["heart_rate"] is not None],
        "weight": [{"date": v["recorded_at"], "val": v["weight"]} for v in chronological if v["weight"] is not None],
        "temperature": [{"date": v["recorded_at"], "val": v["temperature"]} for v in chronological if v["temperature"] is not None],
        "bmi": [{"date": v["recorded_at"], "val": v["bmi"]} for v in chronological if v["bmi"] is not None],
    }

    return {"items": serialized, "latest": latest, "trends": trends}


def create_vital(p, patient_id, body):
    p.require("medical_records.create")
    get_patient(p, patient_id)
    data = validate(body, VITALS_SCHEMA)

    has_any = any(data.get(k) is not None for k in (
        "bp_systolic", "bp_diastolic", "heart_rate", "temperature", "resp_rate", "spo2", "weight", "height", "notes"
    ))
    if not has_any:
        raise ValidationError("At least one vital sign or note is required.", code="empty_vitals")

    w = data.get("weight")
    h = data.get("height")
    bmi = calc_bmi(w, h)

    v = PatientVital(
        health_center_id=p.center_id,
        patient_id=patient_id,
        clinic_id=data.get("clinic_id"),
        visit_id=data.get("visit_id"),
        recorded_at=data.get("recorded_at") or utcnow(),
        bp_systolic=data.get("bp_systolic"),
        bp_diastolic=data.get("bp_diastolic"),
        heart_rate=data.get("heart_rate"),
        temperature=data.get("temperature"),
        resp_rate=data.get("resp_rate"),
        spo2=data.get("spo2"),
        weight=w,
        height=h,
        bmi=bmi,
        notes=data.get("notes"),
    )
    v.set_author(p.user)
    db.session.add(v)
    db.session.commit()
    return vital_json(v)


def delete_vital(p, vital_id):
    p.require("medical_records.delete")
    v = db.session.execute(
        select(PatientVital).where(p.tenant(PatientVital), PatientVital.id == vital_id, PatientVital.live())
    ).scalar_one_or_none()
    if v is None:
        raise NotFound("Vital record not found")
    res = deletion.stage(p, v, "vital", f"Vital signs record #{v.id}")
    db.session.commit()
    return res
