"""
Authentication Routes
Handles login, registration, logout, and user identity.
"""
from flask import Blueprint, request, jsonify
from config import Config

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# -------------------------------------------------------------------
# Team prototype accounts (gated behind ENABLE_TEST_ACCOUNTS flag)
# -------------------------------------------------------------------
TEST_ACCOUNTS = {
    "admin@holos.com": "holos2026",
    "tester1@holos.com": "holos2026",
    "tester2@holos.com": "holos2026",
    "guest@holos.com": "holos2026",
    "demo@holos.com": "holos2026",
    "manager@holos.com": "holos2026",
    "user1@holos.com": "holos2026",
    "user2@holos.com": "holos2026",
}

MOCK_TOKEN_MAP = {
    "mock_token_admin": "11111111-1111-1111-1111-111111111111",
    "mock_token_tester1": "22222222-2222-2222-2222-222222222222",
    "mock_token_tester2": "33333333-3333-3333-3333-333333333333",
    "mock_token_guest": "44444444-4444-4444-4444-444444444444",
    "mock_token_demo": "00000000-0000-0000-0000-000000000000",
    "mock_token_manager": "55555555-5555-5555-5555-555555555555",
    "mock_token_user1": "66666666-6666-6666-6666-666666666666",
    "mock_token_user2": "77777777-7777-7777-7777-777777777777",
    "mock_token_for_prototype": "00000000-0000-0000-0000-000000000000",
}


def get_supabase():
    """Lazy import to avoid circular dependency."""
    from app import supabase
    return supabase


def get_current_user_id():
    """Extract user_id from the request and ensure a DB profile exists."""
    supabase = get_supabase()
    user_id = None
    auth_header = request.headers.get("Authorization")

    # 1. Try Bearer Token
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

        if Config.ENABLE_TEST_ACCOUNTS and token in MOCK_TOKEN_MAP:
            user_id = MOCK_TOKEN_MAP[token]
        elif token in ("mock_token", "null", ""):
            user_id = "00000000-0000-0000-0000-000000000000"
        elif supabase:
            try:
                user_res = supabase.auth.get_user(token)
                if user_res.user:
                    user_id = user_res.user.id
            except Exception:
                pass

    # 2. Fallback to form data / default
    if not user_id:
        user_id = request.form.get("user_id") or "00000000-0000-0000-0000-000000000000"

    # 3. Auto-create profile if needed
    if user_id and supabase:
        try:
            profile_check = supabase.table("profiles").select("id").eq("id", user_id).execute()
            if not profile_check.data:
                print(f"DEBUG: Profile missing for {user_id}. Auto-creating...")
                display = "Demo User" if user_id.startswith("0000") else "Holos User"
                supabase.table("profiles").insert({"id": user_id, "display_name": display}).execute()
                print(f"DEBUG: Created profile for {user_id}")
        except Exception as err:
            print(f"WARNING: Could not auto-create profile for {user_id}: {err}")

    return user_id


# ─── Endpoints ───────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    full_name = data.get("full_name", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    supabase = get_supabase()
    if not supabase:
        return jsonify({"success": True})

    try:
        res = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {"data": {"full_name": full_name}},
        })
        return jsonify({"success": True, "user": res.user.model_dump() if res.user else None})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    # Team test accounts (gated)
    if Config.ENABLE_TEST_ACCOUNTS and email in TEST_ACCOUNTS and password == TEST_ACCOUNTS[email]:
        mock_token = f"mock_token_{email.split('@')[0]}"
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
        if password == "password":
            return jsonify({
                "success": True,
                "session": {"access_token": "mock_token"},
                "user": {"email": email, "user_metadata": {"full_name": email.split("@")[0]}},
            })
        return jsonify({"error": "Supabase not configured. Use password 'password' for local testing."}), 500

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
            error_msg = (
                "Your email has not been confirmed yet. "
                "Check your inbox or use a Holos Test Account (e.g., admin@holos.com / holos2026)."
            )
        print(f"Login Error: {e}")
        return jsonify({"error": error_msg}), 400


@auth_bp.route("/logout", methods=["POST"])
def logout():
    supabase = get_supabase()
    if not supabase:
        return jsonify({"success": True})
    try:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            supabase.auth.global_sign_out(token)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
