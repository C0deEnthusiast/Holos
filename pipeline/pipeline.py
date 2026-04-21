"""
pipeline/pipeline.py — Video Pipeline Orchestrator

Full pipeline sequence:
  1. Update scan → "extracting_frames"
  2. extract_scene_frames()    → list[frame_path]
  3. Update scan → "deduplicating"
  4. dedup_frames()            → list[unique_frame_path]
  5. Update scan → "classifying"
  6. classify_frames_parallel()→ list[(frame_path, items)]
  7. Update scan → "merging"
  8. merge_items()             → list[ItemEstimate]   (deduplicated)
  9. Update scan → "saving"
 10. auto_save()               → int (items saved to DB)
 11. Update scan → "completed" + metrics

Real-time updates: every stage writes to supabase.scans so the frontend
can subscribe via Supabase Realtime or poll GET /v2/scan/{id}/status.

§8.7 cost guard: max 60 frames × $0.004/frame ≈ $0.24 per scan.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from typing import Callable, Optional

import structlog

import scanner as sc
from pipeline.extractor import extract_scene_frames
from pipeline.deduplicator import dedup_frames
from pipeline.classifier import classify_frames_parallel
from pipeline.merger import merge_items
from schemas import ItemEstimate

log = structlog.get_logger("holos.pipeline")

# ── Tuning constants ─────────────────────────────────────────────────────
SCENE_THRESHOLD         = 0.28
MAX_HASH_DISTANCE       = 8
MAX_CONCURRENT_CLASSIFY = 5
AUTO_SAVE_THRESHOLD     = 0.75  # same as image scan route
MAX_FRAMES              = 60    # §8.7 cost guard

ProgressCallback = Callable[[str, float, str], None]  # (step, pct, message)


async def run_video_pipeline(
    video_path: str,
    scan_id: str,
    user_id: str,
    home_name: str,
    room_name: str,
    supabase,
    user_notes: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> list[ItemEstimate]:
    """
    Execute the full video walkthrough pipeline.

    Args:
        video_path:   Absolute path to the uploaded video file.
        scan_id:      Supabase scan record id (created before calling).
        user_id:      Authenticated user id for DB writes.
        home_name:    Property name (e.g. "123 Oak St").
        room_name:    Room label (e.g. "Living Room").
        supabase:     Supabase Python client (sync, wrapped with to_thread).
        user_notes:   Optional free-text hints for the AI prompt.
        on_progress:  Optional async callback(step, pct_0_to_1, message).

    Returns:
        Deduplicated list of ItemEstimate objects after auto-save.

    Raises:
        RuntimeError: propagated from extractor if video is unreadable.
    """
    start = time.perf_counter()
    tmp_dir = tempfile.mkdtemp(prefix="holos_frames_")
    log.info("pipeline_start", scan_id=scan_id, video=video_path)

    try:
        # ── 1. Extract frames ────────────────────────────────────────────
        await _update_scan(supabase, scan_id, {"status": "extracting_frames"})
        await _progress(on_progress, "extract", 0.0, "Extracting scene keyframes…")

        frame_paths = await asyncio.to_thread(
            extract_scene_frames,
            video_path,
            tmp_dir,
            scene_threshold=SCENE_THRESHOLD,
            max_frames=MAX_FRAMES,
        )
        await _update_scan(supabase, scan_id, {"frame_count": len(frame_paths)})
        await _progress(on_progress, "extract", 1.0, f"{len(frame_paths)} frames extracted")
        log.info("stage_extract_done", frames=len(frame_paths), scan_id=scan_id)

        # ── 2. pHash dedup ───────────────────────────────────────────────
        await _update_scan(supabase, scan_id, {"status": "deduplicating"})
        await _progress(on_progress, "dedup", 0.0, "Removing duplicate frames…")

        unique_frames = await asyncio.to_thread(
            dedup_frames, frame_paths, MAX_HASH_DISTANCE
        )
        await _progress(on_progress, "dedup", 1.0, f"{len(unique_frames)} unique frames")
        log.info(
            "stage_dedup_done",
            before=len(frame_paths),
            after=len(unique_frames),
            scan_id=scan_id,
        )

        # ── 3. Parallel classify ─────────────────────────────────────────
        await _update_scan(supabase, scan_id, {
            "status": "classifying",
            "frame_count": len(unique_frames),
        })
        await _progress(on_progress, "classify", 0.0,
                        f"AI analysing {len(unique_frames)} frames…")

        frame_results = await classify_frames_parallel(
            unique_frames,
            user_id=user_id,
            scan_id=scan_id,
            user_notes=user_notes,
            max_concurrent=MAX_CONCURRENT_CLASSIFY,
        )

        raw_count = sum(len(items) for _, items in frame_results)
        await _update_scan(supabase, scan_id, {"items_detected": raw_count})
        await _progress(on_progress, "classify", 1.0, f"{raw_count} raw item detections")
        log.info("stage_classify_done", raw_items=raw_count, scan_id=scan_id)

        # ── 4. Merge ─────────────────────────────────────────────────────
        await _update_scan(supabase, scan_id, {"status": "merging"})
        await _progress(on_progress, "merge", 0.0, "Merging duplicate detections…")

        merged = merge_items(frame_results)
        await _update_scan(supabase, scan_id, {"items_detected": len(merged)})
        await _progress(on_progress, "merge", 1.0, f"{len(merged)} unique items identified")
        log.info("stage_merge_done", merged=len(merged), scan_id=scan_id)

        # ── 5. Auto-save ─────────────────────────────────────────────────
        await _update_scan(supabase, scan_id, {"status": "saving"})
        await _progress(on_progress, "save", 0.0, "Saving to inventory…")

        saved = await _auto_save(merged, user_id, scan_id, home_name, room_name, supabase)
        await _progress(on_progress, "save", 1.0, f"{saved} items saved to inventory")

        # ── 6. Complete ──────────────────────────────────────────────────
        elapsed = round(time.perf_counter() - start, 1)
        await _update_scan(supabase, scan_id, {
            "status":             "completed",
            "items_detected":     len(merged),
            "items_saved":        saved,
            "processing_seconds": elapsed,
        })
        await _progress(on_progress, "done", 1.0,
                        f"Done in {elapsed}s — {len(merged)} items, {saved} saved")
        log.info(
            "pipeline_complete",
            scan_id=scan_id,
            items=len(merged),
            saved=saved,
            elapsed_s=elapsed,
        )
        return merged

    except Exception as exc:
        log.error("pipeline_failed", scan_id=scan_id, error=str(exc))
        await _update_scan(supabase, scan_id, {
            "status": "failed",
            "error":  str(exc)[:500],
        })
        raise

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if os.path.exists(video_path):
            os.remove(video_path)


# ── Helpers ───────────────────────────────────────────────────────────────

async def _update_scan(supabase, scan_id: str, fields: dict) -> None:
    """Write fields to the scan record, non-crashing."""
    try:
        await asyncio.to_thread(
            lambda: supabase.table("scans").update(fields).eq("id", scan_id).execute()
        )
    except Exception as e:
        log.warning("scan_update_failed", scan_id=scan_id, fields=list(fields), error=str(e))


async def _auto_save(
    items: list[ItemEstimate],
    user_id: str,
    scan_id: str,
    home_name: str,
    room_name: str,
    supabase,
) -> int:
    """
    Insert high-confidence items into the items table.
    Returns count of successfully saved items.
    """
    saved = 0
    for item in items:
        if item.identification_confidence < AUTO_SAVE_THRESHOLD:
            continue
        try:
            # to_db_dict() uses "room" key — we need "room_name" for the DB
            payload = {k: v for k, v in item.to_db_dict().items() if k != "room"}
            payload.update({
                "user_id":        user_id,
                "scan_id":        scan_id,
                "home_name":      home_name,
                "room_name":      room_name,
                "is_archived":    False,
                "user_confirmed": False,
                "ai_model_id":    sc.VISION_MODEL,
            })
            await asyncio.to_thread(
                lambda p=payload: supabase.table("items").insert(p).execute()
            )
            saved += 1
        except Exception as e:
            log.warning("auto_save_item_failed", name=item.item_name, error=str(e))

    return saved


async def _progress(
    callback: Optional[ProgressCallback],
    step: str,
    pct: float,
    message: str,
) -> None:
    if callback is None:
        return
    try:
        result = callback(step, pct, message)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass
