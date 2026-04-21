from schemas import ItemEstimate, Category, Condition, ParseError, QuotaError, calculate_tri_value, validate_items
print("schemas import OK")

# Test depreciation calculator
tri = calculate_tri_value(100000, "electronics", "good")
print(f"depreciation: resale={tri['value_resale_low_cents']//100}-{tri['value_resale_high_cents']//100}, retail={tri['value_retail_replacement_low_cents']//100}-{tri['value_retail_replacement_high_cents']//100}")
assert tri["value_resale_low_cents"] > 0
assert tri["value_retail_replacement_low_cents"] == 85000
assert tri["value_insurance_replacement_high_cents"] > 110000  # insurance_high > retail_high
print("depreciation calculator OK")

# Test Pydantic validation with valid item
items, failures = validate_items([{
    "item_name": "Samsung 65-inch OLED TV",
    "category": "electronics",
    "subcategory": "television",
    "color_material": "black",
    "room_hint": "living room",
    "condition": "good",
    "condition_confidence": 0.9,
    "condition_evidence": "no visible scratches",
    "identification_confidence": 0.85,
    "identification_basis": "Samsung logo visible",
    "value_resale_low_cents": 0,
    "value_resale_high_cents": 0,
    "value_retail_replacement_low_cents": 90000,
    "value_retail_replacement_high_cents": 110000,
    "value_insurance_replacement_low_cents": 0,
    "value_insurance_replacement_high_cents": 0,
    "pricing_rationale": "OLED 65in retails ~$1000",
    "bounding_box": [100, 100, 500, 500],
}])
assert len(items) == 1, f"Expected 1 item, got {len(items)}"
assert items[0].item_name == "Samsung 65-inch OLED TV"
assert items[0].category == Category.ELECTRONICS
print("validate_items OK")

# Test ParseError is raised on garbage input
from schemas import ParseError
import scanner
print(f"scanner import OK")
print(f"Vision model: {scanner.VISION_MODEL}")
print(f"Pricing model: {scanner.PRICING_MODEL}")

try:
    scanner._parse_and_validate("this is not json")
    assert False, "Should have raised ParseError"
except ParseError as e:
    print(f"ParseError raised correctly: {str(e)[:60]}")

print("\nAll Agent 2 checks PASSED")
