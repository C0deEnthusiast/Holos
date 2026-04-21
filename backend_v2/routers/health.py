"""GET /v2/health — live DB ping, version, model."""
import os
import structlog
from fastapi import APIRouter
from backend_v2.models import HealthResponse
import scanner

router = APIRouter(tags=["Health"])
log = structlog.get_logger("holos.v2.health")

APP_VERSION = "2.0.0"


@router.get("/health", response_model=HealthResponse)
def health_check():
    # DB ping
    db_status = "unavailable"
    try:
        from supabase import create_client
        sb = create_client(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_KEY", ""),
        )
        sb.table("items").select("id").limit(1).execute()
        db_status = "connected"
    except Exception as e:
        log.warning("db_ping_failed", error=str(e))

    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        db=db_status,
        model=scanner.VISION_MODEL,
    )
