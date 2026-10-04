"""/api/v1/favorites — clinical favorites (snippets, diagnoses, prescription sets, procedures)."""
from flask import Blueprint, jsonify, request

from backend.app.authz.decorators import login_required
from backend.app.authz.principal import current_principal
from backend.app.core.validation import request_json
from . import service

bp = Blueprint("favorites", __name__, url_prefix="/favorites")


@bp.get("")
@login_required
def list_favorites():
    return jsonify(service.list_favorites(current_principal(), request.args.to_dict()))


@bp.post("")
@login_required
def create():
    p = current_principal()
    return jsonify(service.to_json(service.create(p, request_json()), p)), 201


@bp.patch("/<int:fav_id>")
@login_required
def update(fav_id):
    p = current_principal()
    return jsonify(service.to_json(service.update(p, fav_id, request_json()), p))


@bp.delete("/<int:fav_id>")
@login_required
def delete(fav_id):
    return jsonify(service.delete(current_principal(), fav_id)), 202
