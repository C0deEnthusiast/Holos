"""
Backend v2 — FastAPI Application (Agent 4: Strangler-Fig)

This FastAPI app runs alongside the Flask prototype on a separate port.
- Flask (legacy):  http://localhost:5000/api/*
- FastAPI (v2):    http://localhost:8000/v2/*

Strangler strategy: new traffic goes to /v2. Flask routes stay intact.
Migrate clients one route at a time; kill a Flask route only when its
/v2 counterpart is load-tested and stable.

Run with:
    uvicorn backend_v2.main:app --port 8000 --reload
"""

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend_v2.routers import health, items, scan, scan_video

load_dotenv()

log = structlog.get_logger("holos.v2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("holos_v2_starting", port=8000)
    yield
    log.info("holos_v2_shutdown")


app = FastAPI(
    title="Holos API v2",
    description="AI-powered home inventory — FastAPI backend",
    version="2.0.0",
    docs_url="/v2/docs",
    redoc_url="/v2/redoc",
    openapi_url="/v2/openapi.json",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────
_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    os.getenv("FRONTEND_URL", ""),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in _ALLOWED_ORIGINS if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(health.router,      prefix="/v2")
app.include_router(items.router,       prefix="/v2")
app.include_router(scan.router,        prefix="/v2")
app.include_router(scan_video.router,  prefix="/v2")  # Agent 6: video pipeline
