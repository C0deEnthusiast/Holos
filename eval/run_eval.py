#!/usr/bin/env python3
"""
Agent 3 — Eval Harness
Measures scanner quality against a golden dataset of annotated room images.

Usage:
  python eval/run_eval.py                          # run all scenes, compare to baseline
  python eval/run_eval.py --scene scene_001        # partial scene name match
  python eval/run_eval.py --save-baseline          # promote current results to baseline
  python eval/run_eval.py --no-compare             # run without regression check
  python eval/run_eval.py --dry-run                # list scenes without running AI

Exit codes:
  0 — all metrics meet thresholds, no regression detected
  1 — a metric is below threshold or a regression was detected
  2 — no scenes found / config error
"""

from __future__ import annotations

import sys
import os

# Allow importing scanner and schemas from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import time
import argparse
import glob
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────────

GOLDEN_DIR   = Path(__file__).parent / "golden"
BASELINES_DIR = Path(__file__).parent / "baselines"
RESULTS_DIR  = Path(__file__).parent / "results"

RECALL_THRESHOLD           = 0.85
PRECISION_THRESHOLD        = 0.80
PRICE_CONTAINMENT_THRESHOLD = 0.75

REGRESSION_TOLERANCE = 0.05  # flag if any metric drops more than 5 points


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ItemMatch:
    gt_name: str
    pred_name: str
    confidence: int
    price_in_range: Optional[bool]   # None = no retail_usd to check
    confidence_ok: bool


@dataclass
class SceneResult:
    scene_id: str
    image_path: str
    gt_count: int
    pred_count: int
    matches: list[ItemMatch] = field(default_factory=list)
    unmatched_gt: list[str] = field(default_factory=list)
    unmatched_pred: list[str] = field(default_factory=list)
    error: Optional[str] = None
    latency_s: float = 0.0


@dataclass
class EvalMetrics:
    recall: float            # matched_gt / total_gt
    precision: float         # matched_pred / total_pred
    price_containment: float # priced_in_range / total_priced
    scene_count: int
    total_gt: int
    total_pred: int
    total_matched: int
    total_priced: int
    total_price_ok: int
    scenes_with_errors: int
    run_timestamp: str = ""
    thresholds: dict = field(default_factory=lambda: {
        "recall": RECALL_THRESHOLD,
        "precision": PRECISION_THRESHOLD,
        "price_containment": PRICE_CONTAINMENT_THRESHOLD,
    })

    def passes(self) -> bool:
        return (
            self.recall >= RECALL_THRESHOLD
            and self.precision >= PRECISION_THRESHOLD
            and self.price_containment >= PRICE_CONTAINMENT_THRESHOLD
        )


# ── Matching helpers ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens, strip punctuation."""
    return set(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def _item_matches(gt: dict, pred: dict) -> bool:
    """
    Token-overlap matching between a ground truth item and a predicted item.
    Checks the GT name, then each alias. Category must also broadly agree.
    """
    pred_tokens = _tokenize(pred.get("name", ""))
    if not pred_tokens:
        return False

    # Name overlap
    if _tokenize(gt["name"]) & pred_tokens:
        return True

    # Alias overlap
    for alias in gt.get("aliases", []):
        if _tokenize(alias) & pred_tokens:
            return True

    return False


def _price_in_range(gt: dict, pred: dict) -> Optional[bool]:
    """
    Check whether the predicted estimated_price_usd is within tolerance of
    the value the pricing engine would derive from gt.retail_usd.
    Returns None if ground truth has no retail_usd anchor.
    """
    retail_usd = gt.get("retail_usd")
    if not retail_usd:
        return None

    predicted = pred.get("estimated_price_usd", 0)
    if not predicted:
        return False

    from schemas import compute_prices
    condition = pred.get("condition", "Good")
    category = gt.get("category", pred.get("category", ""))
    qty = int(pred.get("quantity") or 1)

    expected = compute_prices(
        retail_usd=float(retail_usd),
        category=category,
        condition=condition,
        quantity=qty,
    )["estimated_price_usd"]

    tolerance = gt.get("price_tolerance", 0.30)
    if expected == 0:
        return None

    deviation = abs(predicted - expected) / expected
    return deviation <= tolerance


def _match_items(gt_items: list[dict], pred_items: list[dict]) -> tuple[list[ItemMatch], list[str], list[str]]:
    """
    Greedy matching: each GT item is matched to at most one predicted item and vice versa.
    Returns (matches, unmatched_gt_names, unmatched_pred_names).
    """
    used_pred = set()
    matches: list[ItemMatch] = []
    unmatched_gt: list[str] = []

    for gt in gt_items:
        found = False
        for j, pred in enumerate(pred_items):
            if j in used_pred:
                continue
            if _item_matches(gt, pred):
                used_pred.add(j)
                matches.append(ItemMatch(
                    gt_name=gt["name"],
                    pred_name=pred.get("name", ""),
                    confidence=int(pred.get("confidence_score") or 0),
                    price_in_range=_price_in_range(gt, pred),
                    confidence_ok=int(pred.get("confidence_score") or 0) >= gt.get("min_confidence", 50),
                ))
                found = True
                break
        if not found:
            unmatched_gt.append(gt["name"])

    unmatched_pred = [
        pred_items[j].get("name", f"item_{j}") for j in range(len(pred_items)) if j not in used_pred
    ]

    return matches, unmatched_gt, unmatched_pred


# ── Scene runner ──────────────────────────────────────────────────────────────

def load_scene(scene_dir: Path) -> tuple[Path, dict] | None:
    """Load ground_truth.json and locate the image. Returns None if image is missing."""
    gt_path = scene_dir / "ground_truth.json"
    if not gt_path.exists():
        return None

    with open(gt_path) as f:
        gt = json.load(f)

    image_file = gt.get("image_file", "image.jpg")
    image_path = scene_dir / image_file
    if not image_path.exists():
        return None

    return image_path, gt


def run_scene(scene_dir: Path, verbose: bool = False) -> SceneResult:
    """Run the scanner on one scene and compute match stats."""
    import scanner

    load_result = load_scene(scene_dir)
    scene_id = scene_dir.name

    if load_result is None:
        return SceneResult(
            scene_id=scene_id,
            image_path=str(scene_dir / "image.jpg"),
            gt_count=0,
            pred_count=0,
            error="image_not_found",
        )

    image_path, gt = load_result
    gt_items = gt.get("items", [])

    t0 = time.time()
    try:
        raw_result = scanner.analyze_room(str(image_path))
    except Exception as e:
        return SceneResult(
            scene_id=scene_id,
            image_path=str(image_path),
            gt_count=len(gt_items),
            pred_count=0,
            error=str(e),
            latency_s=time.time() - t0,
        )
    latency = time.time() - t0

    if raw_result in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE") or str(raw_result).startswith("SCAN_ERROR"):
        return SceneResult(
            scene_id=scene_id,
            image_path=str(image_path),
            gt_count=len(gt_items),
            pred_count=0,
            error=raw_result,
            latency_s=latency,
        )

    try:
        pred_items = json.loads(raw_result)
        if not isinstance(pred_items, list):
            pred_items = [pred_items]
    except Exception as e:
        return SceneResult(
            scene_id=scene_id,
            image_path=str(image_path),
            gt_count=len(gt_items),
            pred_count=0,
            error=f"json_parse: {e}",
            latency_s=latency,
        )

    matches, unmatched_gt, unmatched_pred = _match_items(gt_items, pred_items)

    return SceneResult(
        scene_id=scene_id,
        image_path=str(image_path),
        gt_count=len(gt_items),
        pred_count=len(pred_items),
        matches=matches,
        unmatched_gt=unmatched_gt,
        unmatched_pred=unmatched_pred,
        latency_s=round(latency, 2),
    )


# ── Metric aggregation ────────────────────────────────────────────────────────

def compute_metrics(scene_results: list[SceneResult], run_timestamp: str) -> EvalMetrics:
    total_gt = total_pred = total_matched = total_priced = total_price_ok = scenes_with_errors = 0

    for r in scene_results:
        if r.error:
            scenes_with_errors += 1
            if r.error == "image_not_found":
                continue  # don't penalise missing images — scene is skipped

        total_gt   += r.gt_count
        total_pred += r.pred_count
        total_matched += len(r.matches)

        for m in r.matches:
            if m.price_in_range is not None:
                total_priced += 1
                if m.price_in_range:
                    total_price_ok += 1

    recall    = total_matched / total_gt  if total_gt   > 0 else 0.0
    precision = total_matched / total_pred if total_pred > 0 else 0.0
    price_containment = total_price_ok / total_priced if total_priced > 0 else 1.0

    return EvalMetrics(
        recall=round(recall, 4),
        precision=round(precision, 4),
        price_containment=round(price_containment, 4),
        scene_count=len(scene_results),
        total_gt=total_gt,
        total_pred=total_pred,
        total_matched=total_matched,
        total_priced=total_priced,
        total_price_ok=total_price_ok,
        scenes_with_errors=scenes_with_errors,
        run_timestamp=run_timestamp,
    )


# ── Regression detection ──────────────────────────────────────────────────────

def load_latest_baseline() -> dict | None:
    """Return the most recent baseline JSON, or None if no baselines exist."""
    files = sorted(BASELINES_DIR.glob("baseline_*.json"), reverse=True)
    if not files:
        return None
    with open(files[0]) as f:
        return json.load(f)


def check_regression(current: EvalMetrics, baseline: dict) -> list[str]:
    """
    Return a list of regression messages. Empty list = no regression.
    Flags: metric dropped more than REGRESSION_TOLERANCE points, or is below threshold.
    """
    regressions: list[str] = []
    for metric_name in ("recall", "precision", "price_containment"):
        current_val = getattr(current, metric_name)
        baseline_val = baseline.get(metric_name, 0.0)
        drop = baseline_val - current_val

        threshold = getattr(current.thresholds, metric_name) if hasattr(current.thresholds, metric_name) \
                    else current.thresholds.get(metric_name, 0.0)

        if current_val < threshold:
            regressions.append(
                f"  {metric_name}: {current_val:.3f} is BELOW threshold {threshold:.2f}"
            )
        elif drop > REGRESSION_TOLERANCE:
            regressions.append(
                f"  {metric_name}: {current_val:.3f} dropped {drop:.3f} from baseline {baseline_val:.3f}"
            )

    return regressions


# ── Report printing ───────────────────────────────────────────────────────────

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _pass_fail(v: float, threshold: float) -> str:
    return "✅ PASS" if v >= threshold else "❌ FAIL"


def print_report(
    scene_results: list[SceneResult],
    metrics: EvalMetrics,
    baseline: dict | None,
    regressions: list[str],
    verbose: bool,
) -> None:
    ts = metrics.run_timestamp
    print(f"\n{'═'*60}")
    print(f"  HOLOS EVAL REPORT — {ts}")
    print(f"{'═'*60}")

    # Per-scene detail
    active = [r for r in scene_results if r.error != "image_not_found"]
    skipped = [r for r in scene_results if r.error == "image_not_found"]

    if skipped:
        print(f"\n  Skipped {len(skipped)} scene(s) — image not found:")
        for r in skipped:
            print(f"    · {r.scene_id} (add {r.image_path})")

    for r in active:
        status = f"ERROR ({r.error})" if r.error else f"{r.latency_s}s"
        recall_s   = f"{len(r.matches)}/{r.gt_count}"
        precision_s = f"{len(r.matches)}/{r.pred_count}"
        print(f"\n  Scene: {r.scene_id}  [{status}]")
        print(f"    Recall {recall_s}  ·  Precision {precision_s}")

        if verbose and r.matches:
            for m in r.matches:
                price_tag = (
                    " price✅" if m.price_in_range is True else
                    " price❌" if m.price_in_range is False else ""
                )
                conf_tag = "" if m.confidence_ok else " conf⚠"
                print(f"      ✓ {m.gt_name!r} → {m.pred_name!r} (conf={m.confidence}){price_tag}{conf_tag}")

        if verbose and r.unmatched_gt:
            for name in r.unmatched_gt:
                print(f"      ✗ missed:      {name!r}")

        if verbose and r.unmatched_pred:
            for name in r.unmatched_pred:
                print(f"      ? extra pred:  {name!r}")

    # Summary metrics
    print(f"\n{'─'*60}")
    print(f"  METRICS (scenes run: {len(active)}, gt_items: {metrics.total_gt}, predicted: {metrics.total_pred})")
    print(f"{'─'*60}")

    recall_pass = _pass_fail(metrics.recall, RECALL_THRESHOLD)
    prec_pass   = _pass_fail(metrics.precision, PRECISION_THRESHOLD)
    price_pass  = _pass_fail(metrics.price_containment, PRICE_CONTAINMENT_THRESHOLD)

    baseline_recall = f"  baseline={_pct(baseline['recall'])}" if baseline else ""
    baseline_prec   = f"  baseline={_pct(baseline['precision'])}" if baseline else ""
    baseline_price  = f"  baseline={_pct(baseline['price_containment'])}" if baseline else ""

    print(f"  Recall           {_pct(metrics.recall):>7}  (threshold {_pct(RECALL_THRESHOLD)}) {recall_pass}{baseline_recall}")
    print(f"  Precision        {_pct(metrics.precision):>7}  (threshold {_pct(PRECISION_THRESHOLD)}) {prec_pass}{baseline_prec}")
    print(f"  Price Containment{_pct(metrics.price_containment):>7}  (threshold {_pct(PRICE_CONTAINMENT_THRESHOLD)}) {price_pass}{baseline_price}")

    if baseline:
        print(f"\n  Baseline: {baseline.get('run_timestamp', 'unknown')}")

    # Regression summary
    if regressions:
        print(f"\n{'─'*60}")
        print("  ⚠  REGRESSIONS DETECTED:")
        for r in regressions:
            print(r)

    overall = "✅ PASS" if metrics.passes() and not regressions else "❌ FAIL"
    print(f"\n  Overall: {overall}")
    print(f"{'═'*60}\n")


# ── Save helpers ──────────────────────────────────────────────────────────────

def save_result(metrics: EvalMetrics, scene_results: list[SceneResult]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    ts_safe = metrics.run_timestamp.replace(":", "-").replace(" ", "_")
    out_path = RESULTS_DIR / f"result_{ts_safe}.json"
    payload = {
        **asdict(metrics),
        "scenes": [asdict(r) for r in scene_results],
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    return out_path


def save_baseline(metrics: EvalMetrics) -> Path:
    BASELINES_DIR.mkdir(exist_ok=True)
    ts_safe = metrics.run_timestamp.replace(":", "-").replace(" ", "_")
    out_path = BASELINES_DIR / f"baseline_{ts_safe}.json"
    with open(out_path, "w") as f:
        json.dump(asdict(metrics), f, indent=2)
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Holos Eval Harness — measure scanner quality vs golden dataset"
    )
    p.add_argument("--scene", metavar="PATTERN",
                   help="Run only scenes whose directory name contains PATTERN")
    p.add_argument("--save-baseline", action="store_true",
                   help="Promote this run's results to the baseline after running")
    p.add_argument("--no-compare", action="store_true",
                   help="Skip regression comparison against the baseline")
    p.add_argument("--dry-run", action="store_true",
                   help="List scenes without running AI inference")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show per-item match details")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Suppress noisy AI/http logs during eval unless verbose
    os.environ.setdefault("FLASK_DEBUG", "true")
    from observability import configure_logging
    configure_logging(debug=args.verbose)

    # Discover scenes
    all_scene_dirs = sorted(GOLDEN_DIR.iterdir()) if GOLDEN_DIR.exists() else []
    all_scene_dirs = [d for d in all_scene_dirs if d.is_dir() and (d / "ground_truth.json").exists()]

    if args.scene:
        all_scene_dirs = [d for d in all_scene_dirs if args.scene in d.name]

    if not all_scene_dirs:
        print(f"No scenes found in {GOLDEN_DIR}")
        print("Add annotated scenes following eval/golden/README.md")
        return 2

    if args.dry_run:
        print(f"\nScenes found ({len(all_scene_dirs)}):")
        for d in all_scene_dirs:
            has_image = load_scene(d) is not None
            status = "ready" if has_image else "⚠ missing image"
            print(f"  {d.name}  [{status}]")
        return 0

    run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\nRunning eval: {len(all_scene_dirs)} scene(s) at {run_timestamp}")

    scene_results: list[SceneResult] = []
    for scene_dir in all_scene_dirs:
        print(f"  → {scene_dir.name} ...", end=" ", flush=True)
        result = run_scene(scene_dir, verbose=args.verbose)
        if result.error == "image_not_found":
            print("skipped (no image)")
        elif result.error:
            print(f"ERROR: {result.error}")
        else:
            r_pct = f"{len(result.matches)}/{result.gt_count}"
            p_pct = f"{len(result.matches)}/{result.pred_count}"
            print(f"recall {r_pct}  precision {p_pct}  ({result.latency_s}s)")
        scene_results.append(result)

    metrics = compute_metrics(scene_results, run_timestamp)
    result_path = save_result(metrics, scene_results)
    print(f"\nResults saved → {result_path.relative_to(Path(__file__).parent.parent)}")

    # Regression check
    baseline = None
    regressions: list[str] = []
    if not args.no_compare:
        baseline = load_latest_baseline()
        if baseline:
            regressions = check_regression(metrics, baseline)
        else:
            print("No baseline found — run with --save-baseline to create one.")

    print_report(scene_results, metrics, baseline, regressions, args.verbose)

    if args.save_baseline:
        bl_path = save_baseline(metrics)
        print(f"Baseline saved → {bl_path.relative_to(Path(__file__).parent.parent)}\n")

    return 0 if (metrics.passes() and not regressions) else 1


if __name__ == "__main__":
    sys.exit(main())
