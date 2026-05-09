# Golden Dataset

Each scene lives in its own subdirectory and requires two files:

```
scene_XXX_<description>/
  image.jpg          ← the room photograph (not committed to git)
  ground_truth.json  ← annotations (committed to git)
```

## ground_truth.json schema

```json
{
  "scene_id": "scene_001_living_room",
  "description": "Human-readable description of the scene",
  "image_file": "image.jpg",
  "items": [
    {
      "name": "Primary item name",
      "aliases": ["alternative name 1", "alternative name 2"],
      "category": "Furniture > Seating",
      "retail_usd": 800,
      "price_tolerance": 0.40,
      "min_confidence": 50
    }
  ]
}
```

## Field reference

| Field | Required | Description |
|---|---|---|
| `name` | yes | Canonical item name |
| `aliases` | yes | Alternate names the AI might use (lowercase) |
| `category` | yes | Expected Gemini category (used for price engine) |
| `retail_usd` | no | New retail price — enables price containment check |
| `price_tolerance` | no | Allowed deviation from expected price (default 0.30 = 30%) |
| `min_confidence` | no | Minimum acceptable confidence_score (default 50) |

## Adding a new scene

1. Create a new directory: `eval/golden/scene_XXX_<short_name>/`
2. Copy your room photo in as `image.jpg`
3. Write `ground_truth.json` listing the items visible in the photo
4. Run `python eval/run_eval.py --scene scene_XXX_<short_name>` to verify

## Thresholds

| Metric | Pass threshold |
|---|---|
| Recall | ≥ 0.85 |
| Precision | ≥ 0.80 |
| Price containment | ≥ 0.75 |
