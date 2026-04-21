# Holos Golden Eval Dataset — v1

This directory contains the ground-truth labeled dataset for the vision classifier eval harness.
Per §8.6: 25 hand-labeled images, growing monthly.

## Directory Structure

```
evals/dataset/
  001_living_room/
    image.jpg           <- actual room photo
    ground_truth.yaml   <- labeled items with expected values
  002_bedroom/
    ...
```

## Ground Truth YAML Schema

```yaml
scene_id: "001"
room_type: "living_room"
scene_description: "Mid-century modern living room, good lighting"
price_tier: "mid_range"       # budget | mid_range | luxury | designer

items:
  - item_name: "IKEA KALLAX Shelf Unit"
    category: "furniture"
    subcategory: "storage"
    brand: "IKEA"
    model: "KALLAX"
    condition: "good"
    # Retail midpoint in cents (what the eval checks against)
    retail_midpoint_cents: 19900
    # Acceptable range for model to be within (±30% for price-range containment metric)
    retail_tolerance_pct: 0.30
    # Bounding box ground truth [ymin, xmin, ymax, xmax] 0-1000
    bounding_box: [200, 50, 800, 400]
    # Flags expected
    flags: []
    # Is this item visible enough to detect?
    detectable: true
    # Notes for human reviewer
    notes: "White 4x2 grid unit, typical price $199"
```

## Metrics Computed

Per §8.6:
- **Item Recall**: detected / total_gt (target ≥ 0.85)
- **Item Precision**: correct / detected (target ≥ 0.80)
- **Category Accuracy**: correct_category / detected_correct_items
- **Brand/Model Accuracy**: brand_match / detectable_branded_items
- **Price-Range Containment**: retail_gt within model's low-high range (target ≥ 0.75)
- **Condition κ**: Cohen's kappa vs ground truth condition labels
- **Bounding Box IoU ≥ 0.5**: intersection-over-union on matched items
- **Confidence Calibration (ECE)**: Expected Calibration Error (target < 0.10)
- **Per-scan cost**: sum of ai_calls.cost_cents for scan
- **Per-scan latency**: wall-clock seconds

## CI Gate

Any PR touching `backend/prompts/` or `scanner.py` triggers the eval.
Regression threshold: no metric worse than −2% absolute without `ALLOW_EVAL_REGRESSION=reason`.

## Adding New Images

1. Add directory `evals/dataset/NNN_description/`
2. Drop `image.jpg` (or `.png`, `.webp`)
3. Fill `ground_truth.yaml` per schema above
4. Run `python evals/run_eval.py --dataset evals/dataset/` to verify it parses
5. Commit both image and YAML together

Target: grow to 50 images by Month 3, 100 by Month 6.
