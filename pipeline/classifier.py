"""
Parallel frame classifier — Agent 6: Vision Edge.

Runs scanner.analyze_room on each extracted frame using a thread pool.
scanner.analyze_room is synchronous (blocking Gemini call), so we use
ThreadPoolExecutor rather than asyncio to avoid blocking the event loop.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

import scanner
from observability import get_logger
from pipeline.extractor import ExtractedFrame

log = get_logger("pipeline.classifier", agent_id="6")

DEFAULT_MAX_WORKERS = 3   # conservative — Gemini has per-minute token limits


@dataclass
class FrameResult:
    frame: ExtractedFrame
    items: List[dict] = field(default_factory=list)
    error: Optional[str] = None


def classify_frames_parallel(
    frames: List[ExtractedFrame],
    max_workers: int = DEFAULT_MAX_WORKERS,
    user_notes: Optional[str] = None,
) -> List[FrameResult]:
    """
    Classify all frames in parallel using a thread pool.

    Returns one FrameResult per frame, preserving input order.
    Frames that fail (API error, bad JSON) produce a FrameResult with items=[]
    and error set, so the pipeline continues rather than aborting.
    """
    results: dict[int, FrameResult] = {}

    def _classify_one(frame: ExtractedFrame) -> FrameResult:
        try:
            raw = scanner.analyze_room(frame.path, user_notes=user_notes)

            if raw in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE") or str(raw).startswith("SCAN_ERROR"):
                log.warning("frame_api_error", index=frame.index, status=raw)
                return FrameResult(frame=frame, error=raw)

            cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
            items = json.loads(cleaned)
            if not isinstance(items, list):
                items = [items]

            log.debug("frame_classified", index=frame.index, item_count=len(items))
            return FrameResult(frame=frame, items=items)

        except json.JSONDecodeError as e:
            log.warning("frame_json_error", index=frame.index, error=str(e))
            return FrameResult(frame=frame, error=f"JSONDecodeError: {e}")
        except Exception as e:
            log.error("frame_classify_failed", index=frame.index, error=str(e))
            return FrameResult(frame=frame, error=str(e))

    log.info("classifier_start", total_frames=len(frames), max_workers=max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_frame = {pool.submit(_classify_one, f): f for f in frames}
        for future in as_completed(future_to_frame):
            result = future.result()
            results[result.frame.index] = result

    # Return in original frame order
    ordered = [results[f.index] for f in frames if f.index in results]
    total_items = sum(len(r.items) for r in ordered)
    errors = sum(1 for r in ordered if r.error)
    log.info("classifier_done", frames_ok=len(ordered) - errors, frames_error=errors, total_items=total_items)
    return ordered
