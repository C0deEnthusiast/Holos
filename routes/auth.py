"""
Authentication Routes — Agent 1: Hardened Auth
Handles login, registration, logout, and user identity resolution.

Security model:
- Production: only real Supabase JWT tokens are accepted. No fallbacks.
- Development (DEBUG=True + ENABLE_TEST_ACCOUNTS=True): mock tokens accepted for team accounts.
- ensure_profile() is extracted and idempotent — safe to call from any route.
"""
from flask import Blueprint, request, jsonify
from config import Config
from observability import get_logger

log = get_logger("auth", agent_id="1")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ── Team prototype accounts ────────────────────────────────────────────────
# These are ONLY active when Config.DEBUG=True AND Config.ENABLE_TEST_ACCOUNTS=True.
TEST_ACCOUNTS = {
    "admin@holos.com":   "holos2026",
    "tester1@holos.com": "holos2026",
    "tester2@holos.com": "holos2026",
    "guest@holos.com":   "holos2026",
    "demo@holos.com":    "holos2026",
    "manager@holos.com": "holos2026",
    "user1@holos.com":   "holos2026",
    "user2@holos.com":   "holos2026",
}

MOCK_TOKEN_MAP = {
    "mock_token_admin":          "11111111-1111-1111-1111-111111111111",
    "mock_token_tester1":        "22222222-2222-2222-2222-222222222222",
    "mock_token_tester2":        "33333333-3333-3333-3333-333333333333",
    "mock_token_guest":          "44444444-4444-4444-4444-444444444444",
    "mock_token_demo":           "00000000-0000-0000-0000-000000000000",
    "mock_token_manager":        "55555555-5555-5555-5555-555555555555",
    "mock_token_user1":          "66666666-6666-6666-6666-666666666666",
    "mock_token_user2":          "77777777-7777-7777-7777-777777777777",
    "mock_token_for_prototype":  "00000000-0000-0000-0000-000000000000",
}

_TEST_ACCOUNTS_ACTIVE = Config.DEBUG and Config.ENABLE_TEST_ACCOUNTS


def get_supabase():
    from app import supabase
    return supabase


# ── Profile helper ─────────────────────────────────────────────────────────

def ensure_profile(user_id: str, display_name: str = "Holos User") -> None:
    """
    Idempotent: create a profiles row for user_id if one does not exist.
    Silently skips if Supabase is unavailable or the insert fails.
    """
    supabase = get_supabase()
    if not supabase or not user_id:
        return
    try:
        check = supabase.table("profiles").select("id").eq("id", user_id).execute()
        if not check.data:
            supabase.table("profiles").insert({"id": user_id, "display_name": display_name}).execute()
            log.info("profile_auto_created", user_id=user_id)
    except Exception as err:
        log.warning("profile_auto_create_failed", user_id=user_id, error=str(err))


# ── Identity resolution ────────────────────────────────────────────────────

def get_current_user_id() -> str | None:
    """
    Resolve the authenticated user from the request's Bearer token.

    Production (DEBUG=False):
        - Only real Supabase JWTs are accepted.
        - Any failure → return None. No fallbacks.

    Development (DEBUG=True + ENABLE_TEST_ACCOUNTS=True):
        - Mock tokens from MOCK_TOKEN_MAP are accepted.

    Returns the user UUID string or None if authentication failed.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        log.debug("auth_no_bearer_header")
        return None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    # ── Dev-only: mock token path ──────────────────────────────
    if _TEST_ACCOUNTS_ACTIVE and token in MOCK_TOKEN_MAP:
        user_id = MOCK_TOKEN_MAP[token]
        log.debug("auth_mock_token", user_id=user_id)
        ensure_profile(user_id, display_name="Team Account")
        return user_id

    # ── Primary path: real Supabase JWT verification ──────────
    supabase = get_supabase()
    if supabase:
        try:
            user_res = supabase.auth.get_user(token)
            if user_res and user_res.user:
                user_id = user_res.user.id
                log.debug("auth_success", user_id=user_id)
                ensure_profile(user_id)
                return user_id
            log.warning("auth_token_no_user")
            return None
        except Exception as e:
            log.warning("auth_token_invalid", error=str(e))
            return None

    # ── Dev-only fallback: no Supabase configured ──────────────
    # Allows local development without a Supabase instance.
    if Config.DEBUG:
        log.warning("auth_supabase_unavailable_dev_fallback")
        return None

    log.warning("auth_rejected_no_supabase_in_production")
    return None


# ─── Endpoints ────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")
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
        log.info("user_registered", email=email)
        return jsonify({"success": True, "user": res.user.model_dump() if res.user else None})
    except Exception as e:
        log.warning("register_failed", email=email, error=str(e))
        return jsonify({"error": str(e)}), 400


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    # ── Dev-only: team test accounts ──────────────────────────
    if _TEST_ACCOUNTS_ACTIVE and email in TEST_ACCOUNTS:
        if password != TEST_ACCOUNTS[email]:
            log.warning("test_account_wrong_password", email=email)
            return jsonify({"error": "Invalid credentials"}), 401
        mock_token = f"mock_token_{email.split('@')[0]}"
        log.info("test_account_login", email=email)
        return jsonify({
            "success": True,
            "session": {"access_token": mock_token},
            "user": {
                "email": email,
                "user_metadata": {"full_name": email.split("@")[0].capitalize() + " (Team Account)"},
            },
        })

    supabase = get_supabase()
    if not supabase:
        return jsonify({"error": "Auth service unavailable"}), 503

    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        log.info("user_login_success", email=email)
        return jsonify({
            "success": True,
            "session": res.session.model_dump() if res.session else None,
            "user": res.user.model_dump() if res.user else None,
        })
    except Exception as e:
        error_msg = str(e)
        if "Email not confirmed" in error_msg:
            error_msg = (
                "Your email has not been confirmed yet. "
                "Check your inbox or use a Holos Test Account (e.g., admin@holos.com / holos2026)."
            )
        log.warning("user_login_failed", email=email, error=error_msg)
        return jsonify({"error": error_msg}), 400


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
        log.info("user_logout")
        return jsonify({"success": True})
    except Exception as e:
        log.warning("logout_failed", error=str(e))
        return jsonify({"error": str(e)}), 400
