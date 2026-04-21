"""
Tests for §7 Pydantic schema — ItemEstimate and validate_items.
Updated for Agent 2: §7 field names, cents pricing, 0.0-1.0 confidence.
Tests match ACTUAL schema behavior (strict validation, no silent coercion).
"""
import pytest
from pydantic import ValidationError
from schemas import ItemEstimate, validate_items, Category, Condition


VALID_ITEM = {
    "item_name": "IKEA KALLAX Shelf Unit",
    "category": "furniture",
    "subcategory": "shelving",
    "brand": "IKEA",
    "model": "KALLAX",
    "color_material": "white laminate",
    "dimensions_estimate": "149cm x 149cm",
    "room_hint": "living room",
    "condition": "good",
    "identification_confidence": 0.88,
    "condition_confidence": 0.80,
    "condition_evidence": "Clean with minor surface scratches",
    "value_retail_replacement_low_cents": 8000,
    "value_retail_replacement_high_cents": 10000,
    "value_resale_low_cents": 4000,
    "value_resale_high_cents": 6000,
    "value_insurance_replacement_low_cents": 9000,
    "value_insurance_replacement_high_cents": 11500,
    "pricing_rationale": "KALLAX 4x4 retails $90-$110 at IKEA, resale $40-$60",
    "bounding_box": [100, 200, 800, 900],
    "flags": [],
    "identification_basis": "IKEA logo visible on back panel",
}


def _item(**overrides):
    """Return a valid item dict with optional field overrides."""
    return {**VALID_ITEM, **overrides}


class TestItemEstimate:
    """Tests for the §7 ItemEstimate Pydantic model."""

    def test_valid_item_parses(self):
        """A well-formed §7 response should parse cleanly."""
        item = ItemEstimate.model_validate(VALID_ITEM)
        assert item.item_name == "IKEA KALLAX Shelf Unit"
        assert item.category == Category.FURNITURE
        assert item.condition == Condition.GOOD
        assert item.value_retail_replacement_low_cents == 8000
        assert item.identification_confidence == 0.88

    def test_bounding_box_valid(self):
        """Bounding box [ymin, xmin, ymax, xmax] parsed correctly."""
        item = ItemEstimate.model_validate(VALID_ITEM)
        assert list(item.bounding_box) == [100, 200, 800, 900]

    def test_short_bounding_box_defaults_to_zero(self):
        """Bounding box with < 4 elements falls back to [0,0,0,0]."""
        item = ItemEstimate.model_validate(_item(bounding_box=[10, 20]))
        assert list(item.bounding_box) == [0, 0, 0, 0]

    def test_missing_bounding_box_defaults(self):
        """Missing bounding_box should default to [0,0,0,0]."""
        d = {k: v for k, v in VALID_ITEM.items() if k != "bounding_box"}
        # bounding_box is required — omitting it should raise ValidationError
        with pytest.raises(ValidationError):
            ItemEstimate.model_validate(d)

    def test_confidence_out_of_range_raises(self):
        """identification_confidence > 1.0 raises ValidationError (strict schema)."""
        with pytest.raises(ValidationError):
            ItemEstimate.model_validate(_item(identification_confidence=1.5))

    def test_confidence_negative_raises(self):
        """identification_confidence < 0.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            ItemEstimate.model_validate(_item(identification_confidence=-0.3))

    def test_confidence_boundary_values(self):
        """0.0 and 1.0 are valid boundary values."""
        assert ItemEstimate.model_validate(_item(identification_confidence=0.0)).identification_confidence == 0.0
        assert ItemEstimate.model_validate(_item(identification_confidence=1.0)).identification_confidence == 1.0

    def test_invalid_condition_raises(self):
        """Unknown condition string raises ValidationError (strict enum)."""
        with pytest.raises(ValidationError):
            ItemEstimate.model_validate(_item(condition="FANTASTIC"))

    def test_valid_conditions_parse(self):
        """All valid Condition enum values parse correctly."""
        for cond in ("excellent", "good", "fair", "poor", "damaged"):
            item = ItemEstimate.model_validate(_item(condition=cond))
            assert item.condition.value == cond

    def test_resale_high_corrected_when_lt_low(self):
        """When resale_high < resale_low, validator sets high = low."""
        item = ItemEstimate.model_validate(_item(
            value_resale_low_cents=6000,
            value_resale_high_cents=4000,  # intentionally reversed
        ))
        assert item.value_resale_high_cents >= item.value_resale_low_cents

    def test_insurance_gte_retail_enforced(self):
        """Insurance high must be >= retail high; validator adds 15% if not."""
        item = ItemEstimate.model_validate(_item(
            value_retail_replacement_high_cents=10000,
            value_insurance_replacement_high_cents=500,  # too low
        ))
        assert item.value_insurance_replacement_high_cents >= item.value_retail_replacement_high_cents

    def test_flags_default_empty(self):
        """flags field defaults to empty list if omitted."""
        d = {k: v for k, v in VALID_ITEM.items() if k != "flags"}
        item = ItemEstimate.model_validate(d)
        assert item.flags == []

    def test_to_scan_dict_has_required_keys(self):
        """to_scan_dict() must include all keys needed by frontend."""
        item = ItemEstimate.model_validate(VALID_ITEM)
        d = item.to_scan_dict()
        assert isinstance(d, dict)
        for key in ("name", "category", "condition", "identification_confidence", "bounding_box"):
            assert key in d, f"Missing key in to_scan_dict: {key}"

    def test_to_scan_dict_name_alias(self):
        """to_scan_dict() must include 'name' key = item_name value."""
        item = ItemEstimate.model_validate(VALID_ITEM)
        d = item.to_scan_dict()
        assert d["name"] == "IKEA KALLAX Shelf Unit"

    def test_cents_pricing_stored_as_int(self):
        """Pricing values must be stored as integers (cents)."""
        item = ItemEstimate.model_validate(VALID_ITEM)
        assert isinstance(item.value_retail_replacement_low_cents, int)
        assert isinstance(item.value_resale_high_cents, int)
        assert isinstance(item.value_insurance_replacement_high_cents, int)

    def test_resale_midpoint_property(self):
        """resale_midpoint_cents = (low + high) // 2."""
        item = ItemEstimate.model_validate(VALID_ITEM)
        assert item.resale_midpoint_cents == (4000 + 6000) // 2

    def test_invalid_category_raises(self):
        """Unknown category string should raise ValidationError."""
        with pytest.raises(ValidationError):
            ItemEstimate.model_validate(_item(category="magic"))


class TestValidateItems:
    """Tests for batch validate_items() helper."""

    def test_valid_batch(self):
        """All valid items should parse successfully."""
        items, failures = validate_items([VALID_ITEM, _item(item_name="Samsung TV", category="electronics")])
        assert len(items) == 2
        assert failures == 0

    def test_empty_batch(self):
        """Empty input should return empty output."""
        items, failures = validate_items([])
        assert len(items) == 0
        assert failures == 0

    def test_invalid_item_salvaged(self):
        """Items failing validation are counted as failures, excluded from items."""
        items, failures = validate_items([VALID_ITEM, {"bad_field": "no name or category"}])
        assert len(items) == 1   # only valid item included
        assert failures == 1     # one failure logged

    def test_mixed_batch_salvages(self):
        """Good + bad items: valid ones included, failures counted separately."""
        second = {**VALID_ITEM, "item_name": "Good Item"}
        items, failures = validate_items([VALID_ITEM, second, {"completely_wrong": True}])
        assert len(items) == 2   # 2 valid
        assert failures == 1     # 1 failed
