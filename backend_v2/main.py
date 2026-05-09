"""
Holos backend_v2 — Agent 4: Strangler-Fig FastAPI Migration

Runs alongside the Flask app (Flask on :5001, FastAPI on :8001).
All existing Flask routes remain untouched. Migrate endpoints here one
at a time, then cut over via a reverse proxy once each route is validated.

Migration order (highest value first):
  1. POST /api/v2/scan          ← async AI scan (done)
  2. GET  /api/v2/health        ← liveness / detailed health (done)
  3. POST /api/v2/items         ← manual save
  4. GET  /api/v2/items         ← item listing
  ... remaining routes as validated
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import Config
from observability import get_logger, setup_observability

log = get_logger("backend_v2", agent_id="4")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.validate()
    log.info("fastapi_v2_starting", port=8001, debug=Config.DEBUG)
    yield
    log.info("fastapi_v2_shutdown")


app = FastAPI(
    title="Holos API v2",
    description="Async FastAPI backend — Strangler-Fig migration from Flask",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v2/docs",
    redoc_url="/api/v2/redoc",
    openapi_url="/api/v2/openapi.json",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Tighten allow_origins before production cutover.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception_v2", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )

# ── Routers ───────────────────────────────────────────────────────────────────

from backend_v2.routers import health, scan, video  # noqa: E402

app.include_router(health.router)
app.include_router(scan.router)
app.include_router(video.router)
