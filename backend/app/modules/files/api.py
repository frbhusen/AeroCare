"""/files — patient file upload, list, authorized content download, rename, annotate,
delete+undo, share/unshare, storage usage."""
from flask import Blueprint, jsonify, request, send_file

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.errors import NotFound
from backend.app.core.storage import ALLOWED, IMAGE_MIMES, get_storage
from backend.app.core.validation import request_json
from backend.app.models.files import FILE_CATEGORIES
from backend.app.modules.patients.helpers import accessible_clinics
from backend.app.modules.patients.summary import register_summary_provider
from backend.app.services import files as core_files

from . import service

register_summary_provider("files", service.summary_section, order=50)

bp = Blueprint("files", __name__, url_prefix="/files")

INLINE_MIMES = IMAGE_MIMES | {"application/pdf"}


@bp.get("/meta")
@login_required
def meta():
    p = current_principal()
    p.require("files.view")
    from flask import current_app
    return jsonify({
        "categories": list(FILE_CATEGORIES), "upload_categories": list(service.UPLOAD_CATEGORIES),
        "allowed_extensions": sorted(ALLOWED), "max_file_bytes": current_app.config["MAX_FILE_BYTES"],
        "max_files_per_upload": 20, "annotation_types": list(service.ANNOTATION_TYPES),
        "clinics": accessible_clinics(p) if p.has("files.upload") else [],
        "permissions": {k: p.has(k) for k in ("files.upload", "files.edit", "files.delete", "files.share")},
    })


@bp.get("/storage")
@login_required
def storage():
    p = current_principal()
    p.require("files.view")
    return jsonify(core_files.storage_usage(p.center_id))


@bp.get("/share-targets")
@login_required
def share_targets():
    return jsonify(service.share_targets(current_principal()))


@bp.get("")
@login_required
def list_files():
    return jsonify(service.list_files(current_principal(), request.args.to_dict()))


@bp.post("")
@login_required
def upload():
    p = current_principal()
    uploads = request.files.getlist("files") + request.files.getlist("file")
    rows = service.upload(p, request.form.to_dict(), uploads)
    return jsonify({"items": [core_files.serialize(f, p) for f in rows],
                    "storage": core_files.storage_usage(p.center_id)}), 201


@bp.get("/<int:file_id>")
@login_required
def get(file_id):
    p = current_principal()
    f = service.get_file(p, file_id)
    out = core_files.serialize(f, p)
    if core_files.can_manage(p, f) and p.has("files.share"):
        out["shares"] = service.list_shares(p, file_id)
    return jsonify(out)


@bp.get("/<int:file_id>/content")
@login_required
def content(file_id):
    """Authorized byte download. Images/PDF inline (unless ?download=1), everything else as an
    attachment. MIME type comes from server-side sniffing at upload, never from the client."""
    p = current_principal()
    f = service.get_file(p, file_id)
    storage = get_storage()
    try:
        path = storage.path(f.storage_key)
    except ValueError:
        raise NotFound("File not found")
    if not path.exists():
        raise NotFound("File content is not available")
    inline = f.mime_type in INLINE_MIMES and request.args.get("download") not in ("1", "true")
    resp = send_file(path, mimetype=f.mime_type, as_attachment=not inline, download_name=f.display_name,
                     conditional=True, etag=f.sha256, max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, no-store"
    # Same-origin preview (img/iframe) is allowed; nothing in the file may run scripts.
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Content-Security-Policy"] = ("default-src 'none'; img-src 'self' data: blob:; "
                                               "style-src 'unsafe-inline'; frame-ancestors 'self'")
    return resp


@bp.patch("/<int:file_id>")
@login_required
def update(file_id):
    p = current_principal()
    return jsonify(core_files.serialize(service.update(p, file_id, request_json()), p))


@bp.put("/<int:file_id>/annotations")
@login_required
def annotations(file_id):
    p = current_principal()
    return jsonify(core_files.serialize(service.save_annotations(p, file_id, request_json()), p))


@bp.delete("/<int:file_id>")
@login_required
def delete(file_id):
    return jsonify(service.delete(current_principal(), file_id)), 202


@bp.get("/<int:file_id>/shares")
@login_required
def list_shares(file_id):
    return jsonify({"items": service.list_shares(current_principal(), file_id)})


@bp.post("/<int:file_id>/shares")
@login_required
def add_share(file_id):
    return jsonify(service.add_share(current_principal(), file_id, request_json())), 201


@bp.delete("/<int:file_id>/shares/<int:share_id>")
@login_required
def remove_share(file_id, share_id):
    return jsonify(service.remove_share(current_principal(), file_id, share_id))
