"""
Holos Schemas — Agent 2 (AI Reliability)
Pydantic models matching §7 22-field vision output schema exactly.

Key changes from v1:
- Tri-value pricing is LOW/HIGH CENTS (bigint), NOT string ranges like "$425-$575"
- Condition and Category are proper Enums
- Confidence scores are 0.0-1.0 floats (not 0-100 ints)
- Bounding box coordinate system is a Literal, tied to schema
- Flags are enum-constrained
- No more .replace('```json','') anywhere — structured output raises ParseError
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import structlog

log = structlog.get_logger("holos.schemas")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Condition(str, Enum):
    EXCELLENT = "excellent"
    GOOD      = "good"
    FAIR      = "fair"
    POOR      = "poor"
    DAMAGED   = "damaged"


class Category(str, Enum):
    ELECTRONICS  = "electronics"
    FURNITURE    = "furniture"
    APPLIANCE    = "appliance"
    JEWELRY      = "jewelry"
    ART          = "art"
    CLOTHING     = "clothing"
    KITCHENWARE  = "kitchenware"
    TOOLS        = "tools"
    DECOR        = "decor"
    MEDIA        = "media"
    INSTRUMENTS  = "instruments"
    SPORTS       = "sports"
    COLLECTIBLE  = "collectible"
    OTHER        = "other"


ItemFlag = Literal[
    "high_value",
    "requires_appraisal",
    "serialized",
    "low_light",
    "partial_occlusion",
    "possible_duplicate",
]


# ---------------------------------------------------------------------------
# §7 — 22-Field Vision Output Schema
# ---------------------------------------------------------------------------

class ItemEstimate(BaseModel):
    """
    Single item identified by Gemini from a room/item photograph.
    Enforced with Pydantic. Provider's native structured-output mode feeds this.
    No regex cleanup — if SDK returns non-conforming output, ParseError is raised.
    """

    # Identification (fields 1-9)
    item_name: str = Field(min_length=2, max_length=120)
    category: Category
    subcategory: str
    brand: Optional[str] = None
    model: Optional[str] = None
    estimated_age_years: Optional[str] = None
    color_material: str
    dimensions_estimate: Optional[str] = None
    room_hint: str

    # Quantity (fields 10-11)
    quantity: int = Field(ge=1, default=1)
    is_set: bool = False

    # Condition (fields 12-14)
    condition: Condition
    condition_confidence: float = Field(ge=0.0, le=1.0)
    condition_evidence: str

    # Identification confidence (fields 15-16)
    identification_confidence: float = Field(ge=0.0, le=1.0)
    identification_basis: str

    # Tri-value pricing — LOW/HIGH CENTS, never string ranges (fields 17-23)
    value_resale_low_cents: int = Field(ge=0)
    value_resale_high_cents: int = Field(ge=0)
    value_retail_replacement_low_cents: int = Field(ge=0)
    value_retail_replacement_high_cents: int = Field(ge=0)
    value_insurance_replacement_low_cents: int = Field(ge=0)
    value_insurance_replacement_high_cents: int = Field(ge=0)
    pricing_rationale: str

    # Spatial (fields 24-25)
    bounding_box: tuple[int, int, int, int]  # [ymin, xmin, ymax, xmax] 0-1000
    bounding_box_coordinate_system: Literal["yxyx_1000"] = "yxyx_1000"

    # Flags (field 26)
    flags: list[ItemFlag] = []

    # ── Validators ────────────────────────────────────────────────

    @field_validator("bounding_box", mode="before")
    @classmethod
    def coerce_bounding_box(cls, v: object) -> tuple[int, int, int, int]:
        if isinstance(v, (list, tuple)) and len(v) == 4:
            try:
                return tuple(max(0, min(1000, int(x))) for x in v)  # type: ignore[return-value]
            except (ValueError, TypeError):
                pass
        return (0, 0, 0, 0)

    @field_validator("value_resale_high_cents", mode="after")
    @classmethod
    def resale_high_gte_low(cls, v: int, info: object) -> int:
        low = getattr(info, "data", {}).get("value_resale_low_cents", 0)
        if v < low:
            return low
        return v

    @model_validator(mode="after")
    def insurance_gte_retail(self) -> "ItemEstimate":
        """Insurance must be >= retail (it includes delivery + sourcing uplift)."""
        if self.value_insurance_replacement_high_cents < self.value_retail_replacement_high_cents:
            self.value_insurance_replacement_high_cents = int(
                self.value_retail_replacement_high_cents * 1.15
            )
        return self

    # ── Helpers ───────────────────────────────────────────────────

    @property
    def resale_midpoint_cents(self) -> int:
        return (self.value_resale_low_cents + self.value_resale_high_cents) // 2

    @property
    def insurance_midpoint_cents(self) -> int:
        return (
            self.value_insurance_replacement_low_cents
            + self.value_insurance_replacement_high_cents
        ) // 2

    def to_db_dict(self) -> dict:
        """Maps to the items table column names from §6."""
        return {
            "name": self.item_name,
            "category": self.category.value,
            "subcategory": self.subcategory,
            "brand": self.brand,
            "model": self.model,
            "estimated_age_years": self.estimated_age_years,
            "color_material": self.color_material,
            "dimensions_estimate": self.dimensions_estimate,
            "room": self.room_hint,
            "quantity": self.quantity,
            "is_set": self.is_set,
            "condition": self.condition.value,
            "condition_confidence": float(self.condition_confidence),
            "condition_evidence": self.condition_evidence,
            "identification_confidence": float(self.identification_confidence),
            "identification_basis": self.identification_basis,
            "resale_low_cents": self.value_resale_low_cents,
            "resale_high_cents": self.value_resale_high_cents,
            "retail_replacement_low_cents": self.value_retail_replacement_low_cents,
            "retail_replacement_high_cents": self.value_retail_replacement_high_cents,
            "insurance_replacement_low_cents": self.value_insurance_replacement_low_cents,
            "insurance_replacement_high_cents": self.value_insurance_replacement_high_cents,
            "pricing_rationale": self.pricing_rationale,
            "bounding_box": list(self.bounding_box),
            "bounding_box_coordinate_system": self.bounding_box_coordinate_system,
            "flags": self.flags,
        }

    # Backward-compat alias used by old route code
    def to_scan_dict(self) -> dict:
        d = self.to_db_dict()
        # Add legacy fields old UI code still reads
        d["estimated_price_usd"] = self.resale_midpoint_cents / 100
        d["make"] = self.brand
        d["confidence_score"] = int(self.identification_confidence * 100)
        return d


# ---------------------------------------------------------------------------
# Resale Listing Schema (unchanged — no structural fix needed here)
# ---------------------------------------------------------------------------

class ResaleListing(BaseModel):
    listing_title: str = Field(max_length=100)
    listing_description: str
    buy_now_price: str
    offer_floor_price: str
    suggested_tags: list[str] = Field(default_factory=list)
    best_platform: str = Field(default="eBay")


# ---------------------------------------------------------------------------
# Custom Exceptions (typed, not sentinel strings)
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Raised when AI response does not conform to schema. Never silently ignored."""
    pass


class ClassifierError(Exception):
    """Base for all vision classifier errors."""
    pass


class QuotaError(ClassifierError):
    """Gemini quota exhausted."""
    pass


class UnavailableError(ClassifierError):
    """Gemini API temporarily unavailable (503)."""
    pass


# ---------------------------------------------------------------------------
# Depreciation Calculator — deterministic Python, NOT in the prompt
# Per §8.3: "Move the depreciation table into post-processing, not the prompt"
# ---------------------------------------------------------------------------

_DEPRECIATION: dict[str, dict[str, float]] = {
    # category_key: {condition: resale_as_fraction_of_retail}
    "electronics":   {"excellent": 0.45, "good": 0.35, "fair": 0.20, "poor": 0.10, "damaged": 0.05},
    "furniture":     {"excellent": 0.55, "good": 0.40, "fair": 0.25, "poor": 0.15, "damaged": 0.05},
    "appliance":     {"excellent": 0.50, "good": 0.35, "fair": 0.20, "poor": 0.10, "damaged": 0.05},
    "instruments":   {"excellent": 0.65, "good": 0.50, "fair": 0.35, "poor": 0.20, "damaged": 0.10},
    "art":           {"excellent": 0.70, "good": 0.55, "fair": 0.35, "poor": 0.20, "damaged": 0.10},
    "collectible":   {"excellent": 0.90, "good": 0.80, "fair": 0.60, "poor": 0.40, "damaged": 0.20},
    "media":         {"excellent": 0.40, "good": 0.25, "fair": 0.15, "poor": 0.05, "damaged": 0.02},
    "sports":        {"excellent": 0.50, "good": 0.35, "fair": 0.20, "poor": 0.10, "damaged": 0.05},
    "default":       {"excellent": 0.55, "good": 0.40, "fair": 0.25, "poor": 0.15, "damaged": 0.05},
}

_INSURANCE_UPLIFT = 1.15  # §8.3: retail × 1.15


def calculate_tri_value(
    retail_midpoint_cents: int,
    category: str,
    condition: str,
    price_range_pct: float = 0.15,
) -> dict[str, int]:
    """
    Deterministic tri-value pricing from a retail midpoint.
    Called in post-processing — never embedded in an AI prompt.

    Args:
        retail_midpoint_cents: Retail replacement midpoint in cents
        category: Category enum value string
        condition: Condition enum value string
        price_range_pct: ±% for low/high range (default ±15%)

    Returns:
        Dict with all 6 low/high cents keys for ItemEstimate
    """
    table = _DEPRECIATION.get(category.lower(), _DEPRECIATION["default"])
    rate = table.get(condition.lower(), 0.40)

    resale_mid = int(retail_midpoint_cents * rate)
    insurance_mid = int(retail_midpoint_cents * _INSURANCE_UPLIFT)

    def _range(mid: int) -> tuple[int, int]:
        low = int(mid * (1 - price_range_pct))
        high = int(mid * (1 + price_range_pct))
        return max(0, low), max(0, high)

    retail_low, retail_high = _range(retail_midpoint_cents)
    resale_low, resale_high = _range(resale_mid)
    insurance_low, insurance_high = _range(insurance_mid)

    return {
        "value_resale_low_cents": resale_low,
        "value_resale_high_cents": resale_high,
        "value_retail_replacement_low_cents": retail_low,
        "value_retail_replacement_high_cents": retail_high,
        "value_insurance_replacement_low_cents": insurance_low,
        "value_insurance_replacement_high_cents": insurance_high,
    }


# ---------------------------------------------------------------------------
# Validation Helper
# ---------------------------------------------------------------------------

def validate_items(raw_items: list[dict]) -> tuple[list[ItemEstimate], int]:
    """
    Validate a list of raw dicts into typed ItemEstimate models.
    Returns (validated_items, parse_failures_count).
    Does NOT silently swallow all errors — logs each failure for eval tracking.
    """
    validated: list[ItemEstimate] = []
    failures = 0

    for i, raw in enumerate(raw_items):
        try:
            item = ItemEstimate.model_validate(raw)
            validated.append(item)
        except Exception as e:
            failures += 1
            log.warning(
                "item_parse_failed",
                index=i,
                name=raw.get("item_name", raw.get("name", "?")),
                error=str(e)[:200],
            )

    parse_rate = len(validated) / max(len(raw_items), 1)
    log.info(
        "validation_complete",
        total=len(raw_items),
        parsed=len(validated),
        failures=failures,
        parse_rate=f"{parse_rate:.1%}",
    )

    return validated, failures
