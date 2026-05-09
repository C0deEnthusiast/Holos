"""
Shared FastAPI dependencies for backend_v2.

Provides:
- get_supabase()          — module-level Supabase singleton
- get_current_user_id()   — async auth dependency (mirrors routes/auth.py)
"""
import asyncio
from typing import Optional

from fastapi import Header
from supabase import create_client, Client

from config import Config
from observability import get_logger

log = get_logger("backend_v2.deps", agent_id="4")

# Duplicated from routes/auth.py to avoid circular import (routes/auth imports Flask app context)
_TEST_ACCOUNTS_ACTIVE = Config.DEBUG and Config.ENABLE_TEST_ACCOUNTS

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


def _ensure_profile_v2(user_id: str) -> None:
    """Idempotent profile creation for mock tokens. Duplicated from routes/auth.py."""
    supabase = get_supabase()
    if not supabase or not user_id:
        return
    try:
        check = supabase.table("profiles").select("id").eq("id", user_id).execute()
        if not check.data:
            supabase.table("profiles").insert({"id": user_id, "display_name": "Team Account"}).execute()
            log.info("profile_auto_created_v2", user_id=user_id)
    except Exception as err:
        log.warning("profile_auto_create_failed_v2", user_id=user_id, error=str(err))

# ── Supabase singleton ────────────────────────────────────────────────────────

_supabase_client: Optional[Client] = None


def get_supabase() -> Optional[Client]:
    global _supabase_client
    if _supabase_client is None:
        url = Config.SUPABASE_URL
        key = Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY
        if url and key:
            _supabase_client = create_client(url, key)
            log.info("supabase_connected_v2")
        else:
            log.warning("supabase_not_configured_v2")
    return _supabase_client


# ── Auth dependency ───────────────────────────────────────────────────────────

async def get_current_user_id(authorization: str = Header(default="")) -> Optional[str]:
    """
    FastAPI equivalent of routes/auth.py:get_current_user_id().
    Returns the Supabase user UUID, or None if unauthenticated.
    Endpoints that require auth should raise HTTPException(401) themselves
    when this returns None.
    """
    if not authorization.startswith("Bearer "):
        return None

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None

    if _TEST_ACCOUNTS_ACTIVE and token in MOCK_TOKEN_MAP:
        user_id = MOCK_TOKEN_MAP[token]
        log.debug("auth_mock_token_v2", user_id=user_id)
        await asyncio.to_thread(_ensure_profile_v2, user_id)
        return user_id

    supabase = get_supabase()
    if supabase:
        try:
            user_res = await asyncio.to_thread(supabase.auth.get_user, token)
            if user_res and user_res.user:
                log.debug("auth_success_v2", user_id=user_res.user.id)
                return user_res.user.id
            log.warning("auth_token_no_user_v2")
            return None
        except Exception as e:
            log.warning("auth_token_invalid_v2", error=str(e))
            return None

    if Config.DEBUG:
        log.warning("auth_supabase_unavailable_dev_v2")
        return None

    log.warning("auth_rejected_no_supabase_v2")
    return None
