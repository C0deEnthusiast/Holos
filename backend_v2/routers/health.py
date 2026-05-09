"""Health endpoints for backend_v2."""
from fastapi import APIRouter

from observability import (
    get_uptime_seconds,
    check_supabase_status,
    check_gemini_status,
    get_sentry_status,
    get_last_scan_cost,
)
from backend_v2.dependencies import get_supabase

router = APIRouter(prefix="/api/v2", tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@router.get("/health/detailed")
async def health_detailed():
    sb = get_supabase()
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime_seconds": get_uptime_seconds(),
        "supabase": check_supabase_status(sb),
        "gemini": check_gemini_status(),
        "sentry": get_sentry_status(),
        "last_scan_cost_cents": get_last_scan_cost(),
    }
