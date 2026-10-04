"""Laser Hair Removal sessions (Dermatology submodule, spec §36-37).

Session numbering: per patient + department. Auto number = max(live sessions) + 1, computed
under a transaction-scoped advisory lock keyed on (center, patient, department) so concurrent
creates never collide; a partial unique index on live rows is the database backstop.
"""
from datetime import datetime, time

from sqlalchemy import delete as sa_delete, event, func, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.core.api import check_version, page_params
from backend.app.core.errors import Conflict, NotFound, ValidationError
from backend.app.core.timeutil import TZ, iso, local_today, utcnow
from backend.app.core.validation import Bool, Date, DateTime, Enum, Id, Int, JsonDict, List, Obj, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Patient, StoredFile, Visit
from backend.app.services import clinical, deletion
from backend.app.services import files as file_service

from .models import LaserSession, LaserSessionArea
from .regions import REGION_BY_CODE, REGION_CODES, SIDES, catalog, label
from .service import PHOTO_CATEGORIES, owned_files
from .visitkit import author_json, purge_files

ENV = "dermatology"
ENTITY, OWNER_TYPE = "laser_session", "laser_session"

AREA = Obj({"region": Enum(REGION_CODES, required=True), "side": Enum(SIDES, required=True)})
FIELDS = {
    "session_number": Int(min_value=1, max_value=9999),
    "session_date": Date(),
    "areas": List(AREA, max_items=60),
    "notes": Text(max_len=10000),
    "next_session_at": DateTime(),
    "extra": JsonDict(),
}
CREATE_SCHEMA = {"patient_id": Id(), "clinic_id": Id(), "visit_id": Id(), "create_visit": Bool(), **FIELDS}


def _before_purge(sess):
    purge_files((StoredFile.health_center_id == sess.health_center_id) & (StoredFile.owner_type == OWNER_TYPE)
                & (StoredFile.owner_id == sess.id))
    if sess.owns_visit and sess.visit_id:
        center_id, visit_id = sess.health_center_id, sess.visit_id
        purge_files((StoredFile.health_center_id == center_id) & (StoredFile.visit_id == visit_id))

        # The owned visit goes too, but only after the session row itself is deleted (the
        # visit FK cascades to sessions, so deleting it first would make the ORM delete stale).
        @event.listens_for(db.session(), "after_flush", once=True)
        def _delete_owned_visit(session, _ctx):
            session.connection().execute(sa_delete(Visit).where(Visit.health_center_id == center_id,
                                                                Visit.id == visit_id))


deletion.register(ENTITY, LaserSession, before_purge=_before_purge)


def derm_clinic_ids(p):
    return sorted(c for c, d in p.clinic_department.items() if p.department_env.get(d) == ENV)


def clinic_names(p, ids):
    if not ids:
        return {}
    return dict(db.session.execute(select(Clinic.id, Clinic.name).where(p.tenant(Clinic), Clinic.id.in_(list(ids)))).all())


def meta(p=None):
    clinics = []
    if p:
        ids = derm_clinic_ids(p)
        names = clinic_names(p, ids)
        clinics = [{"id": c, "name": names.get(c), "department_id": p.clinic_department[c]} for c in ids]
    return {"body_regions": catalog(), "sides": list(SIDES), "photo_categories": list(PHOTO_CATEGORIES), "clinics": clinics}


# ---- helpers ------------------------------------------------------------------
def _lock(center_id, patient_id, department_id):
    db.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                       {"k": f"laser_session_number:{center_id}:{patient_id}:{department_id}"})


def _max_number(center_id, patient_id, department_id):
    return db.session.execute(select(func.coalesce(func.max(LaserSession.session_number), 0)).where(
        LaserSession.health_center_id == center_id, LaserSession.patient_id == patient_id,
        LaserSession.department_id == department_id, LaserSession.live())).scalar_one()


def _number_taken(sess, number):
    return db.session.execute(select(LaserSession.id).where(
        LaserSession.health_center_id == sess.health_center_id, LaserSession.patient_id == sess.patient_id,
        LaserSession.department_id == sess.department_id, LaserSession.session_number == number,
        LaserSession.live(), LaserSession.id != (sess.id or -1))).first() is not None


def _taken_error(number):
    return Conflict(f"Session number {number} already exists for this patient.", code="session_number_taken",
                    details={"session_number": number})


def _normalize_areas(areas):
    out, seen, errors = [], set(), {}
    for i, a in enumerate(areas or []):
        if a["side"] not in REGION_BY_CODE[a["region"]]["views"]:
            errors[f"areas.{i}"] = f"{a['region']} cannot be selected on the {a['side']} view"
            continue
        key = (a["region"], a["side"])
        if key not in seen:
            seen.add(key)
            out.append(key)
    if errors:
        raise ValidationError("Invalid input", details=errors)
    return out


def _scoped_stmt(p):
    return (select(LaserSession, Clinic.name)
            .join(Clinic, (Clinic.id == LaserSession.clinic_id) & (Clinic.health_center_id == LaserSession.health_center_id))
            .where(p.tenant(LaserSession), LaserSession.live(),
                   LaserSession.clinic_id.in_(sorted(p.clinic_ids) or [-1])))


def _get(p, session_id, perm="medical_records.view"):
    row = db.session.execute(_scoped_stmt(p).where(LaserSession.id == session_id)).first()
    if row is None:
        raise NotFound("Laser session not found")
    if perm:
        p.require(perm, clinic_id=row[0].clinic_id)
    return row


def _areas_for(ids):
    out = {i: [] for i in ids}
    if ids:
        for a in db.session.execute(select(LaserSessionArea).where(LaserSessionArea.session_id.in_(ids))
                                    .order_by(LaserSessionArea.id)).scalars():
            out[a.session_id].append(a)
    return out


def _area_json(a):
    r = REGION_BY_CODE.get(a.region)
    return {"region": a.region, "side": a.side, "label_en": label(a.region, "en"), "label_ar": label(a.region, "ar"),
            "group": r["group"] if r else None}


def _photo_counts(p, ids):
    if not ids:
        return {}
    return dict(db.session.execute(select(StoredFile.owner_id, func.count()).where(
        file_service.visible_clause(p), StoredFile.owner_type == OWNER_TYPE, StoredFile.owner_id.in_(ids))
        .group_by(StoredFile.owner_id)).all())


def to_json(s, clinic_name, areas, photo_count=0):
    return {"id": s.id, "patient_id": s.patient_id, "department_id": s.department_id, "clinic_id": s.clinic_id,
            "clinic_name": clinic_name, "visit_id": s.visit_id, "owns_visit": s.owns_visit,
            "session_number": s.session_number, "session_date": iso(s.session_date), "notes": s.notes,
            "next_session_at": iso(s.next_session_at), "next_appointment_id": s.next_appointment_id,
            "extra": s.extra or {}, "areas": [_area_json(a) for a in areas], "photo_count": photo_count,
            **author_json(s)}


def _serialize_rows(p, rows):
    ids = [r[0].id for r in rows]
    areas, counts = _areas_for(ids), _photo_counts(p, ids)
    return [to_json(s, cn, areas[s.id], counts.get(s.id, 0)) for s, cn in rows]


def _replace_areas(sess, keys):
    db.session.query(LaserSessionArea).filter(LaserSessionArea.session_id == sess.id).delete(
        synchronize_session=False)
    for region, side in keys:
        db.session.add(LaserSessionArea(health_center_id=sess.health_center_id, session_id=sess.id, region=region,
                                        side=side))


def _visit_at_for(d):
    if d == local_today():
        return utcnow()
    return datetime.combine(d, time(12, 0), tzinfo=TZ)


# ---- API-facing operations ------------------------------------------------------
def list_sessions(p, patient_id, clinic_id=None):
    clinical.get_patient(p, patient_id, perm="medical_records.view")
    stmt = _scoped_stmt(p).where(LaserSession.patient_id == patient_id)
    if clinic_id:
        clinical.require_environment(p, clinic_id, ENV)
        stmt = stmt.where(LaserSession.clinic_id == clinic_id)
    stmt = stmt.order_by(LaserSession.session_number.desc(), LaserSession.id.desc())
    page, per_page = page_params(50)
    rows = db.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    total = db.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    return {"items": _serialize_rows(p, rows), "page": page, "per_page": per_page, "total": total}


def list_department(p, args):
    """Sessions across the caller's clinics. upcoming=1 -> sessions whose next session is due from now on."""
    from . import visitkit
    args = validate(args, {**visitkit.LIST_ARGS, "upcoming": Bool()})
    p.require("medical_records.view")
    stmt = (_scoped_stmt(p).add_columns(Patient.id, Patient.full_name, Patient.code)
            .join(Patient, (Patient.id == LaserSession.patient_id)
                  & (Patient.health_center_id == LaserSession.health_center_id)).where(Patient.live()))
    if args.get("upcoming"):
        stmt = stmt.where(LaserSession.next_session_at >= utcnow()).order_by(LaserSession.next_session_at,
                                                                             LaserSession.id)
        date_col = LaserSession.next_session_at
    else:
        stmt = stmt.order_by(LaserSession.session_date.desc(), LaserSession.id.desc())
        date_col = None
        if args.get("date_from"):
            stmt = stmt.where(LaserSession.session_date >= args["date_from"])
        if args.get("date_to"):
            stmt = stmt.where(LaserSession.session_date <= args["date_to"])
    stmt = visitkit.scope_filters(p, stmt, LaserSession, ENV, args, date_col)
    page, per_page = page_params(25)
    rows = db.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    total = db.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    items = _serialize_rows(p, [r[:2] for r in rows])
    for it, r in zip(items, rows):
        it["patient"] = visitkit.patient_json(*r[2:])
    return {"items": items, "page": page, "per_page": per_page, "total": total}


def history(p, patient_id, clinic_id=None):
    """All visible sessions oldest -> newest with their areas, plus per-area counts."""
    clinical.get_patient(p, patient_id, perm="medical_records.view")
    stmt = _scoped_stmt(p).where(LaserSession.patient_id == patient_id)
    if clinic_id:
        clinical.require_environment(p, clinic_id, ENV)
        stmt = stmt.where(LaserSession.clinic_id == clinic_id)
    rows = db.session.execute(stmt.order_by(LaserSession.session_number, LaserSession.id).limit(1000)).all()
    sessions = _serialize_rows(p, rows)
    counts = {}
    for s in sessions:
        for a in s["areas"]:
            c = counts.setdefault(a["region"], {"region": a["region"], "label_en": a["label_en"],
                                                "label_ar": a["label_ar"], "group": a["group"], "count": 0,
                                                "sides": {}, "first_date": s["session_date"],
                                                "last_date": s["session_date"], "session_numbers": []})
            c["sides"][a["side"]] = c["sides"].get(a["side"], 0) + 1
            if s["session_number"] not in c["session_numbers"]:
                c["session_numbers"].append(s["session_number"])
                c["count"] += 1
            c["first_date"] = min(c["first_date"], s["session_date"])
            c["last_date"] = max(c["last_date"], s["session_date"])
    order = {code: i for i, code in enumerate(REGION_CODES)}
    area_counts = sorted(counts.values(), key=lambda c: order.get(c["region"], 999))
    last = max(sessions, key=lambda s: (s["session_date"], s["session_number"]), default=None)
    return {"patient_id": patient_id, "total_sessions": len(sessions), "sessions": sessions,
            "area_counts": area_counts,
            "last_session_date": last["session_date"] if last else None,
            "next_session_at": last["next_session_at"] if last else None}


def next_number(p, patient_id, clinic_id):
    clinical.get_patient(p, patient_id, perm="medical_records.view")
    dept = clinical.require_environment(p, clinic_id, ENV)
    return {"patient_id": patient_id, "department_id": dept,
            "next_session_number": _max_number(p.center_id, patient_id, dept) + 1}


def create(p, body):
    data = validate(body, CREATE_SCHEMA)
    keys = _normalize_areas(data.get("areas"))
    if not keys:
        raise ValidationError("Invalid input", details={"areas": "select at least one treatment area"})
    visit, owns = None, False
    if data.get("visit_id"):
        visit = db.session.execute(select(Visit).where(Visit.id == data["visit_id"], p.tenant(Visit), Visit.live(),
                                                       p.clinic_clause(Visit.clinic_id))).scalar_one_or_none()
        if visit is None:
            raise NotFound("Visit not found")
        clinic_id = visit.clinic_id
        if data.get("clinic_id") and data["clinic_id"] != clinic_id:
            raise ValidationError("Invalid input", details={"clinic_id": "does not match the visit"})
        if data.get("patient_id") and data["patient_id"] != visit.patient_id:
            raise ValidationError("Invalid input", details={"patient_id": "does not match the visit"})
        patient_id = visit.patient_id
    else:
        errors = {k: "is required" for k in ("patient_id", "clinic_id") if not data.get(k)}
        if errors:
            raise ValidationError("Invalid input", details=errors)
        clinic_id, patient_id = data["clinic_id"], data["patient_id"]
    dept = clinical.require_environment(p, clinic_id, ENV)
    p.require("medical_records.create", clinic_id=clinic_id)
    session_date = data.get("session_date") or local_today()
    if visit is None and data.get("create_visit", True):
        visit = clinical.create_visit(p, patient_id=patient_id, clinic_id=clinic_id, visit_type="session",
                                      visit_at=_visit_at_for(session_date), title="Laser hair removal session",
                                      environments=[ENV])
        owns = True
    elif visit is None:
        # No visit requested: the patient must still exist in this center; link it to the clinic.
        exists = db.session.execute(select(Patient.id).where(Patient.id == patient_id, p.tenant(Patient),
                                                             Patient.live())).first()
        if not exists:
            raise NotFound("Patient not found")
        clinical.link_patient_to_clinic(p.center_id, patient_id, clinic_id, dept)
    if visit is not None and not owns:
        if db.session.execute(select(LaserSession.id).where(LaserSession.visit_id == visit.id)).first():
            raise Conflict("This visit already has a laser session.", code="already_exists")
    _lock(p.center_id, patient_id, dept)
    number = data.get("session_number") or _max_number(p.center_id, patient_id, dept) + 1
    s = LaserSession(health_center_id=p.center_id, patient_id=patient_id, department_id=dept, clinic_id=clinic_id,
                     visit_id=visit.id if visit else None, owns_visit=owns, session_number=number,
                     session_date=session_date, notes=data.get("notes"), next_session_at=data.get("next_session_at"),
                     extra=data.get("extra") or {})
    if _number_taken(s, number):
        raise _taken_error(number)
    s.set_author(p.user)
    db.session.add(s)
    try:
        db.session.flush()
        _replace_areas(s, keys)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise _taken_error(number)
    return get(p, s.id)


def get(p, session_id):
    row = _get(p, session_id)
    return _serialize_rows(p, [row])[0]


def update(p, session_id, body):
    s, _ = _get(p, session_id, perm="medical_records.edit")
    check_version(s, (body or {}).get("version"))
    data = validate(body, FIELDS, partial=True)
    if "areas" in data:
        keys = _normalize_areas(data["areas"])
        if not keys:
            raise ValidationError("Invalid input", details={"areas": "select at least one treatment area"})
        _replace_areas(s, keys)
    if data.get("session_number") and data["session_number"] != s.session_number:
        _lock(s.health_center_id, s.patient_id, s.department_id)
        if _number_taken(s, data["session_number"]):
            raise _taken_error(data["session_number"])
        s.session_number = data["session_number"]
    if data.get("session_date"):
        s.session_date = data["session_date"]
    for k in ("notes", "next_session_at"):
        if k in data:
            setattr(s, k, data[k])
    if "extra" in data:
        s.extra = data["extra"] or {}
    s.updated_at = utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise _taken_error(data.get("session_number"))
    return get(p, s.id)


def delete(p, session_id):
    s, _ = _get(p, session_id, perm=None)
    p.require("medical_records.delete", clinic_id=s.clinic_id)
    return deletion.stage(p, s, ENTITY, f"Laser session {s.session_number}")


def upload_photos(p, session_id, uploads, category="photo", description=None):
    s, _ = _get(p, session_id, perm=None)
    p.require("files.upload", clinic_id=s.clinic_id)
    if category not in PHOTO_CATEGORIES:
        raise ValidationError("Invalid input", details={"category": "must be one of: " + ", ".join(PHOTO_CATEGORIES)})
    if description and len(description) > 2000:
        raise ValidationError("Invalid input", details={"description": "must be at most 2000 characters"})
    rows = file_service.store_upload(p, uploads, clinic_id=s.clinic_id, department_id=s.department_id,
                                     patient_id=s.patient_id, visit_id=s.visit_id, category=category,
                                     owner_type=OWNER_TYPE, owner_id=s.id, description=description)
    return {"items": [file_service.serialize(f, p) for f in rows]}


def list_photos(p, session_id):
    s, _ = _get(p, session_id, perm=None)
    p.require("files.view", clinic_id=s.clinic_id)
    return {"items": owned_files(p, OWNER_TYPE, s.id)}


def patient_summary(p, patient_id):
    """Laser part of the Complete Patient Summary (access-scoped). None if nothing visible."""
    if not p.has("medical_records.view"):
        return None
    stmt = _scoped_stmt(p).where(LaserSession.patient_id == patient_id)
    if db.session.execute(stmt.limit(1)).first() is None:
        return None
    rows = db.session.execute(stmt.order_by(LaserSession.session_number, LaserSession.id).limit(1000)).all()
    h = _serialize_rows(p, rows)
    areas = {}
    for s in h:
        for region in {a["region"] for a in s["areas"]}:
            areas[region] = areas.get(region, 0) + 1
    return {"type": "laser", "title": "Laser Hair Removal", "session_count": len(h), "last_session_date": max(s["session_date"] for s in h),
            "area_counts": areas}


def _register_summary():
    try:
        from backend.app.modules.patients.summary import register_summary_provider
    except ImportError:  # patients module absent: patient_summary() stays callable directly
        return
    register_summary_provider("laser_hair_removal", lambda p, patient: patient_summary(p, patient.id), order=215)


_register_summary()
