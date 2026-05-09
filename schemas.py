"""
Agent 2 — AI Reliability: Data schemas and deterministic pricing engine.

Pydantic models enforce the shape of all AI outputs at parse time.
compute_prices() derives all price fields from a single retail anchor + the
depreciation table, making valuation deterministic and consistent.
"""
from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Depreciation Table ───────────────────────────────────────────────────────
# Keep in sync with the table displayed in scanner.py's IDENTIFICATION_PROMPT.
DEPRECIATION_TABLE: dict[str, dict[str, float]] = {
    "Electronics":          {"Excellent": 0.45, "Good": 0.35, "Fair": 0.20, "Poor": 0.10, "Damaged": 0.05},
    "Furniture (mass)":     {"Excellent": 0.55, "Good": 0.40, "Fair": 0.25, "Poor": 0.15, "Damaged": 0.05},
    "Furniture (designer)": {"Excellent": 0.65, "Good": 0.50, "Fair": 0.35, "Poor": 0.20, "Damaged": 0.10},
    "Appliances":           {"Excellent": 0.50, "Good": 0.35, "Fair": 0.20, "Poor": 0.10, "Damaged": 0.05},
    "Decor / Art":          {"Excellent": 0.70, "Good": 0.55, "Fair": 0.35, "Poor": 0.20, "Damaged": 0.10},
    "Antiques":             {"Excellent": 0.90, "Good": 0.80, "Fair": 0.60, "Poor": 0.40, "Damaged": 0.20},
    "Instruments":          {"Excellent": 0.65, "Good": 0.50, "Fair": 0.35, "Poor": 0.20, "Damaged": 0.10},
    "Media / Books":        {"Excellent": 0.40, "Good": 0.25, "Fair": 0.15, "Poor": 0.05, "Damaged": 0.02},
    "Sports / Fitness":     {"Excellent": 0.50, "Good": 0.35, "Fair": 0.20, "Poor": 0.10, "Damaged": 0.05},
}

_DESIGNER_BRANDS: frozenset[str] = frozenset({
    "herman miller", "restoration hardware", "pottery barn", "west elm",
    "crate & barrel", "ethan allen", "room & board", "arhaus", "knoll",
    "cassina", "fritz hansen", "vitra", "hay", "muuto", "eames",
})

_VALID_CONDITIONS: tuple[str, ...] = ("Excellent", "Good", "Fair", "Poor", "Damaged")


# ── Pricing Helpers ──────────────────────────────────────────────────────────

def parse_price(value: str | int | float | None) -> float:
    """Extract the first numeric value from a price string. Returns 0.0 on failure."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    nums = re.findall(r"\d[\d,]*\.?\d*", str(value).replace(",", ""))
    return float(nums[0]) if nums else 0.0


def dep_key(category: str, make: str = "") -> str:
    """Map Gemini's category string to a DEPRECIATION_TABLE key."""
    cat = category.lower()
    if any(k in cat for k in ("furniture", "seating", "bed", "storage", "table", "office")):
        if make and make.lower() in _DESIGNER_BRANDS:
            return "Furniture (designer)"
        return "Furniture (mass)"
    if any(k in cat for k in ("electronic", "computing", "entertainment", "audio", "photography")):
        return "Electronics"
    if "appliance" in cat:
        return "Appliances"
    if any(k in cat for k in ("decor", "art", "rug", "mirror", "lighting", "plant", "object")):
        return "Decor / Art"
    if "instrument" in cat:
        return "Instruments"
    if any(k in cat for k in ("media", "book", "music", "game")):
        return "Media / Books"
    if any(k in cat for k in ("sport", "fitness", "gym", "outdoor")):
        return "Sports / Fitness"
    return "Furniture (mass)"


def is_antique(estimated_age_years: str | None) -> bool:
    """Return True if the age string indicates 15+ years old."""
    if not estimated_age_years:
        return False
    age_str = str(estimated_age_years).lower()
    if any(k in age_str for k in ("15+", "vintage", "antique", "pre-", "pre 2")):
        return True
    nums = re.findall(r"\d+", age_str)
    return bool(nums) and int(nums[0]) >= 15


def compute_prices(
    retail_usd: float,
    category: str,
    condition: str,
    quantity: int = 1,
    make: str = "",
    estimated_age_years: str | None = None,
) -> dict:
    """
    Deterministic pricing from a retail anchor + depreciation table.
    Returns a dict with all price fields ready to merge into a ScannedItem.
    Prices use ±15% margin bands to keep ranges tight.
    """
    dk = "Antiques" if is_antique(estimated_age_years) else dep_key(category, make)
    rates = DEPRECIATION_TABLE.get(dk, DEPRECIATION_TABLE["Furniture (mass)"])
    dep_rate = rates.get(condition, rates.get("Good", 0.35))

    resale_mid = retail_usd * dep_rate
    ins_mid = retail_usd * 1.15
    margin = 0.15

    def _rng(mid: float, qty: int = 1) -> str:
        lo = round(mid * (1 - margin) * qty)
        hi = round(mid * (1 + margin) * qty)
        return f"${lo:,}–${hi:,}"

    return {
        "estimated_price_usd": round(resale_mid * quantity),
        "unit_price_usd": _rng(resale_mid),
        "resale_value_usd": _rng(resale_mid, quantity),
        "retail_replacement_usd": _rng(retail_usd, quantity),
        "insurance_replacement_usd": _rng(ins_mid, quantity),
        "price_basis": (
            f"Retail anchor: ${round(retail_usd):,}. "
            f"{dk} in {condition} condition → {round(dep_rate * 100)}% depreciation. "
            f"Insurance = retail × 1.15."
        ),
    }


# ── Pydantic Models ──────────────────────────────────────────────────────────

class ScannedItem(BaseModel):
    """Validated output for one identified item after the AI pass + pricing engine."""

    name: str
    category: str
    make: str = "Unknown"
    model: str = "Unidentified"
    quantity: int = Field(default=1, ge=1)
    is_set: bool = False
    estimated_age_years: Optional[str] = None
    condition: str = "Good"
    condition_notes: str = ""
    estimated_dimensions: str = ""
    unit_price_usd: Optional[str] = None
    estimated_price_usd: int = 0
    resale_value_usd: str = "$0–$0"
    retail_replacement_usd: str = "$0–$0"
    insurance_replacement_usd: str = "$0–$0"
    price_basis: str = ""
    confidence_score: int = Field(default=50, ge=0, le=100)
    identification_basis: str = ""
    suggested_replacements: Optional[str] = None
    bounding_box: list[int] = Field(default_factory=lambda: [0, 0, 0, 0])

    # Injected by scan route — not from AI
    original_image_url: Optional[str] = None
    home_name: Optional[str] = None
    room_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    thumbnail_source: Optional[str] = None
    id: Optional[str] = None
    auto_saved: Optional[bool] = None
    review_reason: Optional[str] = None

    @field_validator("condition", mode="before")
    @classmethod
    def normalize_condition(cls, v: object) -> str:
        if not isinstance(v, str):
            return "Good"
        for valid in _VALID_CONDITIONS:
            if valid.lower() == str(v).strip().lower():
                return valid
        return "Good"

    @field_validator("confidence_score", mode="before")
    @classmethod
    def coerce_confidence(cls, v: object) -> int:
        if isinstance(v, str):
            try:
                return max(0, min(100, int(v.replace("%", "").strip())))
            except (ValueError, TypeError):
                return 50
        try:
            return max(0, min(100, int(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 50

    @field_validator("estimated_price_usd", mode="before")
    @classmethod
    def coerce_estimated_price(cls, v: object) -> int:
        if isinstance(v, str):
            nums = re.findall(r"\d[\d,]*", v.replace(",", ""))
            return int(nums[0]) if nums else 0
        try:
            return max(0, int(v))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    @field_validator("quantity", mode="before")
    @classmethod
    def coerce_quantity(cls, v: object) -> int:
        try:
            return max(1, int(v))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1

    @field_validator("bounding_box", mode="before")
    @classmethod
    def validate_bbox(cls, v: object) -> list[int]:
        if not isinstance(v, list) or len(v) != 4:
            return [0, 0, 0, 0]
        try:
            return [max(0, min(1000, int(x))) for x in v]
        except (TypeError, ValueError):
            return [0, 0, 0, 0]

    def to_api_dict(self) -> dict:
        return self.model_dump(exclude_none=False)


class ResaleListing(BaseModel):
    """Validated AI output for /api/items/<id>/resale."""

    listing_title: str
    listing_description: str
    buy_now_price: str
    offer_floor_price: str
    suggested_tags: list[str] = Field(default_factory=list)
    best_platform: str = "eBay"

    @field_validator("listing_title")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        return v[:80]

    @field_validator("suggested_tags", mode="before")
    @classmethod
    def ensure_list(cls, v: object) -> list:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return []
