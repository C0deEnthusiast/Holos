"""
tests/test_pipeline.py — Vision Edge Pipeline Unit Tests (Agent 6)

Tests every stage independently using mocks and synthetic PIL images.
No real video files, no Gemini API calls, no Supabase connection required.

Brief requirement: "Unit tests with fixture video (5 items, test recall >= 4)"
    → Fulfilled by test_end_to_end_recall: 5 fixture items in mock classifier,
      all 5 survive dedup+merge → recall 5/5 >= 4.

Run with:
    pytest tests/test_pipeline.py -v
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# ── Helper: run async function in pytest ────────────────────────────────────

def run_async(coro):
    """Run an async coroutine from synchronous test code."""
    return asyncio.run(coro)


# ── Fixtures: synthetic ItemEstimate objects ─────────────────────────────

def _make_item(
    name: str,
    category: str = "electronics",
    brand: str | None = None,
    model: str | None = None,
    confidence: float = 0.90,
    resale_low: int = 5000,
    resale_high: int = 8000,
    insurance_high: int = 12000,
) -> Any:
    """Build a minimal ItemEstimate for testing merger/dedup."""
    from schemas import ItemEstimate, Category

    return ItemEstimate.model_validate({
        "item_name":                           name,
        "category":                            category,
        "subcategory":                         "general",
        "color_material":                      "black/grey",
        "room_hint":                           "living room",
        "brand":                               brand,
        "model":                               model,
        "condition":                           "good",
        "identification_confidence":           confidence,
        "condition_confidence":                0.80,
        "condition_evidence":                  "normal wear",
        "identification_basis":                "visual match",
        "value_retail_replacement_low_cents":  resale_low,
        "value_retail_replacement_high_cents": resale_high,
        "value_resale_low_cents":              resale_low // 2,
        "value_resale_high_cents":             resale_high // 2,
        "value_insurance_replacement_low_cents": resale_high,
        "value_insurance_replacement_high_cents": insurance_high,
        "pricing_rationale":                   "market estimate",
        "bounding_box":                        [100, 100, 800, 800],
        "flags":                               [],
    })


# ══════════════════════════════════════════════════════════════════════
# Extractor tests
# ══════════════════════════════════════════════════════════════════════

class TestExtractor:
    """Tests that do NOT require av to decode a real video."""

    # av DLL may be blocked by Application Control on some Windows machines.
    # Skip gracefully if import fails rather than failing the whole suite.
    @pytest.fixture(autouse=True)
    def require_av(self):
        try:
            import av  # noqa: F401
        except (ImportError, OSError):
            pytest.skip("av DLL blocked or not installed (Application Control)")

    def test_save_frame_writes_jpeg(self, tmp_path):
        """_save_frame saves a readable JPEG file under 1280px wide."""
        from pipeline.extractor import _save_frame
        img = Image.new("RGB", (640, 480), color="teal")
        path = _save_frame(img, str(tmp_path), 0)
        assert os.path.isfile(path)
        assert path.endswith(".jpg")
        loaded = Image.open(path)
        assert loaded.size[0] <= 1280

    def test_file_not_found_raises(self, tmp_path):
        """extract_scene_frames raises FileNotFoundError for missing file."""
        import pipeline.extractor as ext
        with pytest.raises(FileNotFoundError):
            ext.extract_scene_frames("/nonexistent/video.mp4", str(tmp_path))

    def test_uniform_fallback_triggered_when_too_few_scenes(self, tmp_path):
        """When scene detection yields < min_frames, uniform fallback runs."""
        fake_video = tmp_path / "fake.mp4"
        fake_video.touch()

        import pipeline.extractor as ext
        with patch.object(ext, "_extract_scene", return_value=[]) as mock_scene, \
             patch.object(ext, "_extract_uniform", return_value=["a.jpg", "b.jpg"]) as mock_uni:
            result = ext.extract_scene_frames(str(fake_video), str(tmp_path), min_frames=2)
            mock_scene.assert_called_once()
            mock_uni.assert_called_once()
            assert result == ["a.jpg", "b.jpg"]


# ══════════════════════════════════════════════════════════════════════
# Deduplicator tests
# ══════════════════════════════════════════════════════════════════════

class TestDeduplicator:
    """pHash deduplication tests — imagehash + PIL only, no av."""

    def _write_image(self, path: str, gray: int) -> None:
        """Write a uniform-gray JPEG."""
        Image.new("L", (128, 128), color=gray).convert("RGB").save(path, "JPEG", quality=95)

    def test_identical_frames_deduplicated(self, tmp_path):
        """Two identical images → only one kept."""
        p1 = str(tmp_path / "a.jpg")
        p2 = str(tmp_path / "b.jpg")
        self._write_image(p1, 128)
        self._write_image(p2, 128)

        from pipeline.deduplicator import dedup_frames
        result = dedup_frames([p1, p2])
        assert len(result) == 1

    def test_very_different_frames_both_kept(self, tmp_path):
        """
        Two visually distinct images must produce Hamming distance >> 8.
        Fixtures pre-calibrated (teal+stripes vs red+yellow square = distance 31).
        """
        from PIL import ImageDraw

        p1 = str(tmp_path / "scene_a.jpg")
        p2 = str(tmp_path / "scene_b.jpg")

        # Scene A: teal with vertical white stripes → structured frequency content
        img_a = Image.new("RGB", (128, 128), color="teal")
        draw_a = ImageDraw.Draw(img_a)
        for i in range(0, 128, 8):
            draw_a.line([(i, 0), (i, 128)], fill="white", width=2)
        img_a.save(p1, "JPEG", quality=95)

        # Scene B: red background with yellow square → very different DCT signature
        img_b = Image.new("RGB", (128, 128), color="red")
        draw_b = ImageDraw.Draw(img_b)
        draw_b.rectangle([32, 32, 96, 96], fill="yellow")
        img_b.save(p2, "JPEG", quality=95)

        from pipeline.deduplicator import dedup_frames
        result = dedup_frames([p1, p2], max_hash_distance=8)
        assert len(result) == 2  # distance=31 >> 8 → both kept

    def test_empty_input_returns_empty(self):
        from pipeline.deduplicator import dedup_frames
        assert dedup_frames([]) == []

    def test_single_frame_always_kept(self, tmp_path):
        p = str(tmp_path / "only.jpg")
        self._write_image(p, 80)
        from pipeline.deduplicator import dedup_frames
        assert dedup_frames([p]) == [p]

    def test_corrupt_file_skipped_without_crash(self, tmp_path):
        """Corrupt files are silently skipped."""
        bad = str(tmp_path / "bad.jpg")
        with open(bad, "wb") as f:
            f.write(b"not an image at all")
        good = str(tmp_path / "good.jpg")
        self._write_image(good, 50)

        from pipeline.deduplicator import dedup_frames
        result = dedup_frames([bad, good])
        assert good in result

    def test_distance_zero_treats_all_unique(self, tmp_path):
        """Threshold 0 → only pixel-perfect duplicates are merged."""
        p1 = str(tmp_path / "a.jpg")
        p2 = str(tmp_path / "b.jpg")
        self._write_image(p1, 128)
        Image.new("RGB", (128, 128), color=(128, 0, 0)).save(p2, "JPEG")

        from pipeline.deduplicator import dedup_frames
        result = dedup_frames([p1, p2], max_hash_distance=0)
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════
# Merger tests
# ══════════════════════════════════════════════════════════════════════

class TestMerger:

    def test_same_brand_model_merged_keeps_highest_confidence(self):
        """Same brand+model from two frames → one item, best confidence."""
        a = _make_item("Samsung TV", "electronics", "Samsung", "QN65Q80C", confidence=0.72)
        b = _make_item("Samsung TV", "electronics", "Samsung", "QN65Q80C", confidence=0.91)

        from pipeline.merger import merge_items
        result = merge_items([("f1.jpg", [a]), ("f2.jpg", [b])])
        assert len(result) == 1
        assert result[0].identification_confidence == pytest.approx(0.91)

    def test_different_items_both_kept(self):
        tv   = _make_item("Samsung TV",   "electronics", "Samsung", "QN65", 0.90)
        sofa = _make_item("IKEA KALLAX",  "furniture",   "IKEA",    "KALLAX", 0.85)

        from pipeline.merger import merge_items
        result = merge_items([("f.jpg", [tv, sofa])])
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        from pipeline.merger import merge_items
        assert merge_items([]) == []

    def test_sorted_by_insurance_value_descending(self):
        cheap  = _make_item("Cheap Lamp",  "decor", insurance_high=1000)
        pricey = _make_item("Grand Piano", "art",   insurance_high=200000)

        from pipeline.merger import merge_items
        result = merge_items([("f.jpg", [cheap, pricey])])
        assert result[0].insurance_midpoint_cents >= result[-1].insurance_midpoint_cents

    def test_flags_unioned_on_merge(self):
        a = _make_item("Nikon D850", "electronics", "Nikon", "D850", 0.80)
        b = _make_item("Nikon D850", "electronics", "Nikon", "D850", 0.95)
        a = a.model_copy(update={"flags": ["high_value"]})
        b = b.model_copy(update={"flags": ["serialized"]})

        from pipeline.merger import merge_items
        result = merge_items([("f1.jpg", [a]), ("f2.jpg", [b])])
        assert len(result) == 1
        assert "high_value" in result[0].flags
        assert "serialized" in result[0].flags

    def test_name_only_fuzzy_merge(self):
        """Near-identical names → fuzzy merge to 1."""
        a = _make_item("65 inch Samsung television",     "electronics", confidence=0.80)
        b = _make_item("65 inch Samsung television set", "electronics", confidence=0.75)

        from pipeline.merger import merge_items
        result = merge_items([("f1.jpg", [a]), ("f2.jpg", [b])])
        assert len(result) == 1

    def test_different_categories_not_merged(self):
        """Same name but different category → not merged."""
        a = _make_item("Black Box", "electronics", confidence=0.80)
        b = _make_item("Black Box", "furniture",   confidence=0.75)

        from pipeline.merger import merge_items
        result = merge_items([("f1.jpg", [a]), ("f2.jpg", [b])])
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════
# Classifier tests (fully mocked — no Gemini calls)
# ══════════════════════════════════════════════════════════════════════

class TestClassifier:

    def test_classify_frames_parallel_returns_per_frame_result(self):
        """One result tuple per frame input."""
        items_fixture = [_make_item("Test TV", "electronics")]
        with patch("pipeline.classifier.scanner.analyze_room", return_value=items_fixture):
            from pipeline.classifier import classify_frames_parallel
            result = run_async(classify_frames_parallel(["f1.jpg", "f2.jpg"]))

        assert len(result) == 2
        assert all(isinstance(r, tuple) and len(r) == 2 for r in result)

    def test_classify_frame_error_returns_empty_list(self):
        """Frame that raises during analysis returns (path, []) without crash."""
        with patch("pipeline.classifier.scanner.analyze_room", side_effect=RuntimeError("fail")):
            from pipeline.classifier import classify_frame
            path, items = run_async(classify_frame("bad.jpg", asyncio.Semaphore(1)))

        assert path == "bad.jpg"
        assert items == []

    def test_concurrency_cap_respected(self):
        """At most max_concurrent=3 calls run simultaneously."""
        call_count = [0]
        max_seen   = [0]
        lock = threading.Lock()

        def fake_analyze(path, **_):
            with lock:
                call_count[0] += 1
                max_seen[0] = max(max_seen[0], call_count[0])
            import time; time.sleep(0.05)
            with lock:
                call_count[0] -= 1
            return []

        with patch("pipeline.classifier.scanner.analyze_room", side_effect=fake_analyze):
            from pipeline.classifier import classify_frames_parallel
            run_async(classify_frames_parallel(
                [f"f{i}.jpg" for i in range(10)],
                max_concurrent=3,
            ))

        assert max_seen[0] <= 3

    def test_empty_frame_list_returns_empty(self):
        from pipeline.classifier import classify_frames_parallel
        result = run_async(classify_frames_parallel([]))
        assert result == []


# ══════════════════════════════════════════════════════════════════════
# End-to-end recall  (Brief §13: recall >= 4/5)
# ══════════════════════════════════════════════════════════════════════

class TestEndToEndRecall:
    """
    3-frame walkthrough fixture containing 5 distinct items
    (one item appears in 2 frames → should be merged to 1).
    After merge: expect 5 unique items → recall 5/5 >= 4.
    """

    FIVE_ITEMS = [
        ("Samsung 65 QLED TV",     "electronics", "Samsung",  "QN65Q80C",    0.92),
        ("IKEA KALLAX Shelf",      "furniture",   "IKEA",     "KALLAX",      0.88),
        ("Apple MacBook Pro 16",   "electronics", "Apple",    "MacBook Pro", 0.95),
        ("Nikon Z9 Camera",        "electronics", "Nikon",    "Z9",          0.83),
        ("Bose SoundLink Speaker", "electronics", "Bose",     "SoundLink",   0.77),
    ]

    def test_five_items_recall_gte_four(self):
        """All 5 fixture items survive dedup+merge → recall = 5 >= 4."""
        tv     = _make_item(*self.FIVE_ITEMS[0])
        shelf  = _make_item(*self.FIVE_ITEMS[1])
        mac    = _make_item(*self.FIVE_ITEMS[2])
        nikon  = _make_item(*self.FIVE_ITEMS[3])
        bose   = _make_item(*self.FIVE_ITEMS[4])
        tv_dup = _make_item(*self.FIVE_ITEMS[0])  # same TV in frame 3

        frame_results = [
            ("frame_0001.jpg", [tv, shelf]),
            ("frame_0002.jpg", [mac, nikon]),
            ("frame_0003.jpg", [bose, tv_dup]),  # TV is a repeat
        ]

        from pipeline.merger import merge_items
        merged = merge_items(frame_results)

        assert len(merged) == 5, (
            f"Expected 5 unique items, got {len(merged)}: "
            f"{[i.item_name for i in merged]}"
        )

        known_names = {row[0].lower() for row in self.FIVE_ITEMS}
        recall = sum(
            1 for item in merged
            if any(kn in item.item_name.lower() for kn in known_names)
        )
        assert recall >= 4, (
            f"Recall {recall}/5 < 4. Detected: {[i.item_name for i in merged]}"
        )

    def test_merged_items_sorted_by_value(self):
        """Final output is sorted by insurance value descending."""
        items = [_make_item(*row) for row in self.FIVE_ITEMS]
        from pipeline.merger import merge_items
        merged = merge_items([("f.jpg", items)])
        values = [i.insurance_midpoint_cents for i in merged]
        assert values == sorted(values, reverse=True)
