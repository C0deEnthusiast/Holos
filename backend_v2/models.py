"""
Backend v2 — Pydantic Response Models (Agent 4)
Typed API contracts for /v2 endpoints.
Reuses §7 ItemEstimate from schemas.py where possible.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str = "2.0.0"
    db: str
    model: str


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------

class ItemResponse(BaseModel):
    """Item as returned by GET /v2/items and POST /v2/items/save."""
    id: str
    user_id: str
    name: str
    category: str
    brand: Optional[str] = None
    model: Optional[str] = None
    condition: Optional[str] = None
    condition_confidence: Optional[float] = None
    identification_confidence: Optional[float] = None
    quantity: int = 1
    is_set: bool = False

    # Pricing (cents)
    resale_low_cents: Optional[int] = 0
    resale_high_cents: Optional[int] = 0
    retail_replacement_low_cents: Optional[int] = 0
    retail_replacement_high_cents: Optional[int] = 0
    insurance_replacement_low_cents: Optional[int] = 0
    insurance_replacement_high_cents: Optional[int] = 0
    pricing_rationale: Optional[str] = None

    # Display strings (computed server-side)
    resale_display: Optional[str] = None
    retail_display: Optional[str] = None
    insurance_display: Optional[str] = None

    # Location
    home_name: str = "My Home"
    room_name: str = "General Room"

    # Media
    thumbnail_url: Optional[str] = None
    original_image_url: Optional[str] = None
    web_image_url: Optional[str] = None

    # Flags
    flags: Optional[list[str]] = []
    is_archived: bool = False
    user_confirmed: bool = False

    class Config:
        from_attributes = True


class ItemsListResponse(BaseModel):
    success: bool = True
    data: list[ItemResponse]
    total: int


class SaveItemRequest(BaseModel):
    name: str = Field(min_length=2)
    category: str
    brand: Optional[str] = None
    model: Optional[str] = None
    condition: Optional[str] = None
    condition_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    condition_evidence: Optional[str] = None
    identification_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    identification_basis: Optional[str] = None
    quantity: int = Field(default=1, ge=1)
    is_set: bool = False
    resale_low_cents: int = Field(default=0, ge=0)
    resale_high_cents: int = Field(default=0, ge=0)
    retail_replacement_low_cents: int = Field(default=0, ge=0)
    retail_replacement_high_cents: int = Field(default=0, ge=0)
    insurance_replacement_low_cents: int = Field(default=0, ge=0)
    insurance_replacement_high_cents: int = Field(default=0, ge=0)
    pricing_rationale: Optional[str] = None
    bounding_box: Optional[list[int]] = None
    flags: list[str] = []
    home_name: str = "My Home"
    room_name: str = "General Room"
    thumbnail_url: Optional[str] = None
    scan_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

class ScanResultItem(BaseModel):
    """Single item from a scan result — scan_dict format for frontend compat."""
    item_name: str
    name: str         # backward compat alias
    category: str
    brand: Optional[str] = None
    model: Optional[str] = None
    condition: str = "good"
    condition_confidence: float = 0.5
    identification_confidence: float = 0.5
    resale_low_cents: int = 0
    resale_high_cents: int = 0
    retail_replacement_low_cents: int = 0
    retail_replacement_high_cents: int = 0
    insurance_replacement_low_cents: int = 0
    insurance_replacement_high_cents: int = 0
    resale_display: Optional[str] = None
    retail_display: Optional[str] = None
    insurance_display: Optional[str] = None
    bounding_box: list[int] = [0, 0, 0, 0]
    flags: list[str] = []
    auto_saved: bool = False
    thumbnail_url: Optional[str] = None
    original_image_url: Optional[str] = None
    id: Optional[str] = None


class ScanResponse(BaseModel):
    success: bool = True
    data: list[ScanResultItem]
    auto_saved: list[ScanResultItem] = []
    needs_review: list[ScanResultItem] = []
    summary: dict
    errors: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Estate Report
# ---------------------------------------------------------------------------

class ReportItem(BaseModel):
    name: Optional[str]
    category: Optional[str]
    brand: Optional[str]
    model: Optional[str]
    condition: Optional[str]
    resale_midpoint: float
    insurance_midpoint: float
    resale_range: str
    insurance_range: str
    thumbnail: Optional[str]


class RoomReport(BaseModel):
    items: list[ReportItem]
    subtotal_resale: float
    subtotal_insurance: float


class EstateReportResponse(BaseModel):
    success: bool = True
    report_date: str
    owner_id: str
    total_items: int
    total_resale_value: float
    total_insurance_value: float
    properties: dict[str, dict[str, RoomReport]]
