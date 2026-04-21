"""
/v2/scan/video — Video walkthrough upload (Agent 6)

POST /v2/scan/video
    Accepts multipart video upload. Returns 202 + scan_id immediately.
    Processing runs as a FastAPI BackgroundTask.

GET /v2/scan/{scan_id}/status
    Poll for status and results. Returns scan record + items when complete.

Status flow:
    queued → extracting_frames → deduplicating → classifying
           → merging → saving → completed
                    └─ failed (on any unrecoverable error)
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend_v2.deps import CurrentUser, SupabaseDep
from pipeline.pipeline import run_video_pipeline

router = APIRouter(tags=["Scan"])
log = structlog.get_logger("holos.v2.scan_video")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".m4v", ".mkv"}
MAX_VIDEO_MB = 500.0  # hard size cap


class VideoScanResponse(BaseModel):
    success: bool = True
    scan_id: str
    status: str = "queued"
    message: str
    poll_url: str


class ScanStatusResponse(BaseModel):
    success: bool = True
    scan: dict
    items: list[dict] = []


# ── POST /v2/scan/video ───────────────────────────────────────────────────

@router.post("/scan/video", response_model=VideoScanResponse, status_code=202)
async def upload_video_scan(
    background_tasks: BackgroundTasks,
    user_id: CurrentUser,
    supabase: SupabaseDep,
    video: UploadFile = File(...),
    home_name: str = Form("My Home"),
    room_name: str = Form("General Room"),
    user_notes: Optional[str] = Form(None),
):
    """
    Upload a video walkthrough for AI processing.

    Returns immediately with 202 Accepted and a scan_id.
    The video is processed asynchronously; poll GET /v2/scan/{scan_id}/status
    for progress and final results.

    Args:
        video:      Video file (mp4, mov, avi, webm, m4v, mkv ≤ 500MB).
        home_name:  Property name (e.g. "123 Oak Street").
        room_name:  Room being scanned (e.g. "Master Bedroom").
        user_notes: Optional hints for the AI (e.g. "antique furniture from 1890s").
    """
    # ── Validate extension ────────────────────────────────────────────
    ext = os.path.splitext(video.filename or "video.mp4")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported format '{ext}'. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # ── Read + size-check ─────────────────────────────────────────────
    try:
        content = await video.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload read error: {e}")

    size_mb = len(content) / 1_048_576
    if size_mb > MAX_VIDEO_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Video too large ({size_mb:.1f} MB). Maximum is {MAX_VIDEO_MB:.0f} MB.",
        )

    # ── Save to temp file ─────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(content)
        tmp.flush()
        tmp.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Temp file write error: {e}")

    video_path = tmp.name

    # ── Create scan record ────────────────────────────────────────────
    scan_id: Optional[str] = None
    try:
        sr = supabase.table("scans").insert({
            "user_id":   user_id,
            "status":    "queued",
            "home_name": home_name,
            "room_name": room_name,
            "scan_type": "video",
        }).execute()
        if sr.data:
            scan_id = sr.data[0]["id"]
    except Exception as e:
        os.unlink(video_path)
        log.error("scan_record_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Could not create scan record")

    if not scan_id:
        os.unlink(video_path)
        raise HTTPException(status_code=500, detail="Scan record returned no id")

    log.info(
        "video_scan_queued",
        scan_id=scan_id,
        size_mb=round(size_mb, 1),
        room_name=room_name,
        home_name=home_name,
    )

    # ── Dispatch background pipeline ──────────────────────────────────
    background_tasks.add_task(
        _run_pipeline_bg,
        video_path=video_path,
        scan_id=scan_id,
        user_id=user_id,
        home_name=home_name,
        room_name=room_name,
        user_notes=user_notes,
        supabase=supabase,
    )

    return VideoScanResponse(
        scan_id=scan_id,
        message=(
            f"Video ({size_mb:.1f} MB) queued for processing. "
            f"Estimated time: {_estimate_seconds(size_mb):.0f}s."
        ),
        poll_url=f"/v2/scan/{scan_id}/status",
    )


# ── GET /v2/scan/{scan_id}/status ─────────────────────────────────────────

@router.get("/scan/{scan_id}/status", response_model=ScanStatusResponse)
def get_scan_status(scan_id: str, user_id: CurrentUser, supabase: SupabaseDep):
    """
    Poll the processing status of a video (or image) scan.

    Returns the scan record and, when status == "completed", the full item list.
    """
    try:
        scan_res = (
            supabase.table("scans")
            .select("*")
            .eq("id", scan_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not scan_res.data:
        raise HTTPException(status_code=404, detail="Scan not found")

    scan = scan_res.data[0]
    items: list[dict] = []

    if scan.get("status") == "completed":
        try:
            item_res = (
                supabase.table("items")
                .select("*")
                .eq("scan_id", scan_id)
                .eq("user_id", user_id)
                .execute()
            )
            items = item_res.data or []
        except Exception as e:
            log.warning("status_items_fetch_failed", scan_id=scan_id, error=str(e))

    return ScanStatusResponse(scan=scan, items=items)


# ── Background task wrapper ────────────────────────────────────────────────

async def _run_pipeline_bg(
    video_path: str,
    scan_id: str,
    user_id: str,
    home_name: str,
    room_name: str,
    user_notes: Optional[str],
    supabase,
) -> None:
    """
    Thin wrapper around run_video_pipeline for BackgroundTasks.
    Guarantees temp video is removed even if pipeline crashes.
    """
    try:
        await run_video_pipeline(
            video_path=video_path,
            scan_id=scan_id,
            user_id=user_id,
            home_name=home_name,
            room_name=room_name,
            supabase=supabase,
            user_notes=user_notes,
        )
    except Exception as e:
        log.error("pipeline_bg_failed", scan_id=scan_id, error=str(e))
    finally:
        # pipeline.py removes the temp file on completion/failure,
        # but we guard here too in case pipeline raised before that step.
        if os.path.exists(video_path):
            os.remove(video_path)


# ── Helpers ────────────────────────────────────────────────────────────────

def _estimate_seconds(size_mb: float) -> float:
    """Rough ETA: ~2s per MB as a conservative estimate for classification."""
    return max(30.0, size_mb * 2.0)
