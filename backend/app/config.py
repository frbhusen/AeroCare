"""Application configuration. All secrets/deployment values come from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    ENV_NAME = os.environ.get("FLASK_ENV", "production")
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SCHEMA_DATABASE_URL = os.environ.get("SCHEMA_DATABASE_URL")
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        "pool_recycle": 1800,
        "connect_args": {"options": "-c statement_timeout=30000 -c timezone=UTC"},
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_NAME = "hc_session"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", "365"))

    STORAGE_ROOT = os.environ.get("STORAGE_ROOT", str(BASE_DIR / "storage"))
    BACKUP_ROOT = os.environ.get("BACKUP_ROOT", str(BASE_DIR / "backups"))
    LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
    WEB_ROOT = os.environ.get("WEB_ROOT", str(BASE_DIR / "web"))
    SERVE_FRONTEND = _bool("SERVE_FRONTEND", True)
    PDF_FONT_PATH = os.environ.get("PDF_FONT_PATH")

    MAX_FILE_BYTES = 15 * 1024 * 1024
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 4  # multi-file uploads; each file still capped at 15 MB
    DEFAULT_STORAGE_QUOTA_BYTES = 2 * 1024 ** 3
    TRIAL_DAYS = 14
    UNDO_WINDOW_SECONDS = int(os.environ.get("UNDO_WINDOW_SECONDS", "30"))
    LOGIN_RATE_LIMIT = int(os.environ.get("LOGIN_RATE_LIMIT", "10"))  # failures per window
    LOGIN_RATE_WINDOW_SECONDS = 15 * 60
    RUN_BACKGROUND_PURGER = _bool("RUN_BACKGROUND_PURGER", True)
    TIMEZONE = "Asia/Damascus"
    EMAIL_DOMAIN = "aerodent.com"
    TESTING = False


class DevelopmentConfig(Config):
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://hc_app@127.0.0.1:55432/healthcenter_test")
    SCHEMA_DATABASE_URL = os.environ.get(
        "TEST_SCHEMA_DATABASE_URL", "postgresql+psycopg://hc_schema@127.0.0.1:55432/healthcenter_test")
    RUN_BACKGROUND_PURGER = False
    LOGIN_RATE_LIMIT = 1000
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"  # fast hashing for tests only


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True


def get_config(name=None):
    name = name or os.environ.get("FLASK_ENV", "production")
    return {"development": DevelopmentConfig, "testing": TestingConfig}.get(name, ProductionConfig)
