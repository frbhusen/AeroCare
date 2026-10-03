"""Core (non-module) API blueprints: auth/session, notifications, undo, health."""


def blueprints():
    from .auth import bp as auth_bp
    from .common import bp as common_bp
    return [auth_bp, common_bp]
