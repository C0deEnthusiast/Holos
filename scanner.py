"""
Holos Scanner — Agent 2: AI Reliability
Two-pass architecture:
  Pass 1 (VISION_MODEL / Flash): identify items, condition, dimensions, bounding boxes,
          and a single retail_usd anchor per item.
  Pricing engine (Python): derives all price fields deterministically from retail_usd
          + the depreciation table in schemas.py.

This decouples visual identification from valuation:
- Flash is cheaper and fast at spatial reasoning / object detection.
- Pricing is now deterministic — same retail anchor always yields same prices.
- Pydantic (ScannedItem) validates every field before the response leaves this module.

Agent 0B instrumentation: every Gemini call logs token counts and cost via
record_ai_call_stat(). Outer functions use @observe_ai_call.
"""

import os
import json
import tempfile
import time
import random
import traceback
import uuid

from google import genai
from dotenv import load_dotenv
from PIL import Image, ImageFilter, ImageOps
from pydantic import BaseModel, Field as PydanticField

from observability import get_logger, observe_ai_call, record_ai_call_stat
from schemas import ScannedItem, ResaleListing, compute_prices, parse_price, is_antique

load_dotenv()

log = get_logger("scanner", agent_id="2")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")

client = genai.Client(api_key=API_KEY)

# Two-Model Architecture:
# VISION_MODEL  = Gemini Flash — fast, cheap, excels at spatial reasoning / object detection
# PRICING_MODEL = kept for resale listing generation (text-only, benefits from Pro reasoning)
VISION_MODEL  = os.getenv("GEMINI_VISION_MODEL",  "gemini-3-flash-preview")
PRICING_MODEL = os.getenv("GEMINI_PRICING_MODEL", "gemini-2.5-pro")
MODEL_ID = VISION_MODEL  # backward compat alias

log.info("scanner_initialized", vision_model=VISION_MODEL, pricing_model=PRICING_MODEL)


# ═══════════════════════════════════════════════════════════════
# GEMINI OUTPUT SCHEMA
# ═══════════════════════════════════════════════════════════════

class _GeminiItem(BaseModel):
    """
    Enforced at the Gemini API level via response_schema.
    Only covers fields the model generates — no route-injected fields.
    Gemini uses constrained decoding against this schema, guaranteeing
    valid JSON without markdown fences or leading reasoning text.
    """
    name: str
    category: str
    make: str = "Unknown"
    model: str = "Unidentified"
    quantity: int = 1
    is_set: bool = False
    estimated_age_years: str = ""
    condition: str = "Good"
    condition_notes: str = ""
    estimated_dimensions: str = ""
    retail_usd: int = 0
    confidence_score: int = 50
    identification_basis: str = ""
    suggested_replacements: str = ""
    bounding_box: list[int] = PydanticField(default_factory=lambda: [0, 0, 0, 0])


# ═══════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
You are an expert home appraiser and certified personal property valuator with 20 years of
experience in furniture, electronics, fine art, collectibles, and appliances. You have deep
knowledge of secondary markets including eBay sold listings, Facebook Marketplace, 1stDibs,
Chairish, AptDeco, and retail replacement costs.
"""

# ── Pass 1: Identification + retail anchor (no derived pricing) ──────────────
IDENTIFICATION_PROMPT = """
You are analyzing a room photograph to build a home inventory. Your job in this pass:
  1. Identify every item of value.
  2. Assess condition and estimate dimensions.
  3. Provide a single retail anchor price (retail_usd) per item.

The pricing engine will derive all other price fields from your retail_usd; you do NOT need
to compute resale ranges, insurance values, or depreciation — just supply retail_usd.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — VISUAL REASONING (3–5 sentences before the JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
a) Room type and overall price tier (budget / mid-range / luxury / designer)
b) Scale anchors you will use (door height ≈ 80 in, ceiling ≈ 96–108 in)
c) Lighting quality and how it limits identification

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — ITEM IDENTIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Identify all movable objects of potential value. Be EXHAUSTIVE.
EXCLUDE fixed architectural elements (walls, floors, built-ins that require renovation to remove).
INCLUDE: furniture, electronics, appliances, art, lamps, rugs, mirrors, plants, instruments,
sports equipment, collectibles, individual books/media if spines are readable.

CATEGORY — use ONLY:
  "Furniture > Seating" | "Furniture > Tables" | "Furniture > Storage"
  "Furniture > Beds"    | "Furniture > Office"
  "Electronics > Entertainment" | "Electronics > Computing" | "Electronics > Audio" | "Electronics > Photography"
  "Appliances > Kitchen" | "Appliances > Laundry" | "Appliances > Climate"
  "Decor > Art" | "Decor > Rugs" | "Decor > Mirrors" | "Decor > Lighting" | "Decor > Plants" | "Decor > Objects"
  "Media > Books" | "Media > Music" | "Media > Games"
  "Instruments > Strings" | "Instruments > Keys" | "Instruments > Other"
  "Sports & Fitness > Gym" | "Sports & Fitness > Outdoor"

QUANTITY & SETS: multiple identical items → one entry with quantity > 1 and is_set: true if paired.
Do NOT group distinct items generically. List them individually.

BRAND/MODEL: scan logos, text, badges, design signatures. Prefix uncertain identifications
with "likely" or "possibly". Use "Unknown" / "Unidentified — [description]" if unsure.

AGE: infer from design era, technology generation, wear. Be specific ("2–4 years", "10–15 years").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — CONDITION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use ONLY: Excellent | Good | Fair | Poor | Damaged
Cite specific visual evidence in condition_notes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — RETAIL ANCHOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
retail_usd: INTEGER — the new retail price (per unit) to buy this item today.
Anchor to a specific current retailer (Amazon, Wayfair, brand website, IKEA, etc.).
For discontinued items use the closest current equivalent.
Do NOT include symbols, ranges, or strings — just an integer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — DIMENSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Format: "W × D × H in inches" for furniture; "diagonal inches" for screens; "W × L in feet" for rugs.
Use standard door height (80 in) and ceiling height (96–108 in) as scale anchors.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After the Step 1 reasoning block, return ONLY a valid JSON array:

[
  {
    "name": "string",
    "category": "string (Main Category > Subcategory)",
    "make": "string",
    "model": "string",
    "quantity": 1,
    "is_set": false,
    "estimated_age_years": "string (e.g. '2–4 years', 'Pre-2000 vintage')",
    "condition": "string (Excellent | Good | Fair | Poor | Damaged)",
    "condition_notes": "string (specific visual evidence)",
    "estimated_dimensions": "string",
    "retail_usd": 0,
    "confidence_score": 75,
    "identification_basis": "string (what visual evidence confirmed the identification)",
    "suggested_replacements": "string (1–3 modern alternatives)",
    "bounding_box": [0, 0, 0, 0]
  }
]

BOUNDING BOX: normalized coordinates 0–1000. Wrap tightly around the item.
CONFIDENCE: 90–100 = brand+model confirmed; 70–89 = brand confirmed, model inferred;
            50–69 = generic identification; below 50 = best guess.
"""

# ── Single-item analysis (thumbnail/crop flow) ────────────────────────────────
SINGLE_ITEM_PROMPT = """
Analyze this image and identify the main object using expert appraisal knowledge.

Provide accurate identification (name, brand, model) based on visible logos, design
signatures, and style cues. Assess condition with specific visual evidence.
Provide a single retail_usd integer (new retail price today).

Return ONLY a valid JSON object:
{
  "name": "string",
  "category": "string (Main Category > Subcategory)",
  "make": "string",
  "model": "string",
  "quantity": 1,
  "condition": "string (Excellent | Good | Fair | Poor | Damaged)",
  "condition_notes": "string",
  "estimated_dimensions": "string",
  "retail_usd": 0,
  "confidence_score": 75,
  "suggested_replacements": "string"
}
"""

# ── Resale listing (text-only, benefits from Pro reasoning) ───────────────────
RESALE_LISTING_PROMPT = """
You are an expert sales copywriter for high-end online marketplaces like eBay, Facebook Marketplace,
Chairish, and AptDeco. Create a compelling, professional listing that maximises the item's appeal.

Item Data:
- Name: {name}
- Category: {category}
- Make: {make}
- Model: {model}
- Condition: {condition}
- Condition Notes: {condition_notes}
- Dimensions: {dimensions}
- Resale Value: {resale_value}
- Retail Replacement: {retail_replacement}
- Age: {age}
- Room Context: {room}
- Price Basis: {price_basis}

Create a listing with:
1. A catchy, SEO-optimised title (max 80 characters)
2. A detailed description with feature highlights, condition details, and value proposition
3. A pricing recommendation with a "Buy Now" price and a "Make Offer" floor price
4. Platform-specific tags for maximum visibility

Return ONLY as JSON:
{{
  "listing_title": "string",
  "listing_description": "string",
  "buy_now_price": "string",
  "offer_floor_price": "string",
  "suggested_tags": ["string"],
  "best_platform": "string (eBay | Facebook Marketplace | Chairish | AptDeco | OfferUp)"
}}
"""


# ═══════════════════════════════════════════════════════════════
# CORE API CALL
# ═══════════════════════════════════════════════════════════════

def _call_gemini(
    prompt,
    image=None,
    temperature: float = 0.0,
    max_retries: int = 3,
    model_override: str | None = None,
    response_schema=None,
):
    """
    Core Gemini API call with exponential-backoff retry.
    Records token counts and cost via record_ai_call_stat() after each call.
    Pass response_schema to enforce structured output at the model level.
    """
    active_model = model_override or MODEL_ID
    contents = [SYSTEM_PROMPT, prompt]
    if image:
        contents.append(image)

    config: dict = {
        "temperature": temperature,
        "top_k": 1,
        "top_p": 0.1,
        "response_mime_type": "application/json",
        "seed": 42,
    }
    if response_schema is not None:
        config["response_schema"] = response_schema

    for attempt in range(max_retries):
        try:
            call_start = time.time()
            response = client.models.generate_content(
                model=active_model,
                contents=contents,
                config=config,
            )
            latency_ms = (time.time() - call_start) * 1000

            usage = getattr(response, "usage_metadata", None)
            if usage:
                record_ai_call_stat(
                    model=active_model,
                    input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                    latency_ms=latency_ms,
                )

            return response.text

        except genai.errors.ClientError as e:
            is_rate_limit = getattr(e, "code", None) in (429, 503) or any(
                c in str(e) for c in ("429", "503")
            )
            if is_rate_limit and attempt < max_retries - 1:
                wait = min(2 ** attempt * 5, 60) + random.uniform(0, 2)
                log.warning("gemini_rate_limit", model=active_model, attempt=attempt + 1, retry_in_s=round(wait, 1))
                time.sleep(wait)
            elif is_rate_limit:
                log.error("gemini_retries_exhausted", model=active_model, error=str(e))
                return "API_UNAVAILABLE" if "503" in str(e) else "QUOTA_EXHAUSTED"
            else:
                log.error("gemini_client_error", model=active_model, error=str(e))
                traceback.print_exc()
                return f"SCAN_ERROR: {e}"

        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(k in err_str for k in ("429", "503", "resource has been exhausted", "quota", "unavailable"))
            if is_rate_limit and attempt < max_retries - 1:
                wait = min(2 ** attempt * 5, 60) + random.uniform(0, 2)
                log.warning("gemini_rate_limit", model=active_model, attempt=attempt + 1, retry_in_s=round(wait, 1))
                time.sleep(wait)
            elif is_rate_limit:
                log.error("gemini_retries_exhausted", model=active_model)
                return "API_UNAVAILABLE" if "503" in err_str else "QUOTA_EXHAUSTED"
            else:
                log.error("gemini_unexpected_error", model=active_model, error=str(e))
                traceback.print_exc()
                return f"SCAN_ERROR: {e}"


# ═══════════════════════════════════════════════════════════════
# PRICING ENGINE HELPERS
# ═══════════════════════════════════════════════════════════════

def _extract_retail(item: dict) -> float:
    """
    Pull a retail USD anchor from an AI item dict.
    Priority: retail_usd (Pass 1 field) → retail_replacement_usd → fallback from estimated_price_usd.
    """
    raw = item.get("retail_usd")
    if raw:
        return parse_price(raw)

    retail_str = item.get("retail_replacement_usd", "")
    if retail_str:
        return parse_price(retail_str)

    # Reverse-engineer retail from resale midpoint using depreciation rate
    resale_mid = parse_price(item.get("estimated_price_usd", 0))
    if resale_mid > 0:
        from schemas import dep_key, DEPRECIATION_TABLE
        dk = dep_key(item.get("category", ""), item.get("make", ""))
        cond = item.get("condition", "Good")
        rates = DEPRECIATION_TABLE.get(dk, DEPRECIATION_TABLE["Furniture (mass)"])
        dep_rate = rates.get(cond, rates.get("Good", 0.35))
        return resale_mid / dep_rate if dep_rate > 0 else resale_mid * 2

    return 0.0


def _validate_item(raw: dict) -> dict:
    """
    1. Extract retail anchor from AI output.
    2. Run pricing engine to compute all price fields deterministically.
    3. Validate the merged result with ScannedItem (Pydantic).
    Returns a plain dict safe for JSON serialisation.
    """
    retail = _extract_retail(raw)

    if retail > 0:
        prices = compute_prices(
            retail_usd=retail,
            category=raw.get("category", ""),
            condition=raw.get("condition", "Good"),
            quantity=int(raw.get("quantity") or 1),
            make=raw.get("make", ""),
            estimated_age_years=raw.get("estimated_age_years"),
        )
        raw.update(prices)

    return ScannedItem(**raw).to_api_dict()


# ═══════════════════════════════════════════════════════════════
# IMAGE PREPROCESSING
# ═══════════════════════════════════════════════════════════════

_MAX_SIDE = 1536   # Gemini's optimal input resolution


def _preprocess_image(image_path: str) -> Image.Image:
    """
    Prepare an image for Gemini before the API call:
      1. Convert to RGB (drops alpha, normalises palette images).
      2. Resize so the longest side is ≤ 1536 px — Gemini's sweet spot for
         spatial reasoning; larger images are silently downscaled server-side
         and lose detail in the process.
      3. Auto-contrast: stretches the histogram to the full 0-255 range,
         recovering washed-out or underexposed shots.
      4. Unsharp mask: recovers fine text and edge detail lost by JPEG
         compression or camera shake.
    Falls back to the raw image if any step raises an exception.
    """
    try:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size

        if max(w, h) > _MAX_SIDE:
            scale = _MAX_SIDE / max(w, h)
            img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
            log.debug("image_resized", original=(w, h), new=img.size)

        img = ImageOps.autocontrast(img, cutoff=0.5)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=150, threshold=3))

        log.debug("image_preprocessed", path=image_path, size=img.size)
        return img
    except Exception as e:
        log.warning("image_preprocess_failed", path=image_path, error=str(e))
        return Image.open(image_path)


# ═══════════════════════════════════════════════════════════════
# LOW-CONFIDENCE RETRY
# ═══════════════════════════════════════════════════════════════

RETRY_CONFIDENCE_THRESHOLD = 70  # items below this score get a focused crop re-scan
_MAX_RETRIES_PER_SCAN = 5        # cap to bound added latency


def _crop_for_retry(image_path: str, bounding_box: list, tmp_dir: str) -> str | None:
    """
    Crop the bounding-box region from the original image and write it to tmp_dir.
    Uses 20% padding so the item isn't flush against the crop edge.
    Returns the crop file path, or None if the box is degenerate.
    """
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            b0, b1, b2, b3 = bounding_box
            ymin, ymax = sorted([b0, b2])
            xmin, xmax = sorted([b1, b3])

            left   = (xmin / 1000) * w
            top    = (ymin / 1000) * h
            right  = (xmax / 1000) * w
            bottom = (ymax / 1000) * h

            pad_x = (right - left) * 0.20
            pad_y = (bottom - top) * 0.20
            crop_left   = max(0, left - pad_x)
            crop_top    = max(0, top - pad_y)
            crop_right  = min(w, right + pad_x)
            crop_bottom = min(h, bottom + pad_y)

            if crop_right <= crop_left or crop_bottom <= crop_top:
                return None

            crop = img.crop((crop_left, crop_top, crop_right, crop_bottom)).convert("RGB")
            path = os.path.join(tmp_dir, f"retry_{uuid.uuid4().hex[:8]}.jpg")
            crop.save(path, quality=90)
            return path
    except Exception as e:
        log.warning("crop_for_retry_failed", error=str(e))
        return None


def _run_single_item_analysis(image: Image.Image) -> dict | None:
    """
    Focused single-item Gemini call used by the retry path.
    Bypasses the @observe_ai_call decorator so token costs are still recorded
    by record_ai_call_stat() inside _call_gemini but don't create a nested span.
    Returns the raw dict from Gemini, or None on any failure.
    """
    result = _call_gemini(
        SINGLE_ITEM_PROMPT, image=image,
        model_override=VISION_MODEL, response_schema=_GeminiItem,
    )
    if not result or result in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE") or result.startswith("SCAN_ERROR"):
        return None
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return None


def _retry_low_confidence_items(image_path: str, items: list[dict]) -> list[dict]:
    """
    For each item whose confidence_score < RETRY_CONFIDENCE_THRESHOLD and that
    has a non-zero bounding_box, crop the region and re-analyze with a focused
    single-item call.  If the retry returns a higher confidence the item is
    replaced; the original bounding_box is always preserved (it was set in the
    full-room context and is more spatially accurate).
    Capped at _MAX_RETRIES_PER_SCAN items to bound added latency.
    """
    def _conf(item: dict) -> int:
        raw = item.get("confidence_score", 0)
        if isinstance(raw, str):
            try:
                return int(raw.replace("%", "").strip())
            except (ValueError, TypeError):
                return 0
        return int(raw) if raw else 0

    candidates = [
        i for i, it in enumerate(items)
        if _conf(it) < RETRY_CONFIDENCE_THRESHOLD
        and (box := it.get("bounding_box"))
        and isinstance(box, list) and len(box) == 4
        and box != [0, 0, 0, 0]
    ][:_MAX_RETRIES_PER_SCAN]

    if not candidates:
        return items

    log.info("retry_start", candidates=len(candidates))

    with tempfile.TemporaryDirectory(prefix="holos_retry_") as tmp_dir:
        for idx in candidates:
            item = items[idx]
            original_conf = _conf(item)
            original_box  = item.get("bounding_box")

            crop_path = _crop_for_retry(image_path, original_box, tmp_dir)
            if not crop_path:
                continue

            try:
                crop_img  = _preprocess_image(crop_path)
                retry_raw = _run_single_item_analysis(crop_img)
                if not retry_raw:
                    continue

                retry_conf = _conf(retry_raw)
                if retry_conf <= original_conf:
                    log.debug("retry_no_improvement", name=item.get("name"),
                              original_conf=original_conf, retry_conf=retry_conf)
                    continue

                # Validate and run pricing engine on the retry result
                try:
                    merged = _validate_item(retry_raw)
                except Exception:
                    merged = retry_raw

                # Re-attach fields that belong to the scan context, not the item crop
                for key in ("original_image_url", "home_name", "room_name",
                            "thumbnail_url", "thumbnail_source",
                            "id", "auto_saved", "_source_frame", "_source_timestamp"):
                    if key in item:
                        merged[key] = item[key]

                merged["bounding_box"] = original_box
                merged["_retry"] = True
                items[idx] = merged

                log.info("retry_improved", name=item.get("name"),
                         original_conf=original_conf, retry_conf=retry_conf)
            except Exception as e:
                log.warning("retry_failed", name=item.get("name"), error=str(e))

    return items


# ═══════════════════════════════════════════════════════════════
# PUBLIC AI FUNCTIONS
# ═══════════════════════════════════════════════════════════════

@observe_ai_call(VISION_MODEL, agent="2")
def analyze_room(image_path: str, user_notes: str | None = None) -> str:
    """
    Two-pass room analysis.
    Pass 1 (VISION_MODEL): identify items + retail_usd anchor per item.
    Pricing engine: compute all price fields deterministically from retail_usd.
    Returns a validated JSON array (list[ScannedItem]).
    """
    log.info("analyze_room_start", image_path=image_path, has_user_notes=bool(user_notes))

    prompt = IDENTIFICATION_PROMPT
    if user_notes:
        log.debug("injecting_user_notes", preview=user_notes[:80])
        prompt += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nUSER PROVIDED NOTES\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"The user provided: '{user_notes}'. Incorporate this into identification, "
            f"age estimation, and your retail_usd anchor."
        )

    image = _preprocess_image(image_path)
    result = _call_gemini(
        prompt, image=image, temperature=0.0, model_override=VISION_MODEL,
        response_schema=list[_GeminiItem],
    )

    if not result or result in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE") or result.startswith("SCAN_ERROR"):
        log.error("analyze_room_failed", status=result)
        return result

    try:
        raw_items = json.loads(result)
    except json.JSONDecodeError as e:
        log.error("analyze_room_json_parse_failed", error=str(e), raw_preview=result[:200])
        return f"SCAN_ERROR: JSON parse failed — {e}"

    if not isinstance(raw_items, list):
        raw_items = [raw_items]

    enriched: list[dict] = []
    for raw in raw_items:
        try:
            enriched.append(_validate_item(raw))
        except Exception as e:
            log.warning("item_validation_failed", name=raw.get("name"), error=str(e))
            raw["_validation_failed"] = True
            raw["confidence_score"] = 0
            raw["review_reason"] = f"Schema validation failed: {str(e)[:120]}"
            enriched.append(raw)

    enriched = _retry_low_confidence_items(image_path, enriched)

    log.info("analyze_room_complete", item_count=len(enriched))
    return json.dumps(enriched)


@observe_ai_call(VISION_MODEL, agent="2")
def analyze_item(image_path: str) -> str:
    """Analyses a single prominent item in an image. Returns a validated JSON object."""
    log.info("analyze_item_start", image_path=image_path)
    image = _preprocess_image(image_path)
    result = _call_gemini(
        SINGLE_ITEM_PROMPT, image=image, model_override=VISION_MODEL,
        response_schema=_GeminiItem,
    )

    if not result or result.startswith("SCAN_ERROR"):
        return result

    try:
        raw = json.loads(result)
        validated = _validate_item(raw)
        return json.dumps(validated)
    except Exception as e:
        log.warning("analyze_item_validation_failed", error=str(e))
        return result


@observe_ai_call(PRICING_MODEL, agent="2")
def generate_resale_listing(item_data: dict) -> str:
    """Generates a professional marketplace listing via AI. Returns validated JSON."""
    name = item_data.get("name", "Unknown Item")
    log.info("generate_resale_listing_start", item_name=name)

    prompt = RESALE_LISTING_PROMPT.format(
        name=name,
        category=item_data.get("category", "General"),
        make=item_data.get("make", "Unknown"),
        model=item_data.get("model", "Unidentified"),
        condition=item_data.get("condition", "Good"),
        condition_notes=item_data.get("condition_notes", "No notes available"),
        dimensions=item_data.get("estimated_dimensions", "Not specified"),
        resale_value=item_data.get("resale_value_usd", item_data.get("estimated_price_usd", "N/A")),
        retail_replacement=item_data.get("retail_replacement_usd", "N/A"),
        age=item_data.get("estimated_age_years", "Unknown"),
        room=item_data.get("room_name", "General Room"),
        price_basis=item_data.get("price_basis", "Market estimate"),
    )

    result = _call_gemini(prompt, temperature=0.7, model_override=PRICING_MODEL)

    if not result or result.startswith("SCAN_ERROR"):
        return result

    try:
        raw = json.loads(result.strip().replace("```json", "").replace("```", "").strip())
        validated = ResaleListing(**raw)
        return json.dumps(validated.model_dump())
    except Exception as e:
        log.warning("resale_listing_validation_failed", error=str(e))
        return result


def refine_bounding_box(image_path: str, item_name: str) -> str | None:
    """Provides high-precision bounding box for a specific zoomed-in item."""
    log.info("refine_bounding_box", item_name=item_name)

    prompt = f"""
    You are an expert image editor. The provided image is a zoomed-in crop of a '{item_name}'.
    Provide the MOST PRECISE bounding box that strictly contains the '{item_name}' — no background,
    no adjacent objects.

    Return ONLY a JSON object:
    {{"refined_bounding_box": [ymin, xmin, ymax, xmax]}}
    Use normalized coordinates (0–1000) based on THIS zoomed image.
    """

    try:
        call_start = time.time()
        with Image.open(image_path) as image:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt, image],
                config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
        latency_ms = (time.time() - call_start) * 1000
        usage = getattr(response, "usage_metadata", None)
        if usage:
            record_ai_call_stat(
                model=MODEL_ID,
                input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                latency_ms=latency_ms,
            )
        return response.text
    except Exception as e:
        log.error("refine_bounding_box_error", item_name=item_name, error=str(e))
        return None


# ═══════════════════════════════════════════════════════════════
# CLI TESTING
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    log.info("scanner_test_mode", model=MODEL_ID)

    if len(sys.argv) > 1:
        test_image = sys.argv[1]
        log.info("running_room_analysis", image=test_image)
        result = analyze_room(test_image)
        try:
            parsed = json.loads(result)
            print(json.dumps(parsed, indent=2))
            total = sum(
                item.get("estimated_price_usd", 0)
                for item in parsed
                if isinstance(item.get("estimated_price_usd"), (int, float))
            )
            log.info("test_complete", item_count=len(parsed), total_value_usd=total)
        except json.JSONDecodeError:
            log.error("json_parse_failed", raw_output=result[:200])
    else:
        log.info("usage", hint="python scanner.py <image_path>")
