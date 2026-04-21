"""
pipeline/deduplicator.py — pHash Frame Deduplication

Uses perceptual hashing (pHash via imagehash) to identify near-duplicate frames.
Two frames are considered duplicates when their Hamming distance < max_hash_distance.

This prevents the same item being classified N times from slightly different angles,
capping AI cost and avoiding duplicate items in the final inventory.

Hamming distance reference:
    0  = identical images
    1–7 = very similar (same scene, tiny motion)
    8+  = meaningfully different content
"""
from __future__ import annotations

import structlog
import imagehash
from PIL import Image

log = structlog.get_logger("holos.pipeline.deduplicator")

# pHash bit-length = 64. Distance < 8 is same-scene for our sensor.
DEFAULT_MAX_HASH_DISTANCE = 8


def dedup_frames(
    frame_paths: list[str],
    max_hash_distance: int = DEFAULT_MAX_HASH_DISTANCE,
) -> list[str]:
    """
    Remove near-duplicate frames using perceptual hashing.

    Iterates frames in presentation order. The first frame is always kept.
    Each subsequent frame is kept only if its pHash differs from every
    previously-kept frame by more than max_hash_distance.

    Args:
        frame_paths:       Ordered list of frame file paths.
        max_hash_distance: Hamming distance threshold below which frames
                           are considered duplicates (0 = exact match only).

    Returns:
        Subset of frame_paths (preserving original order) after deduplication.
    """
    seen_hashes: list[imagehash.ImageHash] = []
    unique: list[str] = []
    skipped = 0

    for path in frame_paths:
        try:
            img = Image.open(path)
            h = imagehash.phash(img)
        except Exception as e:
            log.warning("phash_failed", path=path, error=str(e))
            continue  # skip corrupt frames silently

        # Compare against every kept hash
        is_dupe = any(
            (h - seen) < max_hash_distance
            for seen in seen_hashes
        )

        if is_dupe:
            skipped += 1
        else:
            seen_hashes.append(h)
            unique.append(path)

    log.info(
        "dedup_complete",
        input=len(frame_paths),
        output=len(unique),
        skipped=skipped,
        threshold=max_hash_distance,
    )
    return unique
