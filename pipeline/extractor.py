"""
Frame extractor — Agent 6: Vision Edge.

Extracts frames from a video at a configurable sample rate and drops
near-duplicate frames in-line using a Pillow-based perceptual hash.
No extra dependencies beyond opencv-python-headless and Pillow.
"""
import os
import uuid
from dataclasses import dataclass, field
from typing import List

from observability import get_logger

log = get_logger("pipeline.extractor", agent_id="6")

DEFAULT_SAMPLE_FPS = 1.0        # frames to keep per second of video
DEFAULT_HASH_THRESHOLD = 8      # max Hamming distance to be considered duplicate (0–64)
DEFAULT_MAX_FRAMES = 30         # hard cap to prevent runaway API costs


@dataclass
class ExtractedFrame:
    index: int              # sequential index of kept frames (0-based)
    timestamp_sec: float
    path: str


# ── Perceptual hash (Pillow only — no imagehash dep) ─────────────────────────

def _phash(path: str, hash_size: int = 8) -> int:
    """
    Compute a simple perceptual hash of an image.
    Resize to hash_size×hash_size grayscale, threshold at mean pixel value.
    Returns an integer bitmask (hash_size² bits).
    """
    from PIL import Image
    img = Image.open(path).convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    return sum(1 << i for i, p in enumerate(pixels) if p > avg)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ── Extractor ─────────────────────────────────────────────────────────────────

def extract_frames(
    video_path: str,
    output_dir: str,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    hash_threshold: int = DEFAULT_HASH_THRESHOLD,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> tuple[List[ExtractedFrame], int]:
    """
    Extract and deduplicate frames from *video_path* into *output_dir*.

    Returns (kept_frames, duplicates_skipped).

    Strategy:
    - Seek to the next sample position (every 1/sample_fps seconds).
    - Compute pHash of the candidate frame.
    - If Hamming distance to the last kept frame's hash is ≤ hash_threshold, skip it.
    - Otherwise write it to disk and keep it.
    - Stop once max_frames unique frames have been collected.
    """
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / video_fps

    frame_interval = max(1, int(round(video_fps / sample_fps)))
    log.info(
        "extractor_start",
        video=os.path.basename(video_path),
        video_fps=round(video_fps, 2),
        duration_sec=round(duration_sec, 1),
        frame_interval=frame_interval,
        max_frames=max_frames,
    )

    os.makedirs(output_dir, exist_ok=True)

    kept: List[ExtractedFrame] = []
    duplicates_skipped = 0
    last_hash: int | None = None
    frame_number = 0

    while len(kept) < max_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_sec = frame_number / video_fps

        # Write candidate to a temp path for hashing
        tmp_path = os.path.join(output_dir, f"_tmp_{uuid.uuid4().hex[:6]}.jpg")
        cv2.imwrite(tmp_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        try:
            h = _phash(tmp_path)
        except Exception as e:
            log.warning("phash_failed", frame=frame_number, error=str(e))
            os.remove(tmp_path)
            frame_number += frame_interval
            continue

        if last_hash is not None and _hamming(h, last_hash) <= hash_threshold:
            duplicates_skipped += 1
            os.remove(tmp_path)
            frame_number += frame_interval
            continue

        # Keep this frame — rename to final path
        final_path = os.path.join(output_dir, f"frame_{len(kept):04d}.jpg")
        os.rename(tmp_path, final_path)
        kept.append(ExtractedFrame(index=len(kept), timestamp_sec=timestamp_sec, path=final_path))
        last_hash = h
        log.debug("frame_kept", index=len(kept) - 1, timestamp=round(timestamp_sec, 2))

        frame_number += frame_interval

    cap.release()
    log.info(
        "extractor_done",
        kept=len(kept),
        duplicates_skipped=duplicates_skipped,
    )
    return kept, duplicates_skipped
