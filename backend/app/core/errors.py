"""Uniform API errors.

Error body (all /api/* errors):
    {"error": {"code": "not_found", "message": "Patient not found", "details": {...}}}
"""
import logging

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError, OperationalError, DBAPIError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException

log = logging.getLogger("hc.errors")


class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message=None, *, code=None, status=None, details=None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or "Request failed"
        if code:
            self.code = code
        if status:
            self.status = status
        self.details = details


class ValidationError(ApiError):
    status, code = 422, "validation_error"


class Unauthorized(ApiError):
    status, code = 401, "unauthorized"


class Forbidden(ApiError):
    status, code = 403, "forbidden"


class NotFound(ApiError):
    status, code = 404, "not_found"


class Conflict(ApiError):
    status, code = 409, "conflict"


class TooManyRequests(ApiError):
    status, code = 429, "rate_limited"


def error_body(code, message, details=None, status=400):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app):
    from backend.app.extensions import db

    def _is_api():
        return request.path.startswith("/api/")

    @app.errorhandler(ApiError)
    def _api_error(e):
        db.session.rollback()
        return error_body(e.code, e.message, e.details, e.status)

    @app.errorhandler(StaleDataError)
    def _stale(e):
        db.session.rollback()
        return error_body("version_conflict", "This record was changed by someone else. Reload and try again.",
                          status=409)

    @app.errorhandler(IntegrityError)
    def _integrity(e):
        db.session.rollback()
        diag = getattr(getattr(e, "orig", None), "diag", None)
        cname = getattr(diag, "constraint_name", None) or ""
        log.warning("integrity error constraint=%s path=%s", cname, request.path)
        if cname.startswith("ex_appointments_"):
            return error_body("appointment_conflict",
                              "The doctor or clinic already has an appointment at that time.",
                              {"constraint": cname}, 409)
        return error_body("integrity_error", "The request conflicts with existing data.", {"constraint": cname}, 409)

    @app.errorhandler(OperationalError)
    @app.errorhandler(DBAPIError)
    def _db_error(e):
        db.session.rollback()
        log.error("database error path=%s: %s", request.path, type(e.orig).__name__ if hasattr(e, "orig") else e)
        return error_body("database_error", "A database error occurred.", status=500)

    @app.errorhandler(HTTPException)
    def _http(e):
        if not _is_api():
            return e
        code = (e.name or "error").lower().replace(" ", "_")
        return error_body(code, e.description or e.name, status=e.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(e):
        db.session.rollback()
        log.exception("unhandled error path=%s", request.path)
        if app.config.get("TESTING"):
            raise e
        return error_body("server_error", "An unexpected error occurred.", status=500)
