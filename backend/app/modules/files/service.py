"""Files API business logic. Storage, validation, quota and the visibility rule live in the core
`services/files.py`; this module adds the patient-file workflows (upload to a patient/clinic/visit,
list, rename, annotate, delete+undo, share/unshare, usage).
"""
import os
import re

from sqlalchemy import exists, or_, select

from backend.app.core.api import check_version, paginate
from backend.app.core.errors import Forbidden, NotFound, ValidationError
from backend.app.core.timeutil import iso
from backend.app.core.validation import Bool, Enum, Id, Str, Text, validate
from backend.app.extensions import db
from backend.app.models import Clinic, Department, FileShare, StoredFile, User, Visit
from backend.app.models.files import FILE_CATEGORIES
from backend.app.services import deletion
from backend.app.services import files as core_files
from backend.app.services.clinical import get_clinic, get_patient, link_patient_to_clinic

from backend.app.modules.patients.helpers import clinic_names, like_escape

deletion.register("file", StoredFile, files=lambda f: StoredFile.id == f.id)

# Categories staff may pick for ordinary patient uploads (others are set by their modules).
UPLOAD_CATEGORIES = ("xray", "photo", "medical_image", "document", "other")
ANNOTATION_TYPES = ("arrow", "line", "rect", "ellipse", "circle", "text", "freehand", "point", "measure")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def file_json(f, p, shares=None):
    out = core_files.serialize(f, p)
    out["share_count"] = shares
    return out


# ------------------------------------------------------------------ visibility
def list_clause(p):
    """Core visibility + the patient rule from services.files.get_visible: patient-bound files
    also need the patient to be visible (unless center-wide or explicitly shared)."""
    clause = core_files.visible_clause(p)
    if p.center_wide:
        return clause
    shared = exists().where(FileShare.file_id == StoredFile.id)
    return clause & or_(StoredFile.patient_id.is_(None), StoredFile.center_wide.is_(True),
                        p.patient_clause(StoredFile.patient_id), shared)


def get_file(p, file_id, perm="files.view"):
    f = core_files.get_visible(p, file_id)
    p.require(perm)
    return f


def get_managed(p, file_id, perm):
    f = get_file(p, file_id, perm=None)
    if not core_files.can_manage(p, f):
        # Visible (e.g. shared with me) but not owned by my scope.
        raise Forbidden("Only the owning clinic or its managers can change this file.", code="file_not_managed")
    p.require(perm)
    return f


def list_files(p, args):
    p.require("files.view")
    a = validate(args, {"patient_id": Id(), "visit_id": Id(), "clinic_id": Id(), "department_id": Id(),
                        "owner_type": Str(max_len=40), "owner_id": Id(), "category": Enum(FILE_CATEGORIES),
                        "q": Str(max_len=100), "images_only": Bool()})
    stmt = select(StoredFile).where(list_clause(p))
    if a.get("patient_id"):
        # No visibility check here: list_clause already restricts to files p may see (a patient not
        # visible to p yields only center-wide / explicitly shared files).
        stmt = stmt.where(StoredFile.patient_id == a["patient_id"])
    for key, col in (("visit_id", StoredFile.visit_id), ("clinic_id", StoredFile.clinic_id),
                     ("department_id", StoredFile.department_id), ("owner_type", StoredFile.owner_type),
                     ("owner_id", StoredFile.owner_id), ("category", StoredFile.category)):
        if a.get(key) is not None:
            stmt = stmt.where(col == a[key])
    if a.get("q"):
        stmt = stmt.where(StoredFile.display_name.ilike(f"%{like_escape(a['q'])}%", escape="\\"))
    if a.get("images_only"):
        stmt = stmt.where(StoredFile.mime_type.like("image/%"))
    stmt = stmt.order_by(StoredFile.created_at.desc(), StoredFile.id.desc())
    out = paginate(db.session, stmt, lambda f: f)
    rows = out["items"]
    names = clinic_names(p.center_id, [f.clinic_id for f in rows])
    items = []
    for f in rows:
        j = core_files.serialize(f, p)
        j["clinic_name"] = names.get(f.clinic_id)
        items.append(j)
    out["items"] = items
    return out


# ------------------------------------------------------------------ upload
def upload(p, form, uploads):
    data = validate(form, {"patient_id": Id(required=True), "clinic_id": Id(required=True), "visit_id": Id(),
                           "category": Enum(UPLOAD_CATEGORIES), "description": Text(max_len=2000)})
    p.require("files.upload", clinic_id=data["clinic_id"])
    clinic = get_clinic(p, data["clinic_id"])
    pt = get_patient(p, data["patient_id"], perm=None)
    if data.get("visit_id"):
        v = db.session.execute(select(Visit).where(Visit.id == data["visit_id"], p.tenant(Visit), Visit.live(),
                                                   p.clinic_clause(Visit.clinic_id))).scalar_one_or_none()
        if v is None:
            raise NotFound("Visit not found")
        if v.clinic_id != clinic.id or v.patient_id != pt.id:
            raise ValidationError("The visit must belong to the same patient and clinic.",
                                  details={"visit_id": "belongs to another patient or clinic"})
    link_patient_to_clinic(p.center_id, pt.id, clinic.id, clinic.department_id)
    rows = core_files.store_upload(p, uploads, clinic_id=clinic.id, department_id=clinic.department_id,
                                   patient_id=pt.id, visit_id=data.get("visit_id"),
                                   category=data.get("category") or "document", description=data.get("description"))
    return rows


# ------------------------------------------------------------------ edit
def _safe_display_name(name, original):
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*/]", "_", name)[:200].strip()
    if not name:
        raise ValidationError("Invalid input", details={"display_name": "is required"})
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext and not name.lower().endswith("." + ext):
        name = f"{name}.{ext}"  # the extension is kept so downloads open with the right application
    return name


def update(p, file_id, body):
    f = get_managed(p, file_id, "files.edit")
    data = validate(body, {"version": Id(required=True), "display_name": Str(max_len=200),
                           "description": Text(max_len=2000), "category": Enum(UPLOAD_CATEGORIES)}, partial=True)
    check_version(f, data.pop("version"))
    if "display_name" in data:
        f.display_name = _safe_display_name(data["display_name"], f.original_name)
    if "description" in data:
        f.description = data["description"]
    if data.get("category"):
        if f.category not in UPLOAD_CATEGORIES:
            raise ValidationError("This file's category is managed by its module.", code="category_locked")
        f.category = data["category"]
    db.session.commit()
    return f


def _validate_annotations(raw):
    if not isinstance(raw, list):
        raise ValidationError("Invalid input", details={"annotations": "must be a list"})
    if len(raw) > 500:
        raise ValidationError("Invalid input", details={"annotations": "must have at most 500 items"})
    out = []
    for n, a in enumerate(raw):
        err = None
        if not isinstance(a, dict) or a.get("type") not in ANNOTATION_TYPES:
            err = "type must be one of: " + ", ".join(ANNOTATION_TYPES)
        else:
            pts = a.get("points") or []
            if (not isinstance(pts, list) or len(pts) > 2000
                    or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and -1e6 < x < 1e6
                               for x in pts)):
                err = "points must be a list of numbers"
            text = a.get("text")
            if text is not None and (not isinstance(text, str) or len(text) > 500):
                err = "text must be at most 500 characters"
            color = a.get("color")
            if color is not None and (not isinstance(color, str) or not COLOR_RE.match(color)):
                err = "color must be #RRGGBB"
            width = a.get("width")
            if width is not None and (not isinstance(width, (int, float)) or isinstance(width, bool)
                                      or not 0 < width <= 100):
                err = "width must be between 0 and 100"
        if err:
            raise ValidationError("Invalid input", details={"annotations": f"item {n}: {err}"})
        out.append({k: a[k] for k in ("type", "points", "text", "color", "width") if k in a})
    return out


def save_annotations(p, file_id, body):
    f = get_managed(p, file_id, "files.edit")
    data = validate(body, {"version": Id(required=True)})
    check_version(f, data["version"])
    if not f.mime_type.startswith("image/"):
        raise ValidationError("Only images can be annotated.", code="not_an_image")
    f.annotations = _validate_annotations((body or {}).get("annotations"))
    db.session.commit()
    return f


def delete(p, file_id):
    f = get_managed(p, file_id, "files.delete")
    return deletion.stage(p, f, "file", f.display_name)


# ------------------------------------------------------------------ sharing
def share_json(s, labels):
    if s.target_department_id:
        kind, tid = "department", s.target_department_id
    elif s.target_clinic_id:
        kind, tid = "clinic", s.target_clinic_id
    else:
        kind, tid = "user", s.target_user_id
    return {"id": s.id, "target_type": kind, "target_id": tid, "target_name": labels.get((kind, tid)),
            "shared_by": s.shared_by, "created_at": iso(s.created_at)}


def _labels(center_id, shares):
    labels = {}
    d = [s.target_department_id for s in shares if s.target_department_id]
    c = [s.target_clinic_id for s in shares if s.target_clinic_id]
    u = [s.target_user_id for s in shares if s.target_user_id]
    if d:
        labels.update({("department", i): n for i, n in db.session.execute(
            select(Department.id, Department.name).where(Department.health_center_id == center_id,
                                                         Department.id.in_(d)))})
    if c:
        labels.update({("clinic", i): n for i, n in db.session.execute(
            select(Clinic.id, Clinic.name).where(Clinic.health_center_id == center_id, Clinic.id.in_(c)))})
    if u:
        labels.update({("user", i): n for i, n in db.session.execute(
            select(User.id, User.name).where(User.health_center_id == center_id, User.id.in_(u)))})
    return labels


def list_shares(p, file_id):
    f = get_managed(p, file_id, "files.share")
    shares = db.session.execute(select(FileShare).where(FileShare.file_id == f.id, p.tenant(FileShare))
                                .order_by(FileShare.id)).scalars().all()
    labels = _labels(p.center_id, shares)
    return [share_json(s, labels) for s in shares]


def add_share(p, file_id, body):
    f = get_managed(p, file_id, "files.share")
    data = validate(body, {"target_type": Enum(["department", "clinic", "user"], required=True),
                           "target_id": Id(required=True)})
    kind, tid = data["target_type"], data["target_id"]
    if kind == "department":
        ok = db.session.execute(select(Department.id).where(Department.id == tid, p.tenant(Department),
                                                            Department.live(), Department.is_active.is_(True))).first()
        col = FileShare.target_department_id
    elif kind == "clinic":
        ok = db.session.execute(select(Clinic.id).where(Clinic.id == tid, p.tenant(Clinic), Clinic.live(),
                                                        Clinic.is_active.is_(True))).first()
        col = FileShare.target_clinic_id
    else:
        ok = db.session.execute(select(User.id).where(User.id == tid, User.health_center_id == p.center_id,
                                                      User.status == "active")).first()
        col = FileShare.target_user_id
    if not ok:
        raise NotFound("Share target not found")
    existing = db.session.execute(select(FileShare).where(FileShare.file_id == f.id, col == tid)).scalar_one_or_none()
    if existing is None:
        existing = FileShare(health_center_id=p.center_id, file_id=f.id, shared_by=p.user.id,
                             **{col.key: tid})
        db.session.add(existing)
        db.session.commit()
    return share_json(existing, _labels(p.center_id, [existing]))


def remove_share(p, file_id, share_id):
    f = get_managed(p, file_id, "files.share")
    s = db.session.execute(select(FileShare).where(FileShare.id == share_id, FileShare.file_id == f.id,
                                                   p.tenant(FileShare))).scalar_one_or_none()
    if s is None:
        raise NotFound("Share not found")
    db.session.delete(s)
    db.session.commit()
    return {"ok": True}


def share_targets(p):
    """Choices for the share dialog: active departments, clinics and staff of the center."""
    p.require("files.share")
    depts = db.session.execute(select(Department.id, Department.name).where(
        p.tenant(Department), Department.live(), Department.is_active.is_(True)).order_by(Department.name)).all()
    active = set(_active_department_ids(p))
    clinics = db.session.execute(select(Clinic.id, Clinic.name, Clinic.department_id).where(
        p.tenant(Clinic), Clinic.live(), Clinic.is_active.is_(True)).order_by(Clinic.name)).all()
    users = db.session.execute(select(User.id, User.name, User.role, User.clinic_id).where(
        User.health_center_id == p.center_id, User.status == "active",
        User.role.in_(["doctor", "department_manager", "center_manager"])).order_by(User.name)).all()
    return {"departments": [{"id": d[0], "name": d[1]} for d in depts if d[0] in active],
            "clinics": [{"id": c[0], "name": c[1], "department_id": c[2]} for c in clinics if c[2] in active],
            "users": [{"id": u[0], "name": u[1], "role": u[2], "clinic_id": u[3]} for u in users]}


def _active_department_ids(p):
    from backend.app.authz.principal import active_structure
    return active_structure(p.center_id)[1].keys()


# ------------------------------------------------------------------ summary section
def summary_section(p, patient):
    if not p.has("files.view"):
        return None
    rows = db.session.execute(select(StoredFile).where(list_clause(p), StoredFile.patient_id == patient.id)
                              .order_by(StoredFile.created_at.desc()).limit(100)).scalars().all()
    names = clinic_names(p.center_id, [f.clinic_id for f in rows])
    items = []
    for f in rows:
        j = core_files.serialize(f, p)
        j["clinic_name"] = names.get(f.clinic_id)
        items.append(j)
    return {"items": items}

