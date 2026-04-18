"""
Scan Routes
Handles image uploads, AI room analysis, and Sniper Mode thumbnail refinement.
"""
import os
import json
import uuid
import mimetypes

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from PIL import Image

import scanner
from config import Config
from routes.auth import get_current_user_id

scan_bp = Blueprint("scan", __name__, url_prefix="/api")


def get_supabase():
    from app import supabase
    return supabase


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def get_refined_thumbnail(original_path, item_name, rough_box, upload_folder):
    """Robust fallback: crops the original image using the provided bounding box without making a second API call."""
    try:
        with Image.open(original_path) as img:
            width, height = img.size
            if not rough_box or len(rough_box) != 4:
                return None, rough_box
            
            # Gemini typically returns [ymin, xmin, ymax, xmax] scaled 0-1000.
            # We sort them to prevent inverted bounds exceptions
            b0, b1, b2, b3 = rough_box
            ymin, ymax = sorted([b0, b2])
            xmin, xmax = sorted([b1, b3])

            left = (xmin / 1000) * width
            top = (ymin / 1000) * height
            right = (xmax / 1000) * width
            bottom = (ymax / 1000) * height

            # Calculate object center and dimensions
            obj_width = right - left
            obj_height = bottom - top
            center_x = left + obj_width / 2
            center_y = top + obj_height / 2

            # Use the larger dimension + 15% padding to create a square
            max_dim = max(obj_width, obj_height) * 1.15
            half_dim = max_dim / 2

            crop_left = center_x - half_dim
            crop_top = center_y - half_dim
            crop_right = center_x + half_dim
            crop_bottom = center_y + half_dim

            # Try to shift the bounding box if it exceeds the image boundaries
            if crop_left < 0:
                crop_right -= crop_left  # shift right
                crop_left = 0
            if crop_top < 0:
                crop_bottom -= crop_top  # shift down
                crop_top = 0
                
            if crop_right > width:
                crop_left -= (crop_right - width)
                crop_right = width
            if crop_bottom > height:
                crop_top -= (crop_bottom - height)
                crop_bottom = height

            # Final safety clamp
            crop_left = max(0, crop_left)
            crop_top = max(0, crop_top)
            crop_right = min(width, crop_right)
            crop_bottom = min(height, crop_bottom)

            if crop_right <= crop_left or crop_bottom <= crop_top:
                return None, rough_box

            thumb_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
            
            if thumb_img.mode in ("RGBA", "P"):
                thumb_img = thumb_img.convert("RGB")
                
            # Guarantee a perfect square (if image was too small for shifting)
            cw, ch = thumb_img.size
            if cw != ch:
                sq_size = int(max(cw, ch))
                # Use a dark modern background that matches the app theme
                square_img = Image.new("RGB", (sq_size, sq_size), (15, 17, 21))
                paste_x = (sq_size - cw) // 2
                paste_y = (sq_size - ch) // 2
                square_img.paste(thumb_img, (paste_x, paste_y))
                thumb_img = square_img
                
            thumb_img.thumbnail((800, 800))
            
            thumb_name = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
            thumb_path = os.path.join(upload_folder, thumb_name)
            thumb_img.save(thumb_path, quality=85)

            return thumb_path, [ymin, xmin, ymax, xmax]
    except Exception as e:
        print(f"Crop Error: {e}")
        return None, rough_box


@scan_bp.route("/scan", methods=["POST"])
def scan_image():
    if "image" not in request.files:
        return jsonify({"error": "No image parts in the request"}), 400

    files = request.files.getlist("image")
    if len(files) == 0 or files[0].filename == "":
        return jsonify({"error": "No selected files"}), 400

    all_results = []
    errors = []
    user_id = get_current_user_id()
    home_name = request.form.get("home_name", "My Home")
    room_name = request.form.get("room_name", "General Room")
    user_notes = request.form.get("user_notes", "").strip()
    supabase = get_supabase()
    upload_folder = Config.UPLOAD_FOLDER

    # Confidence threshold for auto-save (configurable)
    AUTO_SAVE_THRESHOLD = 75

    for file in files:
        if not file or not allowed_file(file.filename):
            continue

        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        # 1. Upload original room photo to Supabase Storage
        room_url = None
        if supabase:
            try:
                storage_path = f"room_{uuid.uuid4().hex[:8]}_{filename}"
                content_type, _ = mimetypes.guess_type(filepath)
                content_type = content_type or "image/jpeg"
                supabase.storage.from_("scans").upload(
                    path=storage_path,
                    file=filepath,
                    file_options={"content-type": content_type},
                )
                room_url = supabase.storage.from_("scans").get_public_url(storage_path)
                print(f"DEBUG: Room image uploaded: {room_url}")
            except Exception as e:
                print(f"ERROR: Room upload failed: {e}")

        # 2. Analyze room for items via Gemini
        try:
            result_str = scanner.analyze_room(filepath, user_notes=user_notes if user_notes else None)
            if result_str in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE"):
                errors.append(f"AI Service currently unavailable: {result_str}")
                continue

            cleaned = result_str.strip().replace("```json", "").replace("```", "").strip()
            items = json.loads(cleaned)
            if not isinstance(items, list):
                items = [items]
            print(f"DEBUG: Identified {len(items)} items in {filename}")

            # 3. Sniper Mode: Refine each item's crop
            for i, item in enumerate(items):
                item["original_image_url"] = room_url
                item["home_name"] = home_name
                item["room_name"] = room_name

                rough_box = item.get("bounding_box")
                if Config.ENABLE_SNIPER_MODE and rough_box:
                    thumb_path, refined_box = get_refined_thumbnail(
                        filepath, item["name"], rough_box, upload_folder
                    )
                    if thumb_path and supabase:
                        try:
                            thumb_storage = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
                            t_content_type, _ = mimetypes.guess_type(thumb_path)
                            t_content_type = t_content_type or "image/jpeg"
                            supabase.storage.from_("scans").upload(
                                path=thumb_storage,
                                file=thumb_path,
                                file_options={"content-type": t_content_type},
                            )
                            item["thumbnail_url"] = supabase.storage.from_("scans").get_public_url(thumb_storage)
                            item["bounding_box"] = refined_box
                            print(f"DEBUG: Thumbnail_{i} generated: {item['thumbnail_url']}")
                            if os.path.exists(thumb_path):
                                os.remove(thumb_path)
                        except Exception as thumb_err:
                            print(f"ERROR: Thumbnail_{i} upload failed: {thumb_err}")

            all_results.extend(items)
        except Exception as e:
            print(f"ERROR: Analysis failed for {filename}: {e}")
            errors.append(str(e))
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    if not all_results and errors:
        return jsonify({"error": "Failed to process any items.", "details": errors}), 500

    # ═══════════════════════════════════════════════════════
    # SMART AUTO-SAVE: split by confidence
    # ═══════════════════════════════════════════════════════
    auto_saved = []
    needs_review = []

    for item in all_results:
        confidence = item.get("confidence_score", 0)
        # Ensure it's a number
        if isinstance(confidence, str):
            try:
                confidence = int(confidence)
            except (ValueError, TypeError):
                confidence = 0

        if confidence >= AUTO_SAVE_THRESHOLD and user_id and supabase:
            # ── Auto-save this item to the database ──
            try:
                import re
                price_str = str(item.get("estimated_price_usd") or "0").replace("$", "").replace(",", "")
                numbers = re.findall(r"[-+]?\d*\.?\d+", price_str)
                price = float(numbers[0]) if numbers else 0.0

                to_save = {
                    "user_id": user_id,
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "make": item.get("make"),
                    "model": item.get("model"),
                    "estimated_price_usd": price,
                    "estimated_dimensions": item.get("estimated_dimensions"),
                    "condition": item.get("condition"),
                    "suggested_replacements": item.get("suggested_replacements"),
                    "bounding_box": item.get("bounding_box"),
                    "thumbnail_url": item.get("thumbnail_url"),
                    "is_archived": False,
                    "maintenance_note": json.dumps({
                        "home": item.get("home_name", "My House"),
                        "room": item.get("room_name", "General Room"),
                        "quantity": item.get("quantity", 1),
                        "is_set": item.get("is_set", False),
                        "estimated_age_years": item.get("estimated_age_years"),
                        "condition_notes": item.get("condition_notes"),
                        "unit_price_usd": item.get("unit_price_usd"),
                        "resale_value_usd": item.get("resale_value_usd"),
                        "retail_replacement_usd": item.get("retail_replacement_usd"),
                        "insurance_replacement_usd": item.get("insurance_replacement_usd"),
                        "price_basis": item.get("price_basis"),
                        "confidence_score": confidence,
                        "identification_basis": item.get("identification_basis"),
                        "auto_saved": True,
                    }),
                }

                # Create scan record for foreign key
                try:
                    scan_payload = {
                        "user_id": user_id,
                        "status": "auto_saved",
                        "original_image_url": item.get("original_image_url"),
                        "home_name": item.get("home_name", "My House"),
                        "room_name": item.get("room_name", "General Room"),
                    }
                    scan_res = supabase.table("scans").insert(scan_payload).execute()
                    if scan_res.data:
                        to_save["scan_id"] = scan_res.data[0]["id"]
                except Exception as scan_err:
                    print(f"NOTICE: Scan record creation failed: {scan_err}")

                res = supabase.table("items").insert(to_save).execute()
                if res.data:
                    saved_item = res.data[0]
                    item["id"] = saved_item["id"]
                    item["auto_saved"] = True
                    auto_saved.append(item)
                    print(f"  [OK] AUTO-SAVED: {item['name']} (confidence: {confidence}%)")
                else:
                    item["auto_saved"] = False
                    needs_review.append(item)
            except Exception as save_err:
                print(f"  [X] Auto-save failed for {item.get('name')}: {save_err}")
                item["auto_saved"] = False
                needs_review.append(item)
        else:
            # ── Below threshold → needs human review ──
            item["auto_saved"] = False
            reason = "low confidence" if confidence < AUTO_SAVE_THRESHOLD else "no auth"
            item["review_reason"] = f"Confidence {confidence}% (threshold: {AUTO_SAVE_THRESHOLD}%)"
            needs_review.append(item)
            print(f"  [!] NEEDS REVIEW: {item.get('name')} (confidence: {confidence}%, {reason})")

    print(f"\n[SUMMARY] Scan Summary: {len(auto_saved)} auto-saved, {len(needs_review)} need review")

    return jsonify({
        "success": True,
        "data": all_results,  # All items (backward compat)
        "auto_saved": auto_saved,
        "needs_review": needs_review,
        "summary": {
            "total": len(all_results),
            "auto_saved_count": len(auto_saved),
            "needs_review_count": len(needs_review),
            "threshold": AUTO_SAVE_THRESHOLD,
        },
        "errors": errors if errors else None,
    })

