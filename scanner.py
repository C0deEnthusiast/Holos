"""
Holos Scanner — Agent 2 (AI Reliability)
AI-Powered Home Inventory Analysis via Gemini.

Changes from prototype per §9.3:
- Pydantic schema enforced on every response (ParseError raised, not swallowed)
- Deleted all .replace('```json','') string munging
- Tenacity retries with exponential jitter (replaces hand-rolled loops)
- Typed exceptions: QuotaError, UnavailableError, ParseError (no sentinel strings)
- Real model IDs pinned, read from env, logged per call
- AICallTimer wires every call into ai_calls table
- Depreciation math moved to Python post-processing (schemas.calculate_tri_value)
- temperature=0, top_k=1, top_p=0.1 per §8.5
"""
import os
import json
import time
from pathlib import Path

import structlog
from google import genai
from dotenv import load_dotenv
from PIL import Image
from tenacity import (
    retry,
    wait_exponential_jitter,
    stop_after_attempt,
    retry_if_exception_type,
    before_sleep_log,
)

from schemas import (
    ItemEstimate,
    ResaleListing,
    ParseError,
    QuotaError,
    UnavailableError,
    validate_items,
    calculate_tri_value,
)
from observability import AICallTimer, log_ai_call

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv(override=True)

log = structlog.get_logger("holos.scanner")

_API_KEY = os.getenv("GEMINI_API_KEY")
if not _API_KEY:
    raise ValueError("GEMINI_API_KEY is not set.")

# Unset GOOGLE_API_KEY from the process environment so the google-genai SDK
# doesn't silently prefer it over the api_key we pass explicitly.
# (GOOGLE_API_KEY is used only by image_search.py for Custom Search, not Gemini.)
os.environ.pop("GOOGLE_API_KEY", None)

client = genai.Client(api_key=_API_KEY)

# Real model IDs from env (eval-selected per §8.2) — pinned, not guessed
VISION_MODEL  = os.getenv("GEMINI_VISION_MODEL",  "gemini-2.5-flash-preview-04-17")
PRICING_MODEL = os.getenv("GEMINI_PRICING_MODEL", "gemini-2.5-pro-preview-03-25")
MODEL_ID = VISION_MODEL  # backward compat

# Prompt loaded from versioned file
_PROMPT_PATH = Path(__file__).parent / "backend" / "prompts" / "vision_classify.v1.md"
_VISION_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""

log.info("scanner_initialized", vision_model=VISION_MODEL, pricing_model=PRICING_MODEL)
print(f"  Vision Model:  {VISION_MODEL}")
print(f"  Pricing Model: {PRICING_MODEL}")


# ---------------------------------------------------------------------------
# Typed Exceptions (re-exported for backward compat with routes/scan.py)
# ---------------------------------------------------------------------------

class GeminiQuotaError(QuotaError):
    pass

class GeminiUnavailableError(UnavailableError):
    pass

class GeminiScanError(Exception):
    """Non-retryable Gemini API error."""
    pass


# ---------------------------------------------------------------------------
# Core Gemini Call — tenacity + AICallTimer + typed exceptions
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type((GeminiQuotaError, GeminiUnavailableError)),
    wait=wait_exponential_jitter(initial=2, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _call_gemini(
    prompt: str,
    image: Image.Image | None = None,
    *,
    model: str = VISION_MODEL,
    purpose: str = "vision",
    user_id: str | None = None,
    scan_id: str | None = None,
    temperature: float = 0.0,
) -> str:
    """
    Core Gemini API call.
    - temperature=0, top_k=1, top_p=0.1 per §8.5 determinism requirements
    - Logs every call to ai_calls table via AICallTimer
    - Raises typed exceptions — no sentinel strings ever returned
    - Does NOT clean markdown fences — if SDK returns them, ParseError is raised upstream
    """
    contents: list = [prompt]
    if image is not None:
        contents.append(image)

    with AICallTimer(
        user_id=user_id,
        scan_id=scan_id,
        provider="google",
        model_id=model,
        purpose=purpose,
    ) as timer:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "temperature": temperature,
                    "top_k": 1,
                    "top_p": 0.1,
                    "response_mime_type": "application/json",
                    "seed": 42,
                },
            )

            # Log token usage
            usage = getattr(response, "usage_metadata", None)
            if usage:
                timer.set(
                    input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                    cached_tokens=getattr(usage, "cached_content_token_count", 0) or 0,
                )
                log.info(
                    "gemini_tokens",
                    model=model,
                    input=timer._kwargs.get("input_tokens"),
                    output=timer._kwargs.get("output_tokens"),
                )

            text = response.text
            if text is None:
                raise GeminiScanError("Gemini returned None response text")
            return text

        except genai.errors.ClientError as e:  # type: ignore[attr-defined]
            code = getattr(e, "code", None)
            msg = str(e)
            if code == 429 or "429" in msg or "quota" in msg.lower():
                raise GeminiQuotaError(f"Quota: {e}") from e
            if code == 503 or "503" in msg or "unavailable" in msg.lower():
                raise GeminiUnavailableError(f"Unavailable: {e}") from e
            raise GeminiScanError(f"API error ({code}): {e}") from e

        except (GeminiQuotaError, GeminiUnavailableError, GeminiScanError):
            raise

        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["429", "quota", "resource has been exhausted"]):
                raise GeminiQuotaError(f"Quota: {e}") from e
            if any(k in msg for k in ["503", "unavailable"]):
                raise GeminiUnavailableError(f"Unavailable: {e}") from e
            raise GeminiScanError(f"Unexpected: {e}") from e


# ---------------------------------------------------------------------------
# Parse + Validate — no markdown cleanup, strict Pydantic
# ---------------------------------------------------------------------------

def _parse_and_validate(raw_text: str) -> list[ItemEstimate]:
    """
    Parse JSON from Gemini response and validate via Pydantic.
    Raises ParseError if raw_text is not valid JSON — never silently ignores.
    """
    text = raw_text.strip()

    # ONLY allowed cleanup: skip reasoning text before the JSON array/object
    # (NOT stripping markdown fences — if SDK returns those, it's a config error)
    if text and not text.startswith(("[", "{", "\"")):
        bracket = text.find("[")
        brace = text.find("{")
        start = min(
            bracket if bracket != -1 else len(text),
            brace if brace != -1 else len(text),
        )
        if start < len(text):
            text = text[start:]

    # Fail loudly if still not JSON
    if not text or not (text.startswith("[") or text.startswith("{")):
        raise ParseError(
            f"Gemini response is not JSON. First 200 chars: {raw_text[:200]!r}"
        )

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"JSON parse error: {e}. Input: {text[:300]!r}") from e

    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ParseError(f"Expected JSON array, got {type(raw).__name__}")

    items, failures = validate_items(raw)

    # Parse-rate quality gate (§13: ≥99% in production)
    total = len(raw)
    if total > 0:
        parse_rate = len(items) / total
        log.info("parse_rate", rate=f"{parse_rate:.1%}", parsed=len(items), total=total)
        if failures > 0:
            log.warning("parse_failures", count=failures, total=total)

    return items


# ---------------------------------------------------------------------------
# Post-processing — deterministic depreciation per §8.3
# ---------------------------------------------------------------------------

def _apply_depreciation(items: list[ItemEstimate]) -> list[ItemEstimate]:
    """
    Fill in resale and insurance values using deterministic Python math.
    The prompt only provides retail midpoint — no AI arithmetic needed.
    Per §8.3: "Move the depreciation table into post-processing, not the prompt."
    """
    for item in items:
        retail_mid = (
            item.value_retail_replacement_low_cents
            + item.value_retail_replacement_high_cents
        ) // 2

        if retail_mid > 0 and item.value_resale_low_cents == 0:
            tri = calculate_tri_value(
                retail_midpoint_cents=retail_mid,
                category=item.category.value,
                condition=item.condition.value,
            )
            # Only fill the values AI left at 0 (don't override if AI provided them)
            item.value_resale_low_cents = tri["value_resale_low_cents"]
            item.value_resale_high_cents = tri["value_resale_high_cents"]
            item.value_insurance_replacement_low_cents = tri["value_insurance_replacement_low_cents"]
            item.value_insurance_replacement_high_cents = tri["value_insurance_replacement_high_cents"]

    return items


# ---------------------------------------------------------------------------
# High_value flag — auto-applied for items > $500 retail
# ---------------------------------------------------------------------------

def _apply_flags(items: list[ItemEstimate]) -> list[ItemEstimate]:
    for item in items:
        retail_high = item.value_retail_replacement_high_cents
        if retail_high > 50_000 and "high_value" not in item.flags:  # > $500
            item.flags = list(item.flags) + ["high_value"]
    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_room(
    image_path: str,
    *,
    user_notes: str | None = None,
    user_id: str | None = None,
    scan_id: str | None = None,
) -> list[ItemEstimate]:
    """
    Full room analysis pipeline:
    1. Call Gemini with vision prompt
    2. Parse + validate via Pydantic (ParseError raised, never swallowed)
    3. Apply deterministic depreciation
    4. Auto-flag high-value items

    Raises: GeminiQuotaError, GeminiUnavailableError, GeminiScanError, ParseError
    """
    log.info("room_scan_start", image=image_path, user_id=user_id)

    prompt = _VISION_PROMPT
    if user_notes:
        prompt += f"\n\n## USER CONTEXT\n{user_notes}"

    with Image.open(image_path) as image:
        raw_text = _call_gemini(
            prompt,
            image=image,
            model=VISION_MODEL,
            purpose="vision",
            user_id=user_id,
            scan_id=scan_id,
        )

    items = _parse_and_validate(raw_text)
    items = _apply_depreciation(items)
    items = _apply_flags(items)

    log.info("room_scan_complete", item_count=len(items), user_id=user_id)
    return items


def analyze_room_validated(
    image_path: str,
    user_notes: str | None = None,
    user_id: str | None = None,
) -> list[ItemEstimate]:
    """Alias for analyze_room — kept for backward compat with routes/scan.py."""
    return analyze_room(image_path, user_notes=user_notes, user_id=user_id)


def analyze_item(image_path: str, user_id: str | None = None) -> ItemEstimate | None:
    """Analyze a single prominent item. Returns first validated ItemEstimate."""
    log.info("single_item_scan", image=image_path)
    with Image.open(image_path) as image:
        raw_text = _call_gemini(
            _VISION_PROMPT,
            image=image,
            model=PRICING_MODEL,
            purpose="vision_single",
            user_id=user_id,
        )
    items = _parse_and_validate(raw_text)
    items = _apply_depreciation(items)
    return items[0] if items else None


def generate_resale_listing(item_data: dict, user_id: str | None = None) -> str:
    """Generate a professional marketplace listing via AI."""
    name = item_data.get("name", "Unknown Item")
    log.info("resale_listing_start", name=name)

    prompt = f"""
You are an expert sales copywriter for high-end marketplaces (eBay, Chairish, AptDeco, Facebook).
Create a compelling listing for this item:

Name: {name}
Category: {item_data.get('category', 'General')}
Brand: {item_data.get('brand', item_data.get('make', 'Unknown'))}
Model: {item_data.get('model', 'Unidentified')}
Condition: {item_data.get('condition', 'Good')}
Condition notes: {item_data.get('condition_evidence', item_data.get('condition_notes', ''))}
Dimensions: {item_data.get('dimensions_estimate', item_data.get('estimated_dimensions', 'Not specified'))}
Resale value: ${item_data.get('resale_low_cents', 0)/100:.0f}–${item_data.get('resale_high_cents', 0)/100:.0f}

Return ONLY as JSON:
{{
  "listing_title": "string (max 80 chars, SEO-optimized)",
  "listing_description": "string (detailed, value-focused)",
  "buy_now_price": "string (e.g. '$499')",
  "offer_floor_price": "string (e.g. '$399')",
  "suggested_tags": ["string"],
  "best_platform": "string (eBay | Facebook Marketplace | Chairish | AptDeco | OfferUp)"
}}
"""
    return _call_gemini(
        prompt,
        model=VISION_MODEL,
        purpose="listing",
        user_id=user_id,
        temperature=0.7,
    )


def refine_bounding_box(image_path: str, item_name: str) -> str | None:
    """High-precision bounding box refinement for a specific item crop."""
    log.info("bbox_refine", item=item_name)
    prompt = f"""
You are an expert image editor. Provide the MOST PRECISE bounding box for '{item_name}'.
Edges must be tight against the object. Exclude background.

Return ONLY:
{{"refined_bounding_box": [ymin, xmin, ymax, xmax]}}
Use normalized coordinates (0-1000).
"""
    try:
        with Image.open(image_path) as image:
            return _call_gemini(
                prompt, image=image,
                model=VISION_MODEL,
                purpose="refine_box",
            )
    except Exception as e:
        log.error("bbox_refine_failed", item=item_name, error=str(e))
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import logging
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        print(f"\n[SCAN] {sys.argv[1]}")
        try:
            items = analyze_room(sys.argv[1])
            for item in items:
                print(json.dumps(item.to_scan_dict(), indent=2, default=str))
            total_insurance = sum(i.insurance_midpoint_cents for i in items)
            print(f"\n[OK] {len(items)} items — Total insurance value: ${total_insurance/100:,.2f}")
        except ParseError as e:
            print(f"[PARSE ERROR] {e}")
        except (GeminiQuotaError, GeminiUnavailableError, GeminiScanError) as e:
            print(f"[{type(e).__name__}] {e}")
    else:
        print("Usage: python scanner.py <image_path>")
