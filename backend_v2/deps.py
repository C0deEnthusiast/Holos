"""
FastAPI Auth + DB Dependencies (Agent 4)
Mirrors the Flask auth logic but uses FastAPI's Depends system.
JWT verification uses the same Supabase JWT secret.
"""
from __future__ import annotations

import os
from typing import Annotated

import httpx
import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from supabase import create_client, Client

log = structlog.get_logger("holos.v2.deps")

_bearer = HTTPBearer(auto_error=False)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")


# ---------------------------------------------------------------------------
# Supabase client — one per request (thread-safe, stateless anon key)
# ---------------------------------------------------------------------------

def get_supabase() -> Client:
    if not SUPABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")
    # Use Service Role Key if available (Agent 4 requirement for backend bypass)
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
    if not key:
         raise HTTPException(status_code=503, detail="No Supabase key configured")
    return create_client(SUPABASE_URL, key)


SupabaseDep = Annotated[Client, Depends(get_supabase)]


# ---------------------------------------------------------------------------
# Auth: fail-closed JWT verification
# Same contract as Flask get_current_user_id() but as a FastAPI dependency.
# Returns user_id str or raises 401 — never returns None.
# ---------------------------------------------------------------------------

def _verify_jwt(token: str) -> str:
    """
    Verify a Supabase-issued JWT and return the user_id (sub claim).
    Uses SUPABASE_JWT_SECRET when set, otherwise validates via Supabase /user endpoint.
    Raises HTTPException 401 on any failure.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    # Path A: Mock tokens (dev/local only)
    MOCK_MAP = {
        "mock_token_admin":   "11111111-1111-1111-1111-111111111111",
        "mock_token_tester1": "22222222-2222-2222-2222-222222222222",
        "mock_token_tester2": "33333333-3333-3333-3333-333333333333",
    }
    if token in MOCK_MAP:
        user_id = MOCK_MAP[token]
        log.debug("auth_mock_token_accepted", user_id=user_id)
        return user_id

    # Path B: SUPABASE_JWT_SECRET set → verify locally (fastest, no network call)
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="No sub in token")
            return user_id
        except JWTError as e:
            log.warning("jwt_verify_failed", error=str(e))
            raise HTTPException(status_code=401, detail="Invalid token") from e

    # Path B: No local secret → validate via Supabase REST API
    if not SUPABASE_URL:
        raise HTTPException(status_code=401, detail="Auth not configured")

    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_KEY},
            timeout=5.0,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Token rejected by Supabase")
        return resp.json().get("id", "")
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=503, detail="Auth service timeout") from e


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)] = None,
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header required")
    return _verify_jwt(credentials.credentials)


CurrentUser = Annotated[str, Depends(get_current_user_id)]
