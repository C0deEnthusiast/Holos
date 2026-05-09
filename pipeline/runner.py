"""
Pipeline runner — Agent 6: Vision Edge.

Orchestrates the full video-to-inventory pipeline:
  1. extract_frames  — sample + deduplicate frames from video
  2. classify_frames — parallel Gemini identification per frame
  3. merge_items     — cross-frame deduplication → single item list

Entry point: run_pipeline(video_path, ...)
"""
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from observability import get_logger
from pipeline.extractor import extract_frames, DEFAULT_SAMPLE_FPS, DEFAULT_MAX_FRAMES
from pipeline.classifier import classify_frames_parallel, DEFAULT_MAX_WORKERS
from pipeline.merger import merge_items

log = get_logger("pipeline.runner", agent_id="6")


@dataclass
class PipelineResult:
    items: List[dict] = field(default_factory=list)
    frames_extracted: int = 0
    frames_processed: int = 0       # frames that got a successful AI response
    duplicates_skipped: int = 0
    items_before_merge: int = 0
    processing_time_sec: float = 0.0
    errors: List[str] = field(default_factory=list)
    frame_dir: Optional[str] = None        # set when keep_frames=True
    frame_index: Dict[int, str] = field(default_factory=dict)  # index → file path


def run_pipeline(
    video_path: str,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    max_frames: int = DEFAULT_MAX_FRAMES,
    max_workers: int = DEFAULT_MAX_WORKERS,
    user_notes: Optional[str] = None,
    keep_frames: bool = False,      # set True to retain extracted frames for debugging
) -> PipelineResult:
    """
    Run the full video pipeline and return a PipelineResult.

    Args:
        video_path:   Path to the input video file.
        sample_fps:   Frames per second to sample (default 1.0).
        max_frames:   Hard cap on kept frames (default 30).
        max_workers:  Parallel classifier threads (default 3).
        user_notes:   Optional context passed to Gemini (room type, style hints).
        keep_frames:  If True, extracted frames are not deleted on completion.
    """
    t_start = time.time()
    result = PipelineResult()

    tmp_dir = tempfile.mkdtemp(prefix="holos_pipeline_")
    log.info("pipeline_start", video=os.path.basename(video_path), tmp_dir=tmp_dir)

    try:
        # ── Step 1: Extract & deduplicate frames ──────────────────────────────
        frames, dupes = extract_frames(
            video_path=video_path,
            output_dir=tmp_dir,
            sample_fps=sample_fps,
            max_frames=max_frames,
        )
        result.frames_extracted = len(frames)
        result.duplicates_skipped = dupes

        if not frames:
            log.warning("pipeline_no_frames", video=os.path.basename(video_path))
            return result

        # ── Step 2: Parallel classification ───────────────────────────────────
        frame_results = classify_frames_parallel(
            frames=frames,
            max_workers=max_workers,
            user_notes=user_notes,
        )
        result.frames_processed = sum(1 for r in frame_results if not r.error)
        result.errors = [r.error for r in frame_results if r.error]

        # ── Step 3: Cross-frame merge ─────────────────────────────────────────
        merged, raw_count = merge_items(frame_results)
        result.items = merged
        result.items_before_merge = raw_count

        # Build index → path map so callers can look up frames by index
        result.frame_index = {f.index: f.path for f in frames}
        if keep_frames:
            result.frame_dir = tmp_dir

    finally:
        if not keep_frames:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        result.processing_time_sec = round(time.time() - t_start, 2)

    log.info(
        "pipeline_done",
        frames_extracted=result.frames_extracted,
        frames_processed=result.frames_processed,
        duplicates_skipped=result.duplicates_skipped,
        unique_items=len(result.items),
        raw_items=result.items_before_merge,
        processing_sec=result.processing_time_sec,
    )
    return result
