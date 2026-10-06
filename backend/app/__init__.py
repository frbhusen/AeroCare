"""Flask application factory."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()


def _configure_logging(app):
    level = logging.DEBUG if app.debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    if not app.config.get("TESTING"):
        log_dir = Path(app.config["LOG_DIR"])
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    # Never log request bodies: they may contain medical or financial content.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


# While an administrator-chosen password is active, only these endpoints work (spec §7 resets).
PASSWORD_CHANGE_ALLOWED = {"/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout",
                           "/api/v1/notifications", "/api/v1/platform/branding"}


def create_app(config_name=None, **overrides):
    from .config import get_config
    from .extensions import db
    from .core import tenancy  # noqa: F401  (registers the after_begin listener)
    from .core.errors import register_error_handlers
    from .core.security import csrf_check, security_headers, idempotency_before, idempotency_after, \
        idempotency_teardown
    from .auth.service import load_request_principal
    from .modules import load_all
    from . import api as core_api

    app = Flask(__name__, static_folder=None)
    app.config.from_object(get_config(config_name))
    app.config.update(overrides)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL must be set")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    db.init_app(app)
    _configure_logging(app)
    register_error_handlers(app)

    for bp in core_api.blueprints() + load_all():
        app.register_blueprint(bp, url_prefix="/api/v1" + (bp.url_prefix or ""))

    @app.before_request
    def _auth():
        g.principal = None
        if request.path.startswith("/api/"):
            load_request_principal()
            csrf_check()
            p = g.principal
            if p is not None and getattr(p.user, "must_change_password", False) and request.path not in PASSWORD_CHANGE_ALLOWED:
                from .core.errors import error_body
                return error_body("password_change_required",
                                  "Please choose a new password before continuing.", status=403)
            return idempotency_before()

    @app.after_request
    def _after(resp):
        if request.path.startswith("/api/"):
            resp = idempotency_after(resp)
        return security_headers(resp)

    @app.teardown_request
    def _teardown(exc):
        idempotency_teardown(exc)
        tenancy.clear()

    from .cli import register_cli
    register_cli(app)

    if app.config["SERVE_FRONTEND"]:
        web_root = app.config["WEB_ROOT"]

        @app.route("/")
        def index():
            return send_from_directory(web_root, "index.html")

        @app.route("/<path:path>")
        def static_files(path):
            if path.startswith("api/"):
                from .core.errors import error_body
                return error_body("not_found", "Not found", status=404)
            full = os.path.join(web_root, path)
            if os.path.isfile(full):
                resp = send_from_directory(web_root, path)
                if path == "sw.js":
                    resp.headers["Cache-Control"] = "no-cache"
                return resp
            return send_from_directory(web_root, "index.html")

    if app.config.get("RUN_BACKGROUND_PURGER") and os.environ.get("HC_DISABLE_PURGER") != "1":
        from .services.deletion import start_background_purger
        start_background_purger(app)
    return app
