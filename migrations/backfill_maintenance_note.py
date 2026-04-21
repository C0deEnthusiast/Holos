"""
Migration: Backfill maintenance_note JSON data into new columns.

Run ONCE after executing 001_add_item_columns.sql.
Safe to run multiple times — only updates items that still have unpacked JSON.

Usage:
    python migrations/backfill_maintenance_note.py
"""
import os
import sys
import json
import re

# Add parent dir to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from config import Config


def parse_price_range(range_str: str) -> tuple[float | None, float | None]:
    """Parse '$425-$575' into (425.0, 575.0). Returns (None, None) on failure."""
    if not range_str or range_str == "N/A":
        return None, None
    cleaned = str(range_str).replace("$", "").replace(",", "")
    numbers = re.findall(r"[\d.]+", cleaned)
    if len(numbers) >= 2:
        return float(numbers[0]), float(numbers[1])
    elif len(numbers) == 1:
        val = float(numbers[0])
        return val, val
    return None, None


def main():
    if not Config.SUPABASE_URL or not (Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY):
        print("ERROR: Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)

    key = Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY
    supabase = create_client(Config.SUPABASE_URL, key)

    print("Fetching all items with maintenance_note data...")
    result = supabase.table("items").select("id, maintenance_note, scans(home_name, room_name)").execute()
    items = result.data or []
    print(f"Found {len(items)} total items")

    updated = 0
    skipped = 0
    errors = 0

    for item in items:
        note = item.get("maintenance_note", "")
        if not note or not str(note).startswith("{"):
            skipped += 1
            continue

        try:
            meta = json.loads(note)
        except json.JSONDecodeError:
            skipped += 1
            continue

        # Build update payload from JSON data
        update = {}

        # Simple fields
        for field in [
            "quantity", "is_set", "estimated_age_years", "condition_notes",
            "unit_price_usd", "price_basis", "confidence_score",
            "identification_basis",
        ]:
            val = meta.get(field)
            if val is not None:
                update[field] = val

        # Price range strings
        for field in ["resale_value_usd", "retail_replacement_usd", "insurance_replacement_usd"]:
            val = meta.get(field)
            if val:
                update[field] = val

        # Parse price ranges into numeric low/high
        resale_low, resale_high = parse_price_range(meta.get("resale_value_usd"))
        if resale_low is not None:
            update["resale_value_low"] = resale_low
            update["resale_value_high"] = resale_high

        retail_low, retail_high = parse_price_range(meta.get("retail_replacement_usd"))
        if retail_low is not None:
            update["retail_replacement_low"] = retail_low
            update["retail_replacement_high"] = retail_high

        ins_low, ins_high = parse_price_range(meta.get("insurance_replacement_usd"))
        if ins_low is not None:
            update["insurance_replacement_low"] = ins_low
            update["insurance_replacement_high"] = ins_high

        # Location (prefer scan table, fallback to JSON)
        scan_info = item.get("scans") or {}
        update["home_name"] = scan_info.get("home_name") or meta.get("home", "My House")
        update["room_name"] = scan_info.get("room_name") or meta.get("room", "General Room")

        if not update:
            skipped += 1
            continue

        try:
            supabase.table("items").update(update).eq("id", item["id"]).execute()
            updated += 1
            if updated % 25 == 0:
                print(f"  ... {updated} items updated")
        except Exception as e:
            print(f"  ERROR updating item {item['id']}: {e}")
            errors += 1

    print(f"\nBackfill complete:")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")


if __name__ == "__main__":
    main()
