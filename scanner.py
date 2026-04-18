"""
Holos Scanner — AI-Powered Home Inventory Analysis
Uses Gemini to identify, value, and catalog items from room photographs.
"""

import os
import json
from google import genai
from dotenv import load_dotenv
from PIL import Image
import traceback
import time

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")

client = genai.Client(api_key=API_KEY)

# Dual-Model Architecture:
# VISION_MODEL  = Gemini 3 Flash  — fast image analysis, item identification
# PRICING_MODEL = Gemini 2.5 Pro  — analytical, consistent pricing
VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3-flash-preview")
PRICING_MODEL = os.getenv("GEMINI_PRICING_MODEL", "gemini-2.5-pro")
MODEL_ID = VISION_MODEL  # backward compat

print(f"  Vision Model:  {VISION_MODEL}")
print(f"  Pricing Model: {PRICING_MODEL}")


# ═══════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
You are an expert home appraiser and certified personal property valuator with 20 years of 
experience in furniture, electronics, fine art, collectibles, and appliances. You have deep 
knowledge of secondary markets including eBay sold listings, Facebook Marketplace, 1stDibs, 
Chairish, AptDeco, and retail replacement costs.
"""

ROOM_ANALYSIS_PROMPT = """
You are analyzing a room photograph to build a detailed home inventory with current market valuations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — VISUAL REASONING (do this BEFORE outputting JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before listing items, briefly reason through:
a) Room type (living room, bedroom, kitchen, office, etc.)
b) Overall style and price tier of the room (budget / mid-range / luxury / designer)
c) Visual anchor objects (doors, windows, standard-height ceilings ~8–9ft) you'll use to scale dimensions
d) Lighting quality and how it may affect your ability to identify brands or condition

Keep this reasoning block to 3–5 sentences. Then output the JSON array.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — ITEM IDENTIFICATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Identify all movable objects of potential value. It is CRITICAL to be EXHAUSTIVE. If there are dozens of items visible (e.g., 20+ books on a shelf, many collectibles, or distinct items), you MUST list EACH distinct item individually if they are identifiable. Do not group them generically like "Pile of Books".
EXCLUDE fixed architectural elements (walls, floors, ceilings, built-in cabinetry that cannot be removed without renovation, radiators, permanent fixtures).

INCLUDE: furniture, electronics, appliances, art, lighting fixtures (lamps, sconces), 
rugs, mirrors, plants (large statement plants), musical instruments, sports equipment, 
collectibles, EVERY single book/media item (if spines/covers are visible), decorative objects.

CATEGORY FORMAT — use ONLY this strict hierarchy:
  "Furniture > Seating"      | "Furniture > Tables"         | "Furniture > Storage"
  "Furniture > Beds"         | "Furniture > Office"         | "Electronics > Entertainment"
  "Electronics > Computing"  | "Electronics > Audio"        | "Electronics > Photography"
  "Appliances > Kitchen"     | "Appliances > Laundry"       | "Appliances > Climate"
  "Decor > Art"              | "Decor > Rugs"               | "Decor > Mirrors"
  "Decor > Lighting"         | "Decor > Plants"             | "Decor > Objects"
  "Media > Books"            | "Media > Music"              | "Media > Games"
  "Instruments > Strings"    | "Instruments > Keys"         | "Instruments > Other"
  "Sports & Fitness > Gym"   | "Sports & Fitness > Outdoor"

BRAND/MODEL DETECTION:
- Scan for visible logos, text, badges, labels, model numbers on screens or tags
- Cross-reference style signatures: Eames shell chairs have a distinctive silhouette, 
  Herman Miller Aeron has a unique mesh and lumbar paddle, IKEA KALLAX has a recognizable grid
- For TVs: screen bezel thickness and logo placement help identify brand/era
- If unsure, prefix model with "likely" or "possibly" (e.g., "likely Restoration Hardware")

QUANTITY & SETS:
- If multiple identical items exist (e.g., 6 dining chairs), return ONE entry with quantity > 1
- If items are a set (sofa + loveseat, nightstand pair), set is_set: true and list as one entry
- Do NOT group distinct items (e.g., different books, different games) into a single generic entry. List them individually if their details differ.
- All price fields reflect TOTAL value (unit price × quantity)
- Include unit_price_usd separately

AGE ESTIMATION:
- Infer age from: design era signals, technology visible (curved vs flat CRT vs LCD vs OLED), 
  wear patterns, style trends, visible finish aging
- Be specific: "2–4 years" not "recently purchased"
- Vintage/antique items (15+ years) should be noted, as they may appreciate rather than depreciate

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — CONDITION ASSESSMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use ONLY these five tiers. Cite specific visual evidence in condition_notes:
  "Excellent" — Like new, no visible wear, may still have tags/packaging context
  "Good"       — Light use, minor scuffs or surface marks, fully functional appearance
  "Fair"       — Moderate wear, visible fading/scratches/stains, structurally intact
  "Poor"       — Heavy wear, significant damage, missing parts, or severe fading
  "Damaged"    — Broken, torn, cracked, or non-functional visible state

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — PRICING (CRITICAL — MUST BE CONSISTENT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return THREE distinct price estimates for every item.

CONSISTENCY RULE — Follow this EXACT procedure to ensure repeatable prices:
  Step A: Determine retail_replacement_usd FIRST. This is an objective fact 
          (what it costs to buy new today). Anchor to a specific retailer/website.
  Step B: Calculate resale_value_usd by applying the DEPRECIATION TABLE below 
          to the retail price.
  Step C: Calculate insurance_replacement_usd = retail × 1.15 (standard 15% uplift 
          for delivery, installation, and sourcing).

DEPRECIATION TABLE (resale as % of retail, by category and condition):
┌──────────────────┬───────────┬─────┬──────┬──────┬─────────┐
│ Category         │ Excellent │ Good│ Fair │ Poor │ Damaged │
├──────────────────┼───────────┼─────┼──────┼──────┼─────────┤
│ Electronics      │    45%    │ 35% │ 20%  │ 10%  │   5%    │
│ Furniture (mass) │    55%    │ 40% │ 25%  │ 15%  │   5%    │
│ Furniture (desig)│    65%    │ 50% │ 35%  │ 20%  │  10%    │
│ Appliances       │    50%    │ 35% │ 20%  │ 10%  │   5%    │
│ Decor / Art      │    70%    │ 55% │ 35%  │ 20%  │  10%    │
│ Antiques (15+yr) │    90%    │ 80% │ 60%  │ 40%  │  20%    │
│ Instruments      │    65%    │ 50% │ 35%  │ 20%  │  10%    │
│ Media / Books    │    40%    │ 25% │ 15%  │  5%  │   2%    │
│ Sports / Fitness │    50%    │ 35% │ 20%  │ 10%  │   5%    │
└──────────────────┴───────────┴─────┴──────┴──────┴─────────┘
"Designer furniture" = Herman Miller, Restoration Hardware, Pottery Barn, West Elm, 
  Crate & Barrel, Ethan Allen, Room & Board, Arhaus, and similar premium brands.
"Mass furniture" = IKEA, Ashley, Rooms To Go, Walmart, Target, and unbranded.

PRICE RANGE WIDTH: Keep ranges tight (±15% of the midpoint). 
  Example: If midpoint is 500, range should be ~425–575, NOT 200–800.
  Wider ranges indicate uncertainty — flag with lower confidence_score.

PRICE FORMAT:
  - resale_value_usd: range string, e.g. "$425–$575" (LOWEST tier)
  - retail_replacement_usd: range string, e.g. "$900–$1,100" (MID tier)  
  - insurance_replacement_usd: range string, e.g. "$1,035–$1,265" (HIGHEST tier)
  - estimated_price_usd: integer ONLY, MIDPOINT of resale range (e.g. 500)

Include price_basis: 1–2 sentences explaining the retail anchor and depreciation applied.
Example: "Retail: IKEA KALLAX = 199. Good mass furniture = 40% resale → 80."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — DIMENSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Use standard door height (80 inches) and ceiling height (96–108 inches) as scale anchors
- Provide in format: "W × D × H in inches" for furniture; "diagonal inches" for screens; 
  "W × L in feet" for rugs
- For items with standard manufacturing sizes, use those: standard sofa = 84"W, 
  dining chair = 18"W × 20"D × 36"H, king bed = 76"W × 80"L
- REQUIRED for every item. Use "approximately" if estimating.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After your Step 1 reasoning block, return ONLY a valid JSON array:

[
  {
    "name": "string (real-world object name, never a filename)",
    "category": "string (Main Category > Subcategory from approved list)",
    "make": "string (brand/manufacturer or 'Unknown')",
    "model": "string (specific model or 'Unidentified — [description]')",
    "quantity": 1,
    "is_set": false,
    "estimated_age_years": "string (e.g. '2–4 years', '10–15 years', 'Pre-2000 vintage')",
    "condition": "string (Excellent | Good | Fair | Poor | Damaged)",
    "condition_notes": "string (specific visual evidence for condition rating)",
    "estimated_dimensions": "string (W × D × H in inches or other appropriate format)",
    "unit_price_usd": "string (price for ONE unit, e.g. '$200–$300')",
    "estimated_price_usd": 0,
    "resale_value_usd": "string (total resale range, e.g. '$800–$1,200')",
    "retail_replacement_usd": "string (total retail range)",
    "insurance_replacement_usd": "string (total insurance range)",
    "price_basis": "string (how prices were derived, 1–2 sentences)",
    "confidence_score": 75,
    "identification_basis": "string (what visual evidence confirmed the identification)",
    "suggested_replacements": "string (1–3 modern alternatives)",
    "bounding_box": [0, 0, 0, 0]
  }
]

BOUNDING BOX: normalized coordinates 0–1000. Wrap tightly around the visible item.
CONFIDENCE GUIDE: 90–100 = brand+model confirmed visually; 70–89 = brand confirmed, 
model inferred; 50–69 = generic identification, style-based; Below 50 = best guess, 
flag for human review.
"""

SINGLE_ITEM_PROMPT = """
Analyze this image and identify the main object using your expert appraisal knowledge.

Provide a detailed analysis including:
- Accurate identification (name, brand, model) based on visible logos, design signatures, and style cues
- Condition assessment with specific visual evidence
- Three-tier pricing: resale value, retail replacement, and insurance replacement
- Estimated dimensions using standard reference objects for scale

Return the response ONLY as a valid JSON object:
{
  "name": "string",
  "category": "string (Main Category > Subcategory)",
  "make": "string",
  "model": "string",
  "quantity": 1,
  "condition": "string (Excellent | Good | Fair | Poor | Damaged)",
  "condition_notes": "string",
  "estimated_dimensions": "string",
  "estimated_price_usd": 0,
  "resale_value_usd": "string",
  "retail_replacement_usd": "string",
  "insurance_replacement_usd": "string",
  "price_basis": "string",
  "confidence_score": 75,
  "suggested_replacements": "string"
}
"""

RESALE_LISTING_PROMPT = """
You are an expert sales copywriter for high-end online marketplaces like eBay, Facebook Marketplace,
Chairish, and AptDeco. Create a compelling, professional listing that maximizes the item's appeal.

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
1. A catchy, SEO-optimized title (max 80 characters)
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
# AI FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _call_gemini(prompt, image=None, temperature=0.0, max_retries=3, model_override=None):
    """Core Gemini API call with retry logic. Supports model override for dual-model pipeline."""
    active_model = model_override or MODEL_ID
    contents = [SYSTEM_PROMPT, prompt]
    if image:
        contents.append(image)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=active_model,
                contents=contents,
                config={
                    'temperature': 0.0,
                    'top_k': 1,
                    'top_p': 0.1,
                    'response_mime_type': 'application/json',
                    'seed': 42,
                }
            )
            return response.text
        except genai.errors.ClientError as e:
            if getattr(e, 'code', None) in (429, 503) or any(code in str(e) for code in ['429', '503']):
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 15
                    print(f"  [WAIT] Rate limit hit. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"  [X] Retries exhausted for {active_model}: {e}")
                    return "API_UNAVAILABLE" if '503' in str(e) else "QUOTA_EXHAUSTED"
            else:
                print(f"  [X] API error: {e}")
                traceback.print_exc()
                return f"SCAN_ERROR: {str(e)}"
        except Exception as e:
            if any(key in str(e).lower() for key in ["429", "503", "resource has been exhausted", "quota", "unavailable"]):
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 15
                    print(f"  [WAIT] Rate limit hit. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"  [X] Retries exhausted: {e}")
                    return "API_UNAVAILABLE" if "503" in str(e).lower() else "QUOTA_EXHAUSTED"
            else:
                print(f"  [X] Unexpected error: {e}")
                traceback.print_exc()
                return f"SCAN_ERROR: {str(e)}"


def analyze_item(image_path: str) -> str:
    """Analyzes a single prominent item in an image."""
    print(f"[SEARCH] Analyzing single item: {image_path}")
    with Image.open(image_path) as image:
        return _call_gemini(SINGLE_ITEM_PROMPT, image=image, model_override=PRICING_MODEL)


def analyze_room(image_path: str, user_notes: str = None) -> str:
    """Single-pass room analysis with strict analytical pricing using Gemini 2.5 Pro."""
    print(f"\n[ROOM] Scanning room: {image_path}")

    # ── Pass 1: Vision AND Pricing combined (Gemini 2.5 Pro) ──
    print(f"  [EYE] Pass 1: Visual identification and strict pricing via {PRICING_MODEL}...")
    
    prompt = ROOM_ANALYSIS_PROMPT
    if user_notes:
        print(f"  [NOTE] Injecting user provenance notes: '{user_notes}'")
        prompt += f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nUSER PROVIDED METADATA/NOTES\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nThe user provided the following context for the items in this image: '{user_notes}'. Incorporate this provenance and history into your material identification, age estimation, and final pricing valuation."

    with Image.open(image_path) as image:
        result = _call_gemini(prompt, image=image, temperature=0.0, model_override=PRICING_MODEL)

    # Strip any reasoning text before the JSON
    if result and not result.startswith(('[', '"', '{')):
        bracket_idx = result.find('[')
        if bracket_idx != -1:
            result = result[bracket_idx:]

    # Check for errors from Pass 1
    if not result or result in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE") or result.startswith("SCAN_ERROR"):
        return result

    # ── Pass 2: Skipped (Speed Optimization) ──
    # We bypass Pass 2 entirely. Gemini 2.5 Pro is smart enough to do it right in one try.
    print("  [SKIP] Skipping validation pass; handled by single-pass Pro architecture.")

    return result


def refine_bounding_box(image_path: str, item_name: str) -> str:
    """Provides high-precision bounding box for a specific zoomed-in item."""
    print(f"  [TARGET] Refining bounding box for '{item_name}'")

    prompt = f"""
    You are an expert image editor. The provided image is a zoomed-in crop of a '{item_name}'.
    Your goal is to provide the MOST PRECISE bounding box that strictly contains the '{item_name}' and nothing else.
    
    Ensure the edges of the box are tight against the object's physical boundaries.
    Exclude as much background, floor, or adjacent objects as possible.
    
    Return the response ONLY as a JSON object with:
    {{
      "refined_bounding_box": [ymin, xmin, ymax, xmax]
    }}
    Use normalized coordinates (0-1000) based on THIS zoomed image.
    """

    try:
        with Image.open(image_path) as image:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt, image],
                config={
                    'temperature': 0.0,
                    'response_mime_type': 'application/json'
                }
            )
            return response.text
    except Exception as e:
        print(f"  [X] Refinement error: {e}")
        return None


def generate_resale_listing(item_data: dict) -> str:
    """Generates a professional marketplace listing via AI."""
    name = item_data.get('name', 'Unknown Item')
    print(f"[MONEY] Generating resale listing for '{name}'")

    prompt = RESALE_LISTING_PROMPT.format(
        name=name,
        category=item_data.get('category', 'General'),
        make=item_data.get('make', 'Unknown'),
        model=item_data.get('model', 'Unidentified'),
        condition=item_data.get('condition', 'Good'),
        condition_notes=item_data.get('condition_notes', 'No notes available'),
        dimensions=item_data.get('estimated_dimensions', 'Not specified'),
        resale_value=item_data.get('resale_value_usd', item_data.get('estimated_price_usd', 'N/A')),
        retail_replacement=item_data.get('retail_replacement_usd', 'N/A'),
        age=item_data.get('estimated_age_years', 'Unknown'),
        room=item_data.get('room_name', 'General Room'),
        price_basis=item_data.get('price_basis', 'Market estimate'),
    )

    return _call_gemini(prompt, temperature=0.7)


# ═══════════════════════════════════════════════════════════════
# CLI TESTING
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("================================")
    print("  Holos Scanner - Test Mode")
    print(f"  Model: {MODEL_ID}")
    print("================================")

    import sys
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
        print(f"\n[ROOM] Testing room analysis on: {test_image}")
        result = analyze_room(test_image)
        try:
            parsed = json.loads(result)
            print(json.dumps(parsed, indent=2))
            print(f"\n[OK] Found {len(parsed)} items")
            total = sum(item.get('estimated_price_usd', 0) for item in parsed if isinstance(item.get('estimated_price_usd'), (int, float)))
            print(f"[OK] Total estimated value: ${total:,.2f}")
        except json.JSONDecodeError:
            print(f"Raw output:\n{result}")
    else:
        print("\nUsage: python scanner.py <image_path>")
        print("Example: python scanner.py test_room.jpg")
