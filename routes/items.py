"""
Item Routes
Handles saving, retrieving, updating, archiving items,
and generating AI resale listings.
"""
import json
import re
import time
import traceback

from flask import Blueprint, request, jsonify

import scanner
from routes.auth import get_current_user_id

items_bp = Blueprint("items", __name__, url_prefix="/api")


def get_supabase():
    from app import supabase
    return supabase


# ─── Save Item ──────────────────────────────────────────────

@items_bp.route("/items/save", methods=["POST"])
def save_item():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    supabase = get_supabase()

    try:
        # Parse price safely
        price_str = str(data.get("estimated_price_usd") or "0").replace("$", "").replace(",", "")
        try:
            numbers = re.findall(r"[-+]?\d*\.?\d+", price_str)
            price = float(numbers[0]) if numbers else 0.0
        except Exception:
            price = 0.0

        to_save = {
            "user_id": user_id,
            "name": data.get("name"),
            "category": data.get("category"),
            "make": data.get("make"),
            "model": data.get("model"),
            "estimated_price_usd": price,
            "estimated_dimensions": data.get("estimated_dimensions"),
            "condition": data.get("condition"),
            "suggested_replacements": data.get("suggested_replacements"),
            "bounding_box": data.get("bounding_box"),
            "thumbnail_url": data.get("thumbnail_url"),
            "is_archived": data.get("is_archived", False),
            # Store rich metadata + location in the JSON note column
            "maintenance_note": json.dumps({
                "home": data.get("home_name", "My House"),
                "room": data.get("room_name", "General Room"),
                # New rich fields from the v2 prompt
                "quantity": data.get("quantity", 1),
                "is_set": data.get("is_set", False),
                "estimated_age_years": data.get("estimated_age_years"),
                "condition_notes": data.get("condition_notes"),
                "unit_price_usd": data.get("unit_price_usd"),
                "resale_value_usd": data.get("resale_value_usd"),
                "retail_replacement_usd": data.get("retail_replacement_usd"),
                "insurance_replacement_usd": data.get("insurance_replacement_usd"),
                "price_basis": data.get("price_basis"),
                "confidence_score": data.get("confidence_score"),
                "identification_basis": data.get("identification_basis"),
            }),
        }

        # Create a Scan record for the foreign key link
        scan_payload = {
            "user_id": user_id,
            "status": "item_link",
            "original_image_url": data.get("original_image_url"),
            "home_name": data.get("home_name", "My House"),
            "room_name": data.get("room_name", "General Room"),
        }

        try:
            scan_res = supabase.table("scans").insert(scan_payload).execute()
            if scan_res.data:
                to_save["scan_id"] = scan_res.data[0]["id"]
            else:
                print("WARNING: Scan created but no ID returned.")
        except Exception as scan_err:
            print(f"NOTICE: Could not create scan record: {scan_err}. Saving item without link.")

        print(f"DEBUG: Saving item for user {user_id}")
        res = supabase.table("items").insert(to_save).execute()

        if not res.data:
            return jsonify({
                "error": "Item saved but no data returned. Check RLS policies.",
                "payload_sent": to_save,
            }), 400

        return jsonify({"success": True, "data": res.data[0]})

    except Exception as e:
        error_msg = str(e)
        print(f"ERROR IN SAVE_ITEM: {error_msg}")
        traceback.print_exc()

        # Friendly hints for common Supabase errors
        if "profiles" in error_msg and "violates foreign key constraint" in error_msg:
            hint = "You must create a profile for this user in the Supabase 'profiles' table first."
            return jsonify({"error": f"{error_msg}. {hint}"}), 400

        if "scan_id" in error_msg and "violates not-null constraint" in error_msg:
            hint = "Run this SQL: 'ALTER TABLE items ALTER COLUMN scan_id DROP NOT NULL;'"
            return jsonify({"error": f"{error_msg}. {hint}"}), 400

        return jsonify({"error": f"Failed to save: {error_msg}"}), 500


# ─── Get Items ──────────────────────────────────────────────

@items_bp.route("/items", methods=["GET"])
def get_user_items():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    query = request.args.get("q", "")
    show_archived = request.args.get("archived", "false").lower() == "true"
    supabase = get_supabase()

    try:
        items_query = supabase.table("items").select("*, scans(*)").eq("user_id", user_id)
        result = items_query.execute()
        data = result.data or []

        final_data = []
        for item in data:
            note = item.get("maintenance_note") or ""
            scan_info = item.get("scans") or {}

            # Determine archived status
            is_item_archived = (item.get("is_archived") is True) or (note == "[ARCHIVED]")
            item["is_archived"] = is_item_archived

            if show_archived != is_item_archived:
                continue

            # Resolve location (prefer scan table, fallback to JSON note)
            item["home_name"] = scan_info.get("home_name")
            item["room_name"] = scan_info.get("room_name")
            item["original_image_url"] = scan_info.get("original_image_url")

            if not item["home_name"] or not item["room_name"]:
                if note and note.startswith("{"):
                    try:
                        meta = json.loads(note)
                        item["home_name"] = item["home_name"] or meta.get("home")
                        item["room_name"] = item["room_name"] or meta.get("room")
                        # Unpack rich metadata fields
                        for key in [
                            "quantity", "is_set", "estimated_age_years",
                            "condition_notes", "unit_price_usd",
                            "resale_value_usd", "retail_replacement_usd",
                            "insurance_replacement_usd", "price_basis",
                            "confidence_score", "identification_basis",
                        ]:
                            if meta.get(key) is not None:
                                item[key] = meta[key]
                    except Exception:
                        pass
            else:
                # Even when location comes from scan, still unpack rich metadata
                if note and note.startswith("{"):
                    try:
                        meta = json.loads(note)
                        for key in [
                            "quantity", "is_set", "estimated_age_years",
                            "condition_notes", "unit_price_usd",
                            "resale_value_usd", "retail_replacement_usd",
                            "insurance_replacement_usd", "price_basis",
                            "confidence_score", "identification_basis",
                        ]:
                            if meta.get(key) is not None:
                                item[key] = meta[key]
                    except Exception:
                        pass

            item["home_name"] = item["home_name"] or "My House"
            item["room_name"] = item["room_name"] or "General Room"

            # Search filter (multi-word)
            if query:
                search_terms = query.lower().split()
                searchable = (
                    f"{item.get('name')} {item.get('category')} {item.get('make')} "
                    f"{item.get('model')} {item['home_name']} {item['room_name']}"
                ).lower()
                if not all(term in searchable for term in search_terms):
                    continue

            final_data.append(item)

        return jsonify({"success": True, "data": final_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── Update Item ────────────────────────────────────────────

@items_bp.route("/items/<item_id>/update", methods=["POST"])
def update_item_field(item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    supabase = get_supabase()
    try:
        res = supabase.table("items").update(data).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"success": True, "data": res.data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─── Archive / Unarchive ────────────────────────────────────

@items_bp.route("/items/<item_id>/archive", methods=["POST"])
def archive_item(item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    supabase = get_supabase()
    try:
        try:
            supabase.table("items").update({"is_archived": True}).eq("id", item_id).eq("user_id", user_id).execute()
        except Exception:
            supabase.table("items").update({"maintenance_note": "[ARCHIVED]"}).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@items_bp.route("/items/<item_id>/unarchive", methods=["POST"])
def unarchive_item(item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    supabase = get_supabase()
    try:
        if supabase:
            supabase.table("items").update({"is_archived": False}).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── AI Resale Listing ──────────────────────────────────────

@items_bp.route("/items/<item_id>/resale", methods=["GET"])
def get_resale_listing(item_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    supabase = get_supabase()
    try:
        res = supabase.table("items").select("*, scans(*)").eq("id", item_id).eq("user_id", user_id).execute()
        if not res.data:
            return jsonify({"error": "Item not found"}), 404

        item = res.data[0]
        scan_info = item.get("scans") or {}
        item["room_name"] = scan_info.get("room_name", "General")

        listing_str = scanner.generate_resale_listing(item)
        if listing_str:
            cleaned = listing_str.strip().replace("```json", "").replace("```", "").strip()
            listing_data = json.loads(cleaned)
            return jsonify({"success": True, "listing": listing_data})
        else:
            return jsonify({"error": "AI failed to generate listing"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ─── Estate Report ──────────────────────────────────────────

@items_bp.route("/reports/estate", methods=["GET"])
def generate_estate_report():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    supabase = get_supabase()
    try:
        res = supabase.table("items").select("*, scans(*)").eq("user_id", user_id).execute()
        items = res.data or []

        report = {}
        total_value = 0
        total_items = 0

        for item in items:
            if item.get("is_archived") is True:
                continue

            scan_info = item.get("scans") or {}
            home = scan_info.get("home_name") or "My Property"
            room = scan_info.get("room_name") or "General Areas"

            if home not in report:
                report[home] = {}
            if room not in report[home]:
                report[home][room] = {"items": [], "subtotal": 0, "total_insurance_value": 0}

            price = float(item.get("estimated_price_usd") or 0)
            
            # Unpack rich details
            rich_meta = {}
            note = item.get("maintenance_note")
            if note and str(note).startswith("{"):
                try:
                    rich_meta = json.loads(note)
                except:
                    pass

            report[home][room]["items"].append({
                "name": item.get("name"),
                "category": item.get("category"),
                "make": item.get("make"),
                "model": item.get("model"),
                "price": price,
                "resale_price_range": rich_meta.get("resale_value_usd", "N/A"),
                "retail_replacement_cost": rich_meta.get("retail_replacement_usd", "N/A"),
                "insurance_replacement_value": rich_meta.get("insurance_replacement_usd", "N/A"),
                "appraisal_basis": rich_meta.get("price_basis", "N/A"),
                "estimated_age": rich_meta.get("estimated_age_years", "Unknown"),
                "detailed_condition_notes": rich_meta.get("condition_notes", "None"),
                "thumbnail": item.get("thumbnail_url"),
                "condition": item.get("condition"),
            })
            report[home][room]["subtotal"] += price
            
            # Try to parse string insurance value, fallback to standard price + 15%
            ins_val_str = str(rich_meta.get("insurance_replacement_usd", "0")).replace("$", "").replace(",", "")
            try:
                numbers = re.findall(r"[-+]?\d*\.?\d+", ins_val_str)
                ins_price = float(numbers[-1]) if numbers else price * 1.15
            except:
                ins_price = price * 1.15

            report[home][room]["total_insurance_value"] += ins_price
            
            total_value += price
            total_items += 1

        return jsonify({
            "success": True,
            "report_date": time.strftime("%Y-%m-%d"),
            "owner_id": user_id,
            "total_market_value": round(total_value, 2),
            "total_items": total_items,
            "properties": report,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
