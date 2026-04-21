"""
pipeline/extractor.py — Video Frame Extraction

Uses PyAV (libav bindings, no system ffmpeg required) to:
1. Iterate video frames at a configurable interval
2. Detect scene changes by comparing grayscale histograms between frames
3. Write scene-change frames as JPEG to a temp directory

Algorithm:
    - Sample 1 frame per SAMPLE_INTERVAL_S seconds
    - Compute mean absolute difference of 64×36 grayscale thumbnails
    - If diff > scene_threshold (0–1): keep this frame
    - Cap output at max_frames to bound AI cost
    - If scene detection yields < min_frames, fall back to 1fps uniform sampling
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog
from PIL import Image

log = structlog.get_logger("holos.pipeline.extractor")

# av is imported lazily inside functions so Application Control blocking the DLL
# does not prevent the FastAPI server from starting.
# The functions will raise RuntimeError with a helpful message if av is unavailable.

SAMPLE_INTERVAL_S  = 0.75   # check scene every N seconds
SCENE_THRESHOLD    = 0.28   # abs mean diff / 255, 0=identical 1=total change
COMPARE_SIZE       = (64, 36)  # tiny thumbnail for fast comparison
OUTPUT_SIZE        = (1280, 720)  # max output frame resolution
OUTPUT_QUALITY     = 82      # JPEG quality for saved frames


def extract_scene_frames(
    video_path: str,
    output_dir: str,
    scene_threshold: float = SCENE_THRESHOLD,
    min_frames: int = 5,
    max_frames: int = 60,
    sample_interval_s: float = SAMPLE_INTERVAL_S,
) -> list[str]:
    """
    Extract significant scene-change frames from a video file.

    Args:
        video_path:       Path to the video file (mp4, mov, avi, webm, m4v).
        output_dir:       Directory where JPEG frames will be written.
        scene_threshold:  Normalised pixel difference threshold (0–1).
        min_frames:       Fall back to uniform sampling if scene detection
                          yields fewer than this many frames.
        max_frames:       Hard cap on frames returned (AI cost guard).
        sample_interval_s: Seconds between frames examined for scene change.

    Returns:
        Sorted list of absolute JPEG frame paths.

    Raises:
        FileNotFoundError: if video_path does not exist.
        RuntimeError:      if PyAV cannot decode the file.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    os.makedirs(output_dir, exist_ok=True)

    frames = _extract_scene(video_path, output_dir, scene_threshold, max_frames, sample_interval_s)

    # Fallback: too few scene changes → uniform 1fps sampling
    if len(frames) < min_frames:
        log.info(
            "scene_detect_sparse_fallback",
            scene_frames=len(frames),
            min_frames=min_frames,
        )
        # Clear existing output and re-extract uniformly
        for p in frames:
            Path(p).unlink(missing_ok=True)
        frames = _extract_uniform(video_path, output_dir, fps=1.0, max_frames=max_frames)

    log.info("frames_extracted", count=len(frames), path=video_path)
    return frames


def _extract_scene(
    video_path: str,
    output_dir: str,
    threshold: float,
    max_frames: int,
    interval_s: float,
) -> list[str]:
    """Scene-change extraction pass using PyAV (lazily imported)."""
    try:
        import av
        import numpy as np
    except (ImportError, OSError) as e:
        raise RuntimeError(
            f"PyAV not available: {e}\n"
            "Install with: pip install av\n"
            "On Windows, the DLL may be blocked by Application Control policy."
        ) from e

    frames: list[str] = []
    prev_arr = None
    last_sample_pts: float = -999.0  # force first frame

    try:
        container = av.open(video_path)
    except Exception as e:
        raise RuntimeError(f"PyAV cannot open video: {e}") from e

    try:
        video_stream = container.streams.video[0]
        time_base = float(video_stream.time_base) if video_stream.time_base else 1 / 90000

        for packet in container.demux(video_stream):
            for frame in packet.decode():
                pts_s = (frame.pts or 0) * time_base
                if pts_s - last_sample_pts < interval_s:
                    continue
                last_sample_pts = pts_s

                pil_img = frame.to_image()
                thumb = pil_img.convert("L").resize(COMPARE_SIZE, Image.BILINEAR)
                arr = np.asarray(thumb, dtype=np.float32)

                if prev_arr is None:
                    is_scene = True
                else:
                    diff = float(np.mean(np.abs(arr - prev_arr))) / 255.0
                    is_scene = diff > threshold

                prev_arr = arr

                if is_scene:
                    path = _save_frame(pil_img, output_dir, len(frames))
                    frames.append(path)

                if len(frames) >= max_frames:
                    break

            if len(frames) >= max_frames:
                break
    finally:
        container.close()

    return sorted(frames)


def _extract_uniform(
    video_path: str,
    output_dir: str,
    fps: float,
    max_frames: int,
) -> list[str]:
    """Uniform fps extraction fallback (lazily imports av)."""
    try:
        import av
    except (ImportError, OSError) as e:
        raise RuntimeError(f"PyAV not available: {e}") from e

    frames: list[str] = []
    last_s: float = -999.0

    container = av.open(video_path)
    try:
        video_stream = container.streams.video[0]
        time_base = float(video_stream.time_base) if video_stream.time_base else 1 / 90000
        interval = 1.0 / fps

        for packet in container.demux(video_stream):
            for frame in packet.decode():
                pts_s = (frame.pts or 0) * time_base
                if pts_s - last_s < interval:
                    continue
                last_s = pts_s
                pil_img = frame.to_image()
                path = _save_frame(pil_img, output_dir, len(frames))
                frames.append(path)
                if len(frames) >= max_frames:
                    break
            if len(frames) >= max_frames:
                break
    finally:
        container.close()

    return sorted(frames)


def _save_frame(img: Image.Image, output_dir: str, idx: int) -> str:
    """Resize and save a single frame as JPEG. Returns the path."""
    img.thumbnail(OUTPUT_SIZE, Image.LANCZOS)
    path = os.path.join(output_dir, f"frame_{idx:04d}.jpg")
    img.save(path, "JPEG", quality=OUTPUT_QUALITY, optimize=True)
    return path
