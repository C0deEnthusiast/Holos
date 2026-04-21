"""
Authentication Routes — Agent 1 Hardened
Security changes per Holos v2 brief §9.1:
- Removed default-UUID-000 fallback
- TEST_ACCOUNTS/MOCK_TOKEN_MAP are env-gated and production-blocked
- Demo endpoint removed from production
- Fail-closed auth: unknown token = 401, no fallback
"""
import os
import logging
from functools import wraps

import structlog
from flask import Blueprint, request, jsonify, g
from config import Config

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
log = structlog.get_logger("holos.auth")

# ---------------------------------------------------------------------------
# Test accounts — env-gated, REFUSED in production
# Credentials are in-process only (not in DB, not in .env by default).
# Set ENABLE_TEST_ACCOUNTS=true in local .env only.
# ---------------------------------------------------------------------------
_ENV = os.environ.get("ENV", "development").lower()

_TEST_ACCOUNTS: dict[str, str] = {}
_MOCK_TOKEN_MAP: dict[str, str] = {}

if Config.ENABLE_TEST_ACCOUNTS:
    if _ENV == "production":
        raise RuntimeError(
            "ENABLE_TEST_ACCOUNTS=true is not allowed in production. "
            "Set ENV=production and ENABLE_TEST_ACCOUNTS=false."
        )
    _TEST_ACCOUNTS = {
        "admin@holos.com":   "holos2026",
        "tester1@holos.com": "holos2026",
        "tester2@holos.com": "holos2026",
    }
    _MOCK_TOKEN_MAP = {
        "mock_token_admin":   "11111111-1111-1111-1111-111111111111",
        "mock_token_tester1": "22222222-2222-2222-2222-222222222222",
        "mock_token_tester2": "33333333-3333-3333-3333-333333333333",
    }


def get_supabase():
    """Lazy import to avoid circular dependency."""
    from app import supabase
    return supabase


def get_current_user_id() -> str | None:
    """
    Extract user_id from the request JWT. Fail-closed:
    - Invalid / unknown token → None (caller must 401)
    - No fallback to a default user. Ever.
    - Test mock tokens only work when ENABLE_TEST_ACCOUNTS=true AND ENV != production.
    """
    supabase = get_supabase()
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()

    # Hard-reject obviously bad tokens
    if not token or token in ("null", "undefined", "mock_token"):
        return None

    # Test account mock tokens (dev only)
    if _MOCK_TOKEN_MAP and token in _MOCK_TOKEN_MAP:
        user_id = _MOCK_TOKEN_MAP[token]
        log.debug("auth_mock_token", user_id=user_id)
        _ensure_profile(supabase, user_id, "Holos Test User")
        return user_id

    # Supabase JWT verification
    if supabase:
        try:
            user_res = supabase.auth.get_user(token)
            if user_res and user_res.user:
                user_id = user_res.user.id
                _ensure_profile(supabase, user_id, user_res.user.email or "")
                return user_id
        except Exception as e:
            log.warning("auth_token_invalid", error=str(e))

    return None


def _ensure_profile(supabase, user_id: str, display_name: str) -> None:
    """Auto-create a profiles row if it doesn't exist yet."""
    if not supabase:
        return
    try:
        existing = supabase.table("profiles").select("id").eq("id", user_id).execute()
        if not existing.data:
            supabase.table("profiles").insert({
                "id": user_id,
                "full_name": display_name,
            }).execute()
            log.info("profile_created", user_id=user_id)
    except Exception as e:
        log.warning("profile_create_failed", user_id=user_id, error=str(e))


def require_auth(f):
    """Decorator that enforces authentication and sets g.user_id."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        g.user_id = user_id
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    supabase = get_supabase()
    if not supabase:
        return jsonify({"error": "Auth service unavailable"}), 503

    try:
        res = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {"data": {"full_name": full_name}},
        })
        return jsonify({"success": True, "user": res.user.model_dump() if res.user else None})
    except Exception as e:
        log.warning("register_failed", email=email, error=str(e))
        return jsonify({"error": str(e)}), 400


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    # Test accounts (dev only)
    if _TEST_ACCOUNTS and email in _TEST_ACCOUNTS and password == _TEST_ACCOUNTS[email]:
        mock_token = f"mock_token_{email.split('@')[0]}"
        log.info("auth_test_account_login", email=email)
        return jsonify({
            "success": True,
            "session": {"access_token": mock_token},
            "user": {
                "email": email,
                "user_metadata": {"full_name": f"{email.split('@')[0].capitalize()} (Test)"},
            },
        })

    supabase = get_supabase()
    if not supabase:
        return jsonify({"error": "Auth service unavailable"}), 503

    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return jsonify({
            "success": True,
            "session": res.session.model_dump() if res.session else None,
            "user": res.user.model_dump() if res.user else None,
        })
    except Exception as e:
        error_msg = str(e)
        if "Email not confirmed" in error_msg:
            error_msg = "Email not confirmed. Check your inbox."
        log.warning("login_failed", email=email)
        return jsonify({"error": error_msg}), 400


@auth_bp.route("/demo", methods=["POST"])
def demo_login():
    """Quick demo login — dev/staging only, blocked in production."""
    if not Config.ENABLE_TEST_ACCOUNTS or _ENV == "production":
        return jsonify({"error": "Demo not available"}), 403

    mock_token = "mock_token_admin"
    return jsonify({
        "success": True,
        "session": {"access_token": mock_token},
        "user": {
            "email": "admin@holos.com",
            "user_metadata": {"full_name": "Holos Demo"},
        },
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    supabase = get_supabase()
    if not supabase:
        return jsonify({"success": True})
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            supabase.auth.global_sign_out(token)
        return jsonify({"success": True})
    except Exception as e:
        log.warning("logout_error", error=str(e))
        return jsonify({"success": True})  # Always succeed logout from client's perspective
