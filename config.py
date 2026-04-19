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

    # Feature Flags
    ENABLE_TEST_ACCOUNTS = os.environ.get("ENABLE_TEST_ACCOUNTS", "true").lower() == "true"
    ENABLE_SNIPER_MODE = os.environ.get("ENABLE_SNIPER_MODE", "true").lower() == "true"

    @classmethod
    def validate(cls):
        """Validate that required config is present."""
        missing = []
        if not cls.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not cls.SUPABASE_KEY and not cls.SUPABASE_SERVICE_ROLE_KEY:
            missing.append("SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY")
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if missing:
            print(f"⚠️  WARNING: Missing environment variables: {', '.join(missing)}")
        return len(missing) == 0
