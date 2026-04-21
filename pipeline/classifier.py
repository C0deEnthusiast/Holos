"""
pipeline/classifier.py — Async Parallel Frame Classification

Wraps scanner.analyze_room() (synchronous) with asyncio.to_thread so that
up to MAX_CONCURRENT frames are classified in parallel via a thread-pool.

Uses asyncio.Semaphore to enforce the concurrency cap — this prevents
Gemini quota bursts while still achieving meaningful parallelism.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

import scanner
from schemas import ItemEstimate

log = structlog.get_logger("holos.pipeline.classifier")

# Max simultaneous Gemini calls — §8.7 quota headroom
DEFAULT_MAX_CONCURRENT = 5


async def classify_frame(
    frame_path: str,
    semaphore: asyncio.Semaphore,
    user_id: Optional[str] = None,
    scan_id: Optional[str] = None,
    user_notes: Optional[str] = None,
) -> tuple[str, list[ItemEstimate]]:
    """
    Classify a single image frame within a concurrency semaphore.

    Returns (frame_path, items) where items is an empty list on any error.
    Errors are logged but never raised — a single bad frame must not abort
    the whole batch.
    """
    async with semaphore:
        try:
            # scanner.analyze_room is synchronous → run in thread
            items: list[ItemEstimate] = await asyncio.to_thread(
                scanner.analyze_room,
                frame_path,
                user_notes=user_notes,
                user_id=user_id,
                scan_id=scan_id,
            )
            log.info(
                "frame_classified",
                path=frame_path,
                items_found=len(items),
                model=scanner.VISION_MODEL,
            )
            return frame_path, items
        except Exception as e:
            log.warning("frame_classify_failed", path=frame_path, error=str(e))
            return frame_path, []


async def classify_frames_parallel(
    frame_paths: list[str],
    user_id: Optional[str] = None,
    scan_id: Optional[str] = None,
    user_notes: Optional[str] = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
) -> list[tuple[str, list[ItemEstimate]]]:
    """
    Classify all frames in parallel, bounded by max_concurrent.

    Args:
        frame_paths:    List of frame file paths to classify.
        user_id:        Passed to scanner for cost/audit logging.
        scan_id:        Passed to scanner for correlation.
        user_notes:     Optional room context (passed verbatim to AI prompt).
        max_concurrent: Max simultaneous Gemini API calls.

    Returns:
        List of (frame_path, items) tuples in the same order as frame_paths.
        Frames that fail are included with an empty items list.
    """
    if not frame_paths:
        return []

    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [
        classify_frame(path, semaphore, user_id, scan_id, user_notes)
        for path in frame_paths
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)
    log.info(
        "batch_classified",
        frames=len(frame_paths),
        total_items=sum(len(items) for _, items in results),
        concurrency=max_concurrent,
    )
    return list(results)
