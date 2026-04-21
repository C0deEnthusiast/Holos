"""
Item Routes — Agent 2 Wired
Handles saving, retrieving, updating, archiving items,
and generating AI resale listings.

Changes from prototype:
- All price reading/writing uses §6 column names (*_cents integers)
- maintenance_note column removed (migration 003 dropped it)
- RICH_FIELDS updated to §6 column names
- Estate report uses *_cents columns for aggregation
- generate_resale_listing() updated to pass cents-based item data
- structlog throughout
"""
import re
import time

import structlog
from flask import Blueprint, request, jsonify

import scanner
from scanner import GeminiScanError
from image_search import search_product_image
from routes.auth import get_current_user_id

items_bp = Blueprint("items", __name__, url_prefix="/api")
log = structlog.get_logger("holos.items")


def get_supabase():
    from app import supabase
    return supabase


def _cents_to_display(cents: int | None) -> str:
    """Convert cents integer to display string like '$1,234'."""
    if not cents:
        return "N/A"
    return f"${cents / 100:,.0f}"


def _range_to_display(low_cents: int | None, high_cents: int | None) -> str:
    """Convert low/high cents to '$X,XXX–$Y,YYY' display string."""
    if not low_cents and not high_cents:
        return "N/A"
    if low_cents == high_cents:
        return _cents_to_display(low_cents)
    return f"${low_cents / 100:,.0f}–${high_cents / 100:,.0f}"


# ---------------------------------------------------------------------------
# Save Item
# ---------------------------------------------------------------------------

@items_bp.route("/items/save", methods=["POST"])
def save_item():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    supabase = get_supabase()

    try:
        # Accept either cents directly (from new scanner) or legacy USD floats
        def _to_cents(key_cents: str, key_usd: str | None = None) -> int:
            v = data.get(key_cents)
            if v is not None:
                return int(v)
            if key_usd:
                v = data.get(key_usd)
                if v is not None:
                    try:
                        cleaned = str(v).replace("$", "").replace(",", "")
                        nums = re.findall(r"[\d.]+", cleaned)
                        return int(float(nums[0]) * 100) if nums else 0
                    except Exception:
                        pass
            return 0

        to_save = {
            "user_id": user_id,
            "name": data.get("name") or data.get("item_name"),
            "category": data.get("category"),
            "brand": data.get("brand") or data.get("make"),
            "model": data.get("model"),
            "quantity": data.get("quantity", 1),
            "is_set": data.get("is_set", False),
            "condition": data.get("condition"),
            "condition_confidence": data.get("condition_confidence"),
            "condition_evidence": data.get("condition_evidence") or data.get("condition_notes"),
            "identification_confidence": data.get("identification_confidence"),
            "identification_basis": data.get("identification_basis"),
            "bounding_box": data.get("bounding_box"),
            "bounding_box_coordinate_system": data.get("bounding_box_coordinate_system", "yxyx_1000"),
            "flags": data.get("flags", []),
            "thumbnail_url": data.get("thumbnail_url"),
            "is_archived": data.get("is_archived", False),
            "user_confirmed": data.get("user_confirmed", False),
            "home_name": data.get("home_name", "My Home"),
            "room_name": data.get("room_name", "General Room"),
            "web_image_url": data.get("web_image_url"),
            "ai_model_id": data.get("ai_model_id"),
            "metadata": data.get("metadata", {}),
            "pricing_rationale": data.get("pricing_rationale") or data.get("price_basis"),

            # §6 pricing columns (cents)
            "resale_low_cents":                    _to_cents("resale_low_cents"),
            "resale_high_cents":                   _to_cents("resale_high_cents"),
            "retail_replacement_low_cents":         _to_cents("retail_replacement_low_cents"),
            "retail_replacement_high_cents":        _to_cents("retail_replacement_high_cents"),
            "insurance_replacement_low_cents":      _to_cents("insurance_replacement_low_cents"),
            "insurance_replacement_high_cents":     _to_cents("insurance_replacement_high_cents"),
        }

        # Link scan if provided
        scan_id = data.get("scan_id")
        if not scan_id and supabase:
            try:
                scan_res = supabase.table("scans").insert({
                    "user_id": user_id,
                    "status": "item_link",
                    "original_image_url": data.get("original_image_url"),
                    "home_name": to_save["home_name"],
                    "room_name": to_save["room_name"],
                }).execute()
                if scan_res.data:
                    scan_id = scan_res.data[0]["id"]
            except Exception as e:
                log.warning("scan_link_failed", error=str(e))
        if scan_id:
            to_save["scan_id"] = scan_id

        log.info("item_save", name=to_save["name"], user_id=user_id)
        res = supabase.table("items").insert(to_save).execute()

        if not res.data:
            return jsonify({"error": "Item saved but no data returned. Check RLS policies."}), 400

        return jsonify({"success": True, "data": res.data[0]})

    except Exception as e:
        log.error("save_item_failed", error=str(e))
        msg = str(e)
        if "profiles" in msg and "foreign key" in msg:
            return jsonify({"error": f"{msg}. Create a profile for this user first."}), 400
        return jsonify({"error": f"Failed to save: {msg}"}), 500


# ---------------------------------------------------------------------------
# Get Items
# ---------------------------------------------------------------------------

@items_bp.route("/items", methods=["GET"])
def get_user_items():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    query        = request.args.get("q", "")
    show_archived = request.args.get("archived", "false").lower() == "true"
    supabase     = get_supabase()

    try:
        result = (
            supabase.table("items")
            .select("*, scans(*)")
            .eq("user_id", user_id)
            .execute()
        )
        data = result.data or []

        final = []
        for item in data:
            scan_info = item.get("scans") or {}

            # Archived check
            is_archived = item.get("is_archived") is True
            item["is_archived"] = is_archived
            if show_archived != is_archived:
                continue

            # Location resolution: item column > scan table > default
            if not item.get("home_name") or item["home_name"] == "My House":
                item["home_name"] = scan_info.get("home_name") or "My Home"
            if not item.get("room_name") or item["room_name"] == "General Room":
                item["room_name"] = scan_info.get("room_name") or "General Room"

            item["original_image_url"] = (
                scan_info.get("original_image_url") or item.get("original_image_url")
            )

            # Add display-friendly price strings (computed from cents)
            item["resale_display"] = _range_to_display(
                item.get("resale_low_cents"), item.get("resale_high_cents")
            )
            item["retail_display"] = _range_to_display(
                item.get("retail_replacement_low_cents"), item.get("retail_replacement_high_cents")
            )
            item["insurance_display"] = _range_to_display(
                item.get("insurance_replacement_low_cents"), item.get("insurance_replacement_high_cents")
            )
            # Backward-compat alias: old UI reads confidence_score as 0-100 int
            id_conf = item.get("identification_confidence")
            if id_conf is not None:
                item["confidence_score"] = int(float(id_conf) * 100)

            # Make legacy 'make' field available if only 'brand' column exists
            item["make"] = item.get("brand") or item.get("make", "Unknown")

            # Search filter
            if query:
                terms = query.lower().split()
                searchable = (
                    f"{item.get('name')} {item.get('category')} "
                    f"{item.get('brand')} {item.get('model')} "
                    f"{item['home_name']} {item['room_name']}"
                ).lower()
                if not all(t in searchable for t in terms):
                    continue

            final.append(item)

        return jsonify({"success": True, "data": final})

    except Exception as e:
        log.error("get_items_failed", error=str(e))
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Update Item
# ---------------------------------------------------------------------------

@items_bp.route("/items/<item_id>/update", methods=["POST"])
def update_item_field(item_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    supabase = get_supabase()
    try:
        res = (
            supabase.table("items")
            .update(data)
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        return jsonify({"success": True, "data": res.data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Delete Item
# ---------------------------------------------------------------------------

@items_bp.route("/items/<item_id>", methods=["DELETE"])
def delete_item(item_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    supabase = get_supabase()
    try:
        # Check ownership before deleting
        check = (
            supabase.table("items")
            .select("id")
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not check.data:
            return jsonify({"error": "Not found"}), 404

        supabase.table("items").delete().eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Archive / Unarchive
# ---------------------------------------------------------------------------

@items_bp.route("/items/<item_id>/archive", methods=["POST"])
def archive_item(item_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    supabase = get_supabase()
    try:
        supabase.table("items").update({"is_archived": True}).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@items_bp.route("/items/<item_id>/unarchive", methods=["POST"])
def unarchive_item(item_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    supabase = get_supabase()
    try:
        supabase.table("items").update({"is_archived": False}).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# AI Resale Listing
# ---------------------------------------------------------------------------

@items_bp.route("/items/<item_id>/resale", methods=["GET"])
def get_resale_listing(item_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    supabase = get_supabase()
    try:
        res = (
            supabase.table("items")
            .select("*, scans(*)")
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            return jsonify({"error": "Item not found"}), 404

        item = res.data[0]
        scan_info = item.get("scans") or {}
        item["room_name"] = item.get("room_name") or scan_info.get("room_name", "General")
        item["make"] = item.get("brand") or item.get("make", "Unknown")

        listing_str = scanner.generate_resale_listing(item, user_id=user_id)
        if listing_str:
            import json
            try:
                listing_data = json.loads(listing_str.strip())
            except json.JSONDecodeError:
                listing_data = {"listing_description": listing_str}
            return jsonify({"success": True, "listing": listing_data})
        return jsonify({"error": "AI failed to generate listing"}), 500

    except GeminiScanError as e:
        log.error("resale_listing_ai_error", error=str(e))
        return jsonify({"error": f"AI error: {e}"}), 500
    except Exception as e:
        log.error("resale_listing_failed", error=str(e))
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Estate Report
# ---------------------------------------------------------------------------

@items_bp.route("/reports/estate", methods=["GET"])
def generate_estate_report():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    supabase = get_supabase()
    try:
        res = supabase.table("items").select("*, scans(*)").eq("user_id", user_id).execute()
        items = res.data or []

        report: dict = {}
        total_resale_cents = 0
        total_insurance_cents = 0
        total_items = 0

        for item in items:
            if item.get("is_archived") is True:
                continue

            scan_info = item.get("scans") or {}
            home = item.get("home_name") or scan_info.get("home_name") or "My Property"
            room = item.get("room_name") or scan_info.get("room_name") or "General Areas"

            report.setdefault(home, {})
            report[home].setdefault(room, {"items": [], "subtotal_resale": 0, "subtotal_insurance": 0})

            # Use cents columns directly (migration 001 added them)
            resale_mid   = ((item.get("resale_low_cents") or 0) + (item.get("resale_high_cents") or 0)) // 2
            insurance_mid = ((item.get("insurance_replacement_low_cents") or 0) +
                             (item.get("insurance_replacement_high_cents") or 0)) // 2

            report[home][room]["items"].append({
                "name":                      item.get("name"),
                "category":                  item.get("category"),
                "brand":                     item.get("brand") or item.get("make"),
                "model":                     item.get("model"),
                "condition":                 item.get("condition"),
                "condition_evidence":         item.get("condition_evidence") or item.get("condition_notes"),
                "resale_range":              _range_to_display(item.get("resale_low_cents"), item.get("resale_high_cents")),
                "retail_range":              _range_to_display(item.get("retail_replacement_low_cents"), item.get("retail_replacement_high_cents")),
                "insurance_range":           _range_to_display(item.get("insurance_replacement_low_cents"), item.get("insurance_replacement_high_cents")),
                "resale_midpoint":           round(resale_mid / 100, 2),
                "insurance_midpoint":        round(insurance_mid / 100, 2),
                "pricing_rationale":         item.get("pricing_rationale") or item.get("price_basis"),
                "identification_confidence": item.get("identification_confidence"),
                "thumbnail":                 item.get("thumbnail_url"),
            })

            report[home][room]["subtotal_resale"]    += resale_mid
            report[home][room]["subtotal_insurance"]  += insurance_mid
            total_resale_cents    += resale_mid
            total_insurance_cents += insurance_mid
            total_items += 1

        # Convert room subtotals to dollars for response
        for home_data in report.values():
            for room_data in home_data.values():
                room_data["subtotal_resale"]   = round(room_data["subtotal_resale"] / 100, 2)
                room_data["subtotal_insurance"] = round(room_data["subtotal_insurance"] / 100, 2)

        return jsonify({
            "success":              True,
            "report_date":          time.strftime("%Y-%m-%d"),
            "owner_id":             user_id,
            "total_items":          total_items,
            "total_resale_value":   round(total_resale_cents / 100, 2),
            "total_insurance_value": round(total_insurance_cents / 100, 2),
            "properties":           report,
        })

    except Exception as e:
        log.error("estate_report_failed", error=str(e))
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Web Image Search
# ---------------------------------------------------------------------------

@items_bp.route("/items/<item_id>/web-image", methods=["GET"])
def get_web_image(item_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    supabase = get_supabase()
    try:
        res = (
            supabase.table("items")
            .select("name, brand, model, category, web_image_url")
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            return jsonify({"error": "Item not found"}), 404

        item = res.data[0]
        if item.get("web_image_url"):
            return jsonify({"success": True, "web_image_url": item["web_image_url"], "cached": True})

        url = search_product_image(
            f"{item.get('brand', '')} {item.get('name', '')} {item.get('model', '')}".strip()
        )
        if url:
            supabase.table("items").update({"web_image_url": url}).eq("id", item_id).execute()
            return jsonify({"success": True, "web_image_url": url, "cached": False})
        return jsonify({"success": False, "error": "No web image found"}), 404

    except Exception as e:
        log.error("web_image_failed", item_id=item_id, error=str(e))
        return jsonify({"error": str(e)}), 500
