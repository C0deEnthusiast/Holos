"""
Holos Configuration Module
Centralizes all environment variables and app settings.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Config:
    """Base configuration."""
    # Flask / General
    SECRET_KEY = os.environ.get("SECRET_KEY", "holos-dev-secret-change-me")
    DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

    # Upload
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload

    # Supabase
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    # AI
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

    # Google Custom Search (for web image fallback)
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")

    # Observability (Agent 0B)
    SENTRY_DSN = os.environ.get("SENTRY_DSN")  # optional — skipped silently if absent
    FLASK_ENV = os.environ.get("FLASK_ENV", "development")

    # Feature Flags
    ENABLE_TEST_ACCOUNTS = os.environ.get("ENABLE_TEST_ACCOUNTS", "true").lower() == "true"
    ENABLE_SNIPER_MODE = os.environ.get("ENABLE_SNIPER_MODE", "true").lower() == "true"

    @classmethod
    def validate(cls):
        """
        Validate required config. In production (DEBUG=False) missing secrets raise
        RuntimeError so the app refuses to start rather than running insecurely.
        """
        import structlog
        log = structlog.get_logger("config")

        missing = []
        if not cls.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not cls.SUPABASE_KEY and not cls.SUPABASE_SERVICE_ROLE_KEY:
            missing.append("SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY")
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")

        if missing:
            if cls.DEBUG:
                log.warning("missing_env_vars", variables=missing, note="running in dev mode")
            else:
                raise RuntimeError(
                    f"FATAL: missing required env vars in production: {missing}. "
                    "Set them or set FLASK_DEBUG=true to run in dev mode."
                )

        if not cls.DEBUG and cls.SECRET_KEY == "holos-dev-secret-change-me":
            raise RuntimeError(
                "FATAL: SECRET_KEY is still the default dev value in production. "
                "Set a strong random SECRET_KEY env var."
            )
        elif cls.DEBUG and cls.SECRET_KEY == "holos-dev-secret-change-me":
            log.warning("default_secret_key", note="set SECRET_KEY env var before going to production")

        return len(missing) == 0
