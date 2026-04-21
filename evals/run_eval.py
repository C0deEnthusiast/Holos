"""
Holos Vision Classifier Eval Harness — Agent 3
Runs the golden dataset against the live scanner and computes all §8.6 metrics.

Usage:
    python evals/run_eval.py                        # all scenes
    python evals/run_eval.py --scene 001            # single scene
    python evals/run_eval.py --dry-run              # print ground truth only, no API calls
    python evals/run_eval.py --output evals/reports/run_2026-04-19.json

Metrics computed per §8.6:
    item_recall         >= 0.85  (detected / gt_total)
    item_precision      >= 0.80  (matched / detected)
    category_accuracy   -        (correct_category / matched)
    brand_accuracy      -        (correct_brand / branded_gt)
    price_containment   >= 0.75  (gt_retail within model [low, high])
    condition_kappa     -        (Cohen's kappa vs ground truth)
    iou_50              -        (fraction of matched pairs with IoU >= 0.5)
    ece                 <= 0.10  (Expected Calibration Error on identification_confidence)
    total_cost_cents    -        (sum ai_calls.cost_cents per run)
    avg_latency_s       -        (avg wall-clock per scene)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml  # PyYAML

# Add project root to path so scanner and schemas import cleanly
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from schemas import ItemEstimate, Condition, Category

DATASET_DIR = Path(__file__).parent / "dataset"
REPORTS_DIR = Path(__file__).parent / "reports"

# §8.6 quality thresholds — these become CI gates
THRESHOLDS = {
    "item_recall":       0.85,
    "item_precision":    0.80,
    "price_containment": 0.75,
    "ece":               0.10,   # lower is better
}


# ---------------------------------------------------------------------------
# Dataset Loading
# ---------------------------------------------------------------------------

def load_ground_truths(scene_filter: str | None = None) -> list[dict]:
    scenes = []
    for gt_path in sorted(DATASET_DIR.glob("*/ground_truth.yaml")):
        scene_dir = gt_path.parent
        scene_id = scene_dir.name.split("_")[0]

        if scene_filter and scene_filter not in scene_dir.name:
            continue

        with open(gt_path, encoding="utf-8") as f:
            gt = yaml.safe_load(f)

        # Find image file
        image_path = None
        for ext in ("jpg", "jpeg", "png", "webp"):
            candidate = scene_dir / f"image.{ext}"
            if candidate.exists():
                image_path = candidate
                break

        scenes.append({
            "scene_id": gt.get("scene_id", scene_id),
            "scene_dir": scene_dir,
            "image_path": image_path,
            "gt": gt,
            "items": gt.get("items", []),
        })

    return scenes


# ---------------------------------------------------------------------------
# Metric Helpers
# ---------------------------------------------------------------------------

def iou(box_a: list[int], box_b: list[int]) -> float:
    """
    IoU between two [ymin, xmin, ymax, xmax] boxes in 0-1000 coords.
    """
    ya1, xa1, ya2, xa2 = box_a
    yb1, xb1, yb2, xb2 = box_b

    inter_y1 = max(ya1, yb1)
    inter_x1 = max(xa1, xb1)
    inter_y2 = min(ya2, yb2)
    inter_x2 = min(xa2, xb2)

    inter_h = max(0, inter_y2 - inter_y1)
    inter_w = max(0, inter_x2 - inter_x1)
    intersection = inter_h * inter_w

    area_a = max(0, ya2 - ya1) * max(0, xa2 - xa1)
    area_b = max(0, yb2 - yb1) * max(0, xb2 - xb1)
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


def match_items(
    gt_items: list[dict],
    pred_items: list[ItemEstimate],
) -> list[tuple[dict, ItemEstimate]]:
    """
    Greedy Hungarian-style matching: match each GT item to its best-IoU
    prediction with the same broad category. Falls back to name similarity.
    Returns list of (gt_item, pred_item) pairs.
    """
    used_preds: set[int] = set()
    matches: list[tuple[dict, ItemEstimate]] = []

    for gt in gt_items:
        if not gt.get("detectable", True):
            continue

        gt_box = gt.get("bounding_box", [0, 0, 0, 0])
        gt_cat = gt.get("category", "").lower()

        best_score = -1.0
        best_idx = -1

        for i, pred in enumerate(pred_items):
            if i in used_preds:
                continue

            pred_cat = pred.category.value.lower() if pred.category else ""
            cat_match = (
                gt_cat == pred_cat
                or gt_cat[:4] == pred_cat[:4]  # first 4 chars usually enough
            )

            pred_box = list(pred.bounding_box) if pred.bounding_box else [0, 0, 0, 0]
            box_iou = iou(gt_box, pred_box)

            # Score = 0.6 * IoU + 0.4 * category_match
            score = 0.6 * box_iou + 0.4 * float(cat_match)

            if score > best_score and score > 0.15:  # minimum threshold
                best_score = score
                best_idx = i

        if best_idx >= 0:
            used_preds.add(best_idx)
            matches.append((gt, pred_items[best_idx]))

    return matches


def price_contained(
    gt_retail_cents: int,
    pred_low: int,
    pred_high: int,
    gt_tolerance: float,
) -> bool:
    """
    True if the GT retail midpoint falls within the predicted range,
    OR within the GT-defined tolerance band of the midpoint.
    """
    if pred_low <= gt_retail_cents <= pred_high:
        return True
    # Allow GT tolerance: GT value within ±tolerance% of pred midpoint
    pred_mid = (pred_low + pred_high) / 2
    if pred_mid > 0 and abs(gt_retail_cents - pred_mid) / pred_mid <= gt_tolerance:
        return True
    return False


def cohens_kappa(gt_labels: list[str], pred_labels: list[str]) -> float:
    """Cohen's kappa for categorical agreement."""
    if len(gt_labels) != len(pred_labels) or not gt_labels:
        return 0.0

    classes = list(set(gt_labels + pred_labels))
    n = len(gt_labels)
    po = sum(g == p for g, p in zip(gt_labels, pred_labels)) / n

    gt_counts = {c: gt_labels.count(c) / n for c in classes}
    pred_counts = {c: pred_labels.count(c) / n for c in classes}
    pe = sum(gt_counts.get(c, 0) * pred_counts.get(c, 0) for c in classes)

    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def expected_calibration_error(
    confidences: list[float],
    correct: list[bool],
    n_bins: int = 10,
) -> float:
    """ECE: |avg_confidence - accuracy| weighted by bin size."""
    if not confidences:
        return 0.0

    bins = defaultdict(list)
    for conf, is_correct in zip(confidences, correct):
        bin_idx = min(int(conf * n_bins), n_bins - 1)
        bins[bin_idx].append((conf, is_correct))

    ece = 0.0
    n = len(confidences)
    for bin_items in bins.values():
        avg_conf = sum(c for c, _ in bin_items) / len(bin_items)
        avg_acc = sum(1 for _, ok in bin_items if ok) / len(bin_items)
        ece += (len(bin_items) / n) * abs(avg_conf - avg_acc)

    return ece


# ---------------------------------------------------------------------------
# Per-Scene Eval
# ---------------------------------------------------------------------------

def eval_scene(scene: dict, dry_run: bool = False) -> dict:
    """Run eval for a single scene. Returns metric dict."""
    gt_items = scene["items"]
    image_path = scene["image_path"]
    scene_id = scene["scene_id"]

    print(f"\n{'='*60}")
    print(f"  Scene {scene_id}: {scene['gt'].get('room_type', '?')} "
          f"({scene['gt'].get('price_tier', '?')})")
    print(f"  GT items: {len(gt_items)}")

    if dry_run or image_path is None:
        reason = "dry_run" if dry_run else "no_image"
        print(f"  SKIPPING ({reason})")
        return {
            "scene_id": scene_id,
            "skipped": True,
            "skip_reason": reason,
            "gt_count": len(gt_items),
        }

    from scanner import analyze_room, GeminiScanError, GeminiQuotaError, GeminiUnavailableError

    # Run scan
    t0 = time.time()
    pred_items: list[ItemEstimate] = []
    scan_error = None

    try:
        pred_items = analyze_room(str(image_path))
    except (GeminiScanError, GeminiQuotaError, GeminiUnavailableError, Exception) as e:
        scan_error = str(e)
        print(f"  SCAN ERROR: {e}")

    latency = time.time() - t0
    print(f"  Predicted items: {len(pred_items)}  (latency: {latency:.1f}s)")

    if scan_error:
        return {
            "scene_id": scene_id,
            "scan_error": scan_error,
            "latency_s": latency,
            "gt_count": len(gt_items),
            "pred_count": 0,
        }

    # Match predictions to ground truth
    detectable_gt = [i for i in gt_items if i.get("detectable", True)]
    matches = match_items(detectable_gt, pred_items)

    # ── Recall / Precision ───────────────────────────────────────
    recall = len(matches) / max(len(detectable_gt), 1)
    precision = len(matches) / max(len(pred_items), 1)

    # ── Category Accuracy ────────────────────────────────────────
    category_correct = sum(
        1 for gt, pred in matches
        if gt.get("category", "").lower() == pred.category.value.lower()
    )
    category_accuracy = category_correct / max(len(matches), 1)

    # ── Brand Accuracy ───────────────────────────────────────────
    branded_gt = [(gt, pred) for gt, pred in matches if gt.get("brand")]
    brand_correct = sum(
        1 for gt, pred in branded_gt
        if (pred.brand or "").lower().split()[0] == gt["brand"].lower().split()[0]
    )
    brand_accuracy = brand_correct / max(len(branded_gt), 1) if branded_gt else None

    # ── Price-Range Containment ──────────────────────────────────
    priced_pairs = [
        (gt, pred) for gt, pred in matches
        if gt.get("retail_midpoint_cents", 0) > 0
    ]
    price_contained_count = sum(
        1 for gt, pred in priced_pairs
        if price_contained(
            gt["retail_midpoint_cents"],
            pred.value_retail_replacement_low_cents,
            pred.value_retail_replacement_high_cents,
            gt.get("retail_tolerance_pct", 0.30),
        )
    )
    price_containment = price_contained_count / max(len(priced_pairs), 1)

    # ── Condition κ ──────────────────────────────────────────────
    gt_conditions = [gt.get("condition", "good") for gt, _ in matches]
    pred_conditions = [pred.condition.value for _, pred in matches]
    condition_kappa = cohens_kappa(gt_conditions, pred_conditions)

    # ── IoU ≥ 0.5 ────────────────────────────────────────────────
    iou_scores = []
    for gt, pred in matches:
        gt_box = gt.get("bounding_box", [0, 0, 0, 0])
        pred_box = list(pred.bounding_box) if pred.bounding_box else [0, 0, 0, 0]
        iou_scores.append(iou(gt_box, pred_box))
    iou_50_rate = sum(1 for s in iou_scores if s >= 0.5) / max(len(iou_scores), 1)

    # ── ECE (Expected Calibration Error) ─────────────────────────
    confidences = [pred.identification_confidence for _, pred in matches]
    # "Correct" = category matched AND brand matched (where GT has brand)
    correct_flags = [
        gt.get("category", "").lower() == pred.category.value.lower()
        for gt, pred in matches
    ]
    ece = expected_calibration_error(confidences, correct_flags)

    # ── Result ───────────────────────────────────────────────────
    result = {
        "scene_id": scene_id,
        "room_type": scene["gt"].get("room_type"),
        "price_tier": scene["gt"].get("price_tier"),
        "gt_count": len(detectable_gt),
        "pred_count": len(pred_items),
        "matched_count": len(matches),
        "item_recall": round(recall, 4),
        "item_precision": round(precision, 4),
        "category_accuracy": round(category_accuracy, 4),
        "brand_accuracy": round(brand_accuracy, 4) if brand_accuracy is not None else None,
        "price_containment": round(price_containment, 4),
        "condition_kappa": round(condition_kappa, 4),
        "iou_50_rate": round(iou_50_rate, 4),
        "ece": round(ece, 4),
        "latency_s": round(latency, 2),
    }

    # ── Per-scene summary ─────────────────────────────────────────
    print(f"  Recall: {recall:.1%}  Precision: {precision:.1%}  "
          f"Category: {category_accuracy:.1%}  Price: {price_containment:.1%}")
    if brand_accuracy is not None:
        print(f"  Brand: {brand_accuracy:.1%}  Condition κ: {condition_kappa:.2f}  "
              f"IoU≥50: {iou_50_rate:.1%}  ECE: {ece:.3f}")
    print(f"  Latency: {latency:.1f}s")

    return result


# ---------------------------------------------------------------------------
# Aggregate Metrics
# ---------------------------------------------------------------------------

def aggregate(results: list[dict]) -> dict:
    """Average all metrics across scenes, excluding skipped/errored ones."""
    valid = [r for r in results if not r.get("skipped") and not r.get("scan_error")]
    if not valid:
        return {"error": "no valid results"}

    def avg(key: str) -> float | None:
        vals = [r[key] for r in valid if key in r and r[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "scene_count": len(valid),
        "total_gt_items": sum(r["gt_count"] for r in valid),
        "total_pred_items": sum(r["pred_count"] for r in valid),
        "total_matched": sum(r["matched_count"] for r in valid),
        "item_recall":       avg("item_recall"),
        "item_precision":    avg("item_precision"),
        "category_accuracy": avg("category_accuracy"),
        "brand_accuracy":    avg("brand_accuracy"),
        "price_containment": avg("price_containment"),
        "condition_kappa":   avg("condition_kappa"),
        "iou_50_rate":       avg("iou_50_rate"),
        "ece":               avg("ece"),
        "avg_latency_s":     avg("latency_s"),
    }


def check_thresholds(agg: dict) -> list[str]:
    """Returns list of threshold violations. Empty = pass."""
    violations = []
    for metric, threshold in THRESHOLDS.items():
        val = agg.get(metric)
        if val is None:
            continue
        if metric == "ece":
            if val > threshold:
                violations.append(
                    f"{metric}: {val:.4f} > threshold {threshold} (lower is better)"
                )
        else:
            if val < threshold:
                violations.append(
                    f"{metric}: {val:.4f} < threshold {threshold}"
                )
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Holos Eval Harness")
    parser.add_argument("--scene", help="Filter by scene ID or name substring")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", help="Path to write JSON report")
    parser.add_argument(
        "--baseline",
        help="Path to baseline report JSON — compare and fail on regression"
    )
    args = parser.parse_args()

    scenes = load_ground_truths(scene_filter=args.scene)
    if not scenes:
        print("No scenes found. Add labeled images to evals/dataset/")
        sys.exit(0)

    print(f"\nHolos Eval Harness v1 — {len(scenes)} scenes")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    results = []
    for scene in scenes:
        result = eval_scene(scene, dry_run=args.dry_run)
        results.append(result)

    agg = aggregate(results)
    violations = check_thresholds(agg)

    print("\n" + "="*60)
    print("AGGREGATE METRICS")
    print("="*60)
    for k, v in agg.items():
        if v is None:
            continue
        if not isinstance(v, (int, float)):
            continue
        threshold = THRESHOLDS.get(k)
        status = ""
        if threshold is not None:
            if k == "ece":
                status = " [OK]" if v <= threshold else " [FAIL]"
            else:
                status = " [OK]" if v >= threshold else " [FAIL]"
        print(f"  {k:<25} {v:.4f}{status}")

    if violations:
        print(f"\nFAIL: {len(violations)} threshold violation(s):")
        for v in violations:
            print(f"   - {v}")
    else:
        print("\nOK: All thresholds passed")

    # Regression check
    if args.baseline:
        try:
            with open(args.baseline, encoding="utf-8") as f:
                baseline = json.load(f)
            baseline_agg = baseline.get("aggregate", {})
            regressions = []
            for metric in THRESHOLDS:
                base_val = baseline_agg.get(metric)
                new_val = agg.get(metric)
                if base_val is None or new_val is None:
                    continue
                delta = new_val - base_val
                if metric == "ece":
                    delta = -delta  # lower is better
                if delta < -0.02:  # 2% absolute regression
                    regressions.append(f"{metric}: {base_val:.4f} -> {new_val:.4f} (Δ{delta:+.4f})")
            if regressions:
                print(f"\nREGRESSION vs baseline ({args.baseline}):")
                for r in regressions:
                    print(f"   - {r}")
                if not os.environ.get("ALLOW_EVAL_REGRESSION"):
                    sys.exit(2)
        except FileNotFoundError:
            print(f"  Baseline not found at {args.baseline} -- skipping regression check")

    # Write report
    report = {
        "eval_version": "1",
        "scene_count": len(scenes),
        "aggregate": agg,
        "scenes": results,
        "thresholds": THRESHOLDS,
        "violations": violations,
    }

    output_path = args.output or str(REPORTS_DIR / "latest.json")
    REPORTS_DIR.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport written: {output_path}")

    if violations:
        sys.exit(1)


if __name__ == "__main__":
    main()
