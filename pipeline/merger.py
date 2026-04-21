"""
pipeline/merger.py — Cross-Frame Item Deduplication & Merging

The same physical item can appear in multiple frames from different angles.
This module:
1. Assigns a canonical key to each ItemEstimate (brand+model → brand+name → name)
2. Keeps the highest-confidence instance when duplicates are found
3. Returns items sorted by insurance value descending (highest-value first)

Key strategy (in priority order):
    "{category}:{brand}:{model}"  — exact product ID (best)
    "{category}:{brand}:{name}"   — brand + common-name
    "{category}:{name}"           — name only (broadest)

A 0.70-similarity fuzzy match is applied on the name token when only
the name key is available, using a simple token-overlap ratio.
"""
from __future__ import annotations

import re
import structlog
from schemas import ItemEstimate

log = structlog.get_logger("holos.pipeline.merger")

# Minimum token-overlap ratio to merge same-category, no-brand items
NAME_OVERLAP_THRESHOLD = 0.70


def merge_items(
    frame_results: list[tuple[str, list[ItemEstimate]]],
) -> list[ItemEstimate]:
    """
    Deduplicate and merge items detected across multiple frames.

    For each unique canonical key, keeps the ItemEstimate with the highest
    identification_confidence. Items that share a canonical key are merged —
    the flags lists are unioned and the winner's other fields are preserved.

    Args:
        frame_results: Output of classify_frames_parallel —
                       list of (frame_path, items) tuples.

    Returns:
        Deduplicated list of ItemEstimate, sorted by insurance value desc.
    """
    # First pass: build exact-key → best-item map
    best: dict[str, ItemEstimate] = {}
    all_items = [item for _, items in frame_results for item in items]

    for item in all_items:
        key = _canonical_key(item)
        if key not in best:
            best[key] = item
        elif item.identification_confidence > best[key].identification_confidence:
            # Keep better-confidence version, union flags
            merged_flags = list(set(best[key].flags) | set(item.flags))
            best[key] = item.model_copy(update={"flags": merged_flags})

    # Second pass: fuzzy-merge name-only keys (no brand/model known)
    merged = _fuzzy_merge_names(best)

    result = sorted(merged.values(), key=lambda x: x.insurance_midpoint_cents, reverse=True)
    log.info(
        "merge_complete",
        raw_items=len(all_items),
        merged_items=len(result),
    )
    return result


def _canonical_key(item: ItemEstimate) -> str:
    """Generate a stable dedup key for an item."""
    brand = _norm(item.brand or "")
    model = _norm(item.model or "")
    name  = _norm(item.item_name)
    cat   = item.category.value

    if brand and model:
        return f"{cat}:{brand}:{model}"
    if brand:
        return f"{cat}:{brand}:{name}"
    return f"{cat}:{name}"


def _norm(text: str) -> str:
    """Normalise a string for keying: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _token_overlap(a: str, b: str) -> float:
    """Jaccard token overlap ratio between two strings."""
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _fuzzy_merge_names(
    best: dict[str, ItemEstimate],
) -> dict[str, ItemEstimate]:
    """
    Merge name-only keys (those without brand or model) that are highly similar.
    e.g. "furniture:samsung 65 inch tv" and "furniture:samsung 65 tv" → same item.
    """
    name_only_keys = [k for k in best if k.count(":") == 1]  # cat:name only
    skip: set[str] = set()
    result = dict(best)

    for i, key_a in enumerate(name_only_keys):
        if key_a in skip:
            continue
        item_a = best[key_a]
        cat_a = key_a.split(":")[0]
        name_a = _norm(item_a.item_name)

        for key_b in name_only_keys[i + 1:]:
            if key_b in skip:
                continue
            item_b = best[key_b]
            cat_b = key_b.split(":")[0]

            if cat_a != cat_b:
                continue

            overlap = _token_overlap(name_a, _norm(item_b.item_name))
            if overlap >= NAME_OVERLAP_THRESHOLD:
                # Merge into the higher-confidence item
                if item_a.identification_confidence >= item_b.identification_confidence:
                    flags = list(set(item_a.flags) | set(item_b.flags))
                    result[key_a] = item_a.model_copy(update={"flags": flags})
                    result.pop(key_b, None)
                else:
                    flags = list(set(item_a.flags) | set(item_b.flags))
                    result[key_b] = item_b.model_copy(update={"flags": flags})
                    result.pop(key_a, None)
                skip.add(key_b if item_a.identification_confidence >= item_b.identification_confidence else key_a)

    return result
