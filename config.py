"""
Holos Configuration — Agent 1 Hardened
- SECRET_KEY fails closed in production
- FLASK_DEBUG defaults to false
- GOOGLE_API_KEY no longer falls back to GEMINI_API_KEY
- Validates critical secrets at startup
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path, override=True)

_ENV = os.environ.get("ENV", "development").lower()
_IS_PRODUCTION = _ENV == "production"

_DEFAULT_SECRET = "holos-dev-secret-NOT-FOR-PRODUCTION"


class Config:
    """Centralized configuration. All values from environment — never hardcoded secrets."""

    ENV = _ENV

    # Flask
    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.environ.get("SECRET_KEY", _DEFAULT_SECRET)

    # Upload
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Supabase — use anon key in request path; service role for migrations only
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    # AI
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    GEMINI_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash-preview-04-17")
    GEMINI_PRICING_MODEL = os.environ.get("GEMINI_PRICING_MODEL", "gemini-2.5-pro-preview-03-25")

    # Google Custom Search (product images — NOT the Gemini key)
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")  # CSE key only
    GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")

    # Feature flags — default OFF; explicitly enabled in dev .env
    ENABLE_TEST_ACCOUNTS = os.environ.get("ENABLE_TEST_ACCOUNTS", "false").lower() == "true"
    ENABLE_SNIPER_MODE = os.environ.get("ENABLE_SNIPER_MODE", "false").lower() == "true"

    @classmethod
    def validate(cls) -> bool:
        """
        Validate required config at startup. Fail-closed in production:
        - Insecure SECRET_KEY → RuntimeError
        - Missing SUPABASE_URL/KEY → RuntimeError in production, warning in dev
        """
        if _IS_PRODUCTION:
            if cls.SECRET_KEY == _DEFAULT_SECRET:
                raise RuntimeError(
                    "SECRET_KEY is set to the insecure default. "
                    "Set a strong random SECRET_KEY in production."
                )
            if cls.DEBUG:
                raise RuntimeError("FLASK_DEBUG must be false in production.")
            if cls.ENABLE_TEST_ACCOUNTS:
                raise RuntimeError("ENABLE_TEST_ACCOUNTS must be false in production.")

        missing = []
        if not cls.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not cls.SUPABASE_KEY:
            missing.append("SUPABASE_KEY")
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")

        if missing:
            msg = f"Missing environment variables: {', '.join(missing)}"
            if _IS_PRODUCTION:
                raise RuntimeError(msg)
            import structlog
            structlog.get_logger("holos.config").warning("config_missing", missing=missing)

        return len(missing) == 0
