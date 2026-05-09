"""
Cross-frame item merger — Agent 6: Vision Edge.

After classifying N frames, the same physical item (e.g., a sofa) appears in
multiple frames. This module deduplicates across frames using token-overlap
matching — the same algorithm used in eval/run_eval.py — and keeps the
highest-confidence detection for each unique item.
"""
from typing import List

from observability import get_logger
from pipeline.classifier import FrameResult

log = get_logger("pipeline.merger", agent_id="6")

MERGE_OVERLAP_THRESHOLD = 0.5   # token overlap ratio to consider two items the same


def _tokenize(name: str) -> set[str]:
    """Split item name into lowercase tokens, stripping punctuation."""
    import re
    return set(re.sub(r"[^a-z0-9\s]", "", name.lower()).split())


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _confidence(item: dict) -> int:
    raw = item.get("confidence_score", 0)
    if isinstance(raw, str):
        try:
            return int(str(raw).replace("%", "").strip())
        except (ValueError, TypeError):
            return 0
    return int(raw) if raw else 0


def merge_items(frame_results: List[FrameResult]) -> tuple[List[dict], int]:
    """
    Merge items across all frame results.

    For each item seen across frames:
    - If its name overlaps (≥ MERGE_OVERLAP_THRESHOLD) with an already-merged item,
      replace the merged entry only if this detection has higher confidence.
    - Otherwise add it as a new unique item.

    Returns (merged_items, total_raw_items_before_merge).
    """
    merged: List[dict] = []
    total_raw = 0

    for result in frame_results:
        for item in result.items:
            total_raw += 1
            name = item.get("name", "")
            conf = _confidence(item)

            # Find an existing merged entry that matches this item
            matched_idx = None
            for i, existing in enumerate(merged):
                item_main_cat = item.get("category", "").split(" > ")[0].strip().lower()
                existing_main_cat = existing.get("category", "").split(" > ")[0].strip().lower()
                if item_main_cat and existing_main_cat and item_main_cat != existing_main_cat:
                    continue
                if _overlap(name, existing.get("name", "")) >= MERGE_OVERLAP_THRESHOLD:
                    matched_idx = i
                    break

            if matched_idx is None:
                # New unique item — add it, tagging it with its source frame
                item["_source_frame"] = result.frame.index
                item["_source_timestamp"] = result.frame.timestamp_sec
                merged.append(item)
            else:
                existing_conf = _confidence(merged[matched_idx])
                if conf > existing_conf:
                    # Better detection found — replace
                    item["_source_frame"] = result.frame.index
                    item["_source_timestamp"] = result.frame.timestamp_sec
                    merged[matched_idx] = item
                    log.debug(
                        "item_upgraded",
                        name=name,
                        old_conf=existing_conf,
                        new_conf=conf,
                        frame=result.frame.index,
                    )

    log.info("merger_done", unique_items=len(merged), raw_items=total_raw)
    return merged, total_raw
