"""
Scan Routes
Handles image uploads, AI room analysis, and Sniper Mode thumbnail refinement.

Agent 0B: all logging via structlog. Scan cost is accumulated per-request via
init_scan_cost() / finalize_scan_cost() from observability.
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
from observability import get_logger, init_scan_cost, finalize_scan_cost

log = get_logger("scan", agent_id="0B")

scan_bp = Blueprint("scan", __name__, url_prefix="/api")


def get_supabase():
    from app import supabase
    return supabase


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def get_refined_thumbnail(original_path, item_name, rough_box, upload_folder):
    """Crops the original image using the provided bounding box. No second API call."""
    try:
        with Image.open(original_path) as img:
            width, height = img.size
            if not rough_box or len(rough_box) != 4:
                return None, rough_box

            # Gemini returns [ymin, xmin, ymax, xmax] scaled 0-1000
            b0, b1, b2, b3 = rough_box
            ymin, ymax = sorted([b0, b2])
            xmin, xmax = sorted([b1, b3])

            left   = (xmin / 1000) * width
            top    = (ymin / 1000) * height
            right  = (xmax / 1000) * width
            bottom = (ymax / 1000) * height

            pad = 0.15
            pad_x = (right - left) * pad
            pad_y = (bottom - top) * pad

            crop_left   = max(0, left - pad_x)
            crop_top    = max(0, top - pad_y)
            crop_right  = min(width, right + pad_x)
            crop_bottom = min(height, bottom + pad_y)

            if crop_right <= crop_left or crop_bottom <= crop_top:
                return None, rough_box

            thumb_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))

            if thumb_img.mode in ("RGBA", "P"):
                thumb_img = thumb_img.convert("RGB")

            # Always resize to 800px on longest side — upscale small crops for crispness
            cw, ch = thumb_img.size
            scale = min(800 / cw, 800 / ch)
            new_w = max(1, round(cw * scale))
            new_h = max(1, round(ch * scale))
            resample = Image.LANCZOS if scale < 1 else Image.BICUBIC
            thumb_img = thumb_img.resize((new_w, new_h), resample)

            thumb_name = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
            thumb_path = os.path.join(upload_folder, thumb_name)
            thumb_img.save(thumb_path, quality=85)

            return thumb_path, [ymin, xmin, ymax, xmax]
    except Exception as e:
        log.error("crop_error", item_name=item_name, error=str(e))
        return None, rough_box


def fetch_product_image_url(name, make=None, model=None):
    """Search Google Images for a product photo when no crop thumbnail is available."""
    api_key = Config.GOOGLE_API_KEY
    cse_id = Config.GOOGLE_CSE_ID
    if not api_key or not cse_id:
        log.debug("web_image_skip", reason="GOOGLE_API_KEY or GOOGLE_CSE_ID not set")
        return None
    try:
        import requests as req
        _junk = {"n/a", "unknown", "unidentified", "none", "", "—", "-"}

        def _clean(v):
            if not v:
                return None
            stripped = v.strip()
            return None if stripped.lower() in _junk or stripped.startswith("Unidentified") else stripped

        parts = [p for p in [_clean(make), _clean(model), name] if p]
        query = " ".join(parts) + " product photo"

        resp = req.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cse_id,
                "q": query,
                "searchType": "image",
                "num": 5,
                "imgType": "photo",
                "safe": "active",
            },
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        for item in items:
            url = item.get("link", "")
            if url and any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                return url
        if items:
            return items[0].get("link")
    except Exception as e:
        log.warning("web_image_search_failed", item_name=name, error=str(e))
    return None


@scan_bp.route("/scan", methods=["POST"])
def scan_image():
    init_scan_cost()  # reset per-request AI cost accumulator

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
                log.info("room_image_uploaded", url=room_url)
            except Exception as e:
                log.error("room_upload_failed", error=str(e))

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
            log.info("items_identified", filename=filename, count=len(items))

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
                            log.debug("thumbnail_uploaded", index=i, url=item["thumbnail_url"])
                        except Exception as thumb_err:
                            log.error("thumbnail_upload_failed", index=i, error=str(thumb_err))
                        finally:
                            if thumb_path and os.path.exists(thumb_path):
                                os.remove(thumb_path)

                # 4. Web image fallback
                if not item.get("thumbnail_url"):
                    web_url = fetch_product_image_url(
                        item.get("name", ""),
                        item.get("make"),
                        item.get("model"),
                    )
                    if web_url:
                        item["thumbnail_url"] = web_url
                        item["thumbnail_source"] = "web"
                        log.debug("web_image_fallback_used", item_name=item.get("name"))
                    else:
                        log.debug("no_fallback_image", item_name=item.get("name"))

            all_results.extend(items)
        except Exception as e:
            log.error("analysis_failed", filename=filename, error=str(e))
            errors.append(str(e))
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    if not all_results and errors:
        return jsonify({"error": "Failed to process any items.", "details": errors}), 500

    # ── Smart Auto-Save: split by confidence ─────────────────
    auto_saved = []
    needs_review = []

    for item in all_results:
        confidence = item.get("confidence_score", 0)
        if isinstance(confidence, str):
            try:
                # Strip % if present (e.g. "75%" → 75)
                confidence = int(str(confidence).replace("%", "").strip())
            except (ValueError, TypeError):
                confidence = 0

        if confidence >= AUTO_SAVE_THRESHOLD and user_id and supabase:
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
                    log.warning("scan_record_creation_failed", error=str(scan_err))

                res = supabase.table("items").insert(to_save).execute()
                if res.data:
                    saved_item = res.data[0]
                    item["id"] = saved_item["id"]
                    item["auto_saved"] = True
                    auto_saved.append(item)
                    log.info("item_auto_saved", name=item["name"], confidence=confidence)
                else:
                    item["auto_saved"] = False
                    needs_review.append(item)
            except Exception as save_err:
                log.error("auto_save_failed", name=item.get("name"), error=str(save_err))
                item["auto_saved"] = False
                needs_review.append(item)
        else:
            item["auto_saved"] = False
            reason = "low_confidence" if confidence < AUTO_SAVE_THRESHOLD else "no_auth"
            item["review_reason"] = f"Confidence {confidence}% (threshold: {AUTO_SAVE_THRESHOLD}%)"
            needs_review.append(item)
            log.info("item_needs_review", name=item.get("name"), confidence=confidence, reason=reason)

    total_cost = finalize_scan_cost()
    log.info(
        "scan_summary",
        auto_saved=len(auto_saved),
        needs_review=len(needs_review),
        total_cost_cents=total_cost,
    )

    return jsonify({
        "success": True,
        "data": all_results,
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


@scan_bp.route("/image-search", methods=["GET"])
def image_search():
    name = request.args.get("q", "").strip()
    make = request.args.get("make", "").strip() or None
    model = request.args.get("model", "").strip() or None
    if not name:
        return jsonify({"error": "Missing query parameter 'q'"}), 400
    url = fetch_product_image_url(name, make, model)
    if url:
        return jsonify({"url": url})
    return jsonify({"url": None, "error": "No image found"}), 404
