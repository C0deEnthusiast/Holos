"""
Video scan endpoint — Agent 6: Vision Edge.

POST /api/v2/scan/video

Accepts a walkthrough video, runs the full pipeline (extract → classify →
merge), crops a thumbnail from the best source frame for each item, uploads
to Supabase Storage, and returns a unified item list with the same shape as
POST /api/v2/scan.
"""
import asyncio
import json
import os
import re
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from config import Config
from observability import get_logger, init_scan_cost, finalize_scan_cost
from pipeline.runner import run_pipeline
from backend_v2.dependencies import get_current_user_id, get_supabase
from backend_v2.routers.scan import _upload_to_supabase, _crop_thumbnail, _supabase_insert

log = get_logger("backend_v2.video", agent_id="6")

router = APIRouter(prefix="/api/v2", tags=["video"])

ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "webm", "mkv"}
MAX_VIDEO_SIZE_MB = 200


@router.post("/scan/video")
async def scan_video(
    video: UploadFile = File(...),
    home_name: str = Form(default="My Home"),
    room_name: str = Form(default="General Room"),
    user_notes: str = Form(default=""),
    sample_fps: float = Form(default=1.0, ge=0.1, le=5.0),
    max_frames: int = Form(default=30, ge=1, le=60),
    max_workers: int = Form(default=3, ge=1, le=6),
    user_id: Optional[str] = Depends(get_current_user_id),
):
    filename = video.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid video type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    contents = await video.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Video too large ({size_mb:.1f} MB). Max: {MAX_VIDEO_SIZE_MB} MB",
        )

    upload_folder = Config.UPLOAD_FOLDER
    os.makedirs(upload_folder, exist_ok=True)

    tmp_name = f"v2_video_{uuid.uuid4().hex[:8]}.{ext}"
    video_path = os.path.join(upload_folder, tmp_name)

    result = None
    try:
        def _write(path, data):
            with open(path, "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write, video_path, contents)
        del contents

        log.info(
            "video_scan_start",
            filename=filename,
            size_mb=round(size_mb, 1),
            sample_fps=sample_fps,
            max_frames=max_frames,
        )

        # Run pipeline with keep_frames=True so we can crop thumbnails afterward
        result = await asyncio.to_thread(
            run_pipeline,
            video_path,
            sample_fps,
            max_frames,
            max_workers,
            user_notes.strip() or None,
            True,   # keep_frames
        )

        # ── Thumbnails: crop from source frame, upload to Supabase ───────────
        supabase = get_supabase()
        for item in result.items:
            item["home_name"] = home_name
            item["room_name"] = room_name

            if item.get("thumbnail_url"):
                continue

            src_idx = item.get("_source_frame")
            frame_path = result.frame_index.get(src_idx) if src_idx is not None else None

            if not frame_path or not os.path.exists(frame_path):
                continue

            if supabase:
                try:
                    # Try bounding-box crop first; fall back to uploading full frame
                    rough_box = item.get("bounding_box")
                    if rough_box and Config.ENABLE_SNIPER_MODE:
                        thumb_path, refined_box = await asyncio.to_thread(
                            _crop_thumbnail,
                            frame_path,
                            item.get("name", ""),
                            rough_box,
                            upload_folder,
                        )
                        if thumb_path and os.path.exists(thumb_path):
                            storage_path = f"vthumb_{uuid.uuid4().hex[:8]}.jpg"
                            url = await asyncio.to_thread(
                                _upload_to_supabase, supabase, "scans", storage_path, thumb_path
                            )
                            item["thumbnail_url"] = url
                            item["thumbnail_source"] = "frame_crop"
                            item["bounding_box"] = refined_box
                            os.remove(thumb_path)
                            continue

                    # No crop available — upload the full frame
                    storage_path = f"vframe_{uuid.uuid4().hex[:8]}.jpg"
                    url = await asyncio.to_thread(
                        _upload_to_supabase, supabase, "scans", storage_path, frame_path
                    )
                    item["thumbnail_url"] = url
                    item["thumbnail_source"] = "frame"
                except Exception as e:
                    log.warning("video_thumb_upload_failed", item=item.get("name"), error=str(e))

        AUTO_SAVE_THRESHOLD = 75
        auto_saved = []
        needs_review = []

        init_scan_cost()

        for item in result.items:
            confidence = item.get("confidence_score", 0)
            if isinstance(confidence, str):
                try:
                    confidence = int(str(confidence).replace("%", "").strip())
                except (ValueError, TypeError):
                    confidence = 0

            if confidence >= AUTO_SAVE_THRESHOLD and user_id and supabase:
                try:
                    price_str = str(item.get("estimated_price_usd") or "0").replace("$", "").replace(",", "")
                    numbers = re.findall(r"[-+]?\d*\.?\d+", price_str)
                    price = float(numbers[0]) if numbers else 0.0

                    maintenance_note = json.dumps({
                        "home": home_name,
                        "room": room_name,
                        "make": item.get("make"),
                        "model": item.get("model"),
                        "quantity": item.get("quantity", 1),
                        "is_set": item.get("is_set", False),
                        "estimated_age_years": item.get("estimated_age_years"),
                        "condition_notes": item.get("condition_notes"),
                        "estimated_dimensions": item.get("estimated_dimensions"),
                        "bounding_box": item.get("bounding_box"),
                        "confidence_score": confidence,
                        "unit_price_usd": item.get("unit_price_usd"),
                        "resale_value_usd": item.get("resale_value_usd"),
                        "retail_replacement_usd": item.get("retail_replacement_usd"),
                        "insurance_replacement_usd": item.get("insurance_replacement_usd"),
                        "price_basis": item.get("price_basis"),
                        "identification_basis": item.get("identification_basis"),
                        "source_frame": item.get("_source_frame"),
                        "source_timestamp": item.get("_source_timestamp"),
                    })

                    to_save = {
                        "user_id": user_id,
                        "name": item.get("name"),
                        "category": item.get("category"),
                        "make": item.get("make"),
                        "model": item.get("model"),
                        "estimated_dimensions": item.get("estimated_dimensions"),
                        "suggested_replacements": item.get("suggested_replacements"),
                        "estimated_price_usd": price,
                        "condition": item.get("condition"),
                        "thumbnail_url": item.get("thumbnail_url"),
                        "is_archived": False,
                        "maintenance_note": maintenance_note,
                    }

                    try:
                        scan_payload = {
                            "user_id": user_id,
                            "status": "video_auto_saved",
                            "original_image_url": item.get("thumbnail_url"),
                            "home_name": home_name,
                            "room_name": room_name,
                        }
                        scan_res = await asyncio.to_thread(
                            _supabase_insert, supabase, "scans", scan_payload
                        )
                        if scan_res.data:
                            to_save["scan_id"] = scan_res.data[0]["id"]
                    except Exception as scan_err:
                        log.warning("video_scan_record_failed", error=str(scan_err))

                    res = await asyncio.to_thread(_supabase_insert, supabase, "items", to_save)
                    if res.data:
                        item["id"] = res.data[0]["id"]
                        item["auto_saved"] = True
                        auto_saved.append(item)
                        log.info("video_item_auto_saved", name=item.get("name"), confidence=confidence)
                    else:
                        item["auto_saved"] = False
                        needs_review.append(item)

                except Exception as save_err:
                    log.error("video_auto_save_failed", name=item.get("name"), error=str(save_err))
                    item["auto_saved"] = False
                    needs_review.append(item)
            else:
                item["auto_saved"] = False
                item["review_reason"] = f"Confidence {confidence}% (threshold: {AUTO_SAVE_THRESHOLD}%)"
                needs_review.append(item)

        total_cost = finalize_scan_cost()
        log.info(
            "video_scan_complete",
            auto_saved=len(auto_saved),
            needs_review=len(needs_review),
            total_cost_cents=total_cost,
        )

        return {
            "success": True,
            "api_version": "v2",
            "data": result.items,
            "auto_saved": auto_saved,
            "needs_review": needs_review,
            "pipeline": {
                "frames_extracted": result.frames_extracted,
                "frames_processed": result.frames_processed,
                "duplicates_skipped": result.duplicates_skipped,
                "items_before_merge": result.items_before_merge,
                "unique_items": len(result.items),
                "processing_time_sec": result.processing_time_sec,
                "errors": result.errors if result.errors else None,
            },
            "summary": {
                "total": len(result.items),
                "auto_saved_count": len(auto_saved),
                "needs_review_count": len(needs_review),
                "threshold": AUTO_SAVE_THRESHOLD,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error("video_scan_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        # Clean up kept frames now that thumbnails are uploaded
        if result is not None and result.frame_dir and os.path.exists(result.frame_dir):
            shutil.rmtree(result.frame_dir, ignore_errors=True)
