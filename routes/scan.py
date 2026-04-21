"""
Scan Routes — Agent 2 Wired
Handles image uploads, AI room analysis, and Sniper Mode thumbnail refinement.

Changes from prototype:
- scanner.analyze_room() now returns list[ItemEstimate] (not a JSON string)
- Deleted .replace('```json','') and json.loads() — ParseError raised instead
- to_db_dict() maps ItemEstimate fields to §6 column names (cents, not strings)
- maintenance_note column removed — no longer written
- confidence threshold now uses identification_confidence (0.0-1.0 float)
- structlog throughout
"""
import os
import uuid
import mimetypes

import structlog
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from PIL import Image

import scanner
from scanner import GeminiQuotaError, GeminiUnavailableError, GeminiScanError
from schemas import ItemEstimate, ParseError
from image_search import enrich_items_with_images
from config import Config
from routes.auth import get_current_user_id

scan_bp = Blueprint("scan", __name__, url_prefix="/api")
log = structlog.get_logger("holos.scan")


def get_supabase():
    from app import supabase
    return supabase


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def compute_blur_score(filepath: str) -> float:
    """
    Laplacian-variance blur score via PIL.
    Higher = sharper. Score < 25 is too blurry.
    """
    from PIL import ImageFilter
    with Image.open(filepath) as img:
        img.thumbnail((512, 512))
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        pixels = list(edges.getdata())
        if len(pixels) < 100:
            return 999.0
        mean = sum(pixels) / len(pixels)
        return sum((p - mean) ** 2 for p in pixels) / len(pixels)


def get_refined_thumbnail(
    original_path: str,
    item_name: str,
    rough_box: list[int],
    upload_folder: str,
) -> tuple[str | None, list[int]]:
    """Crops the original image using the bounding box with natural aspect ratio."""
    try:
        with Image.open(original_path) as img:
            width, height = img.size
            if not rough_box or len(rough_box) != 4:
                return None, rough_box

            b0, b1, b2, b3 = rough_box
            ymin, ymax = sorted([b0, b2])
            xmin, xmax = sorted([b1, b3])

            left   = (xmin / 1000) * width
            top    = (ymin / 1000) * height
            right  = (xmax / 1000) * width
            bottom = (ymax / 1000) * height

            pad    = 0.12
            w      = right - left
            h      = bottom - top
            left   = max(0, left   - w * pad)
            top    = max(0, top    - h * pad)
            right  = min(width,  right  + w * pad)
            bottom = min(height, bottom + h * pad)

            # Square crop for consistent thumbnails
            size   = max(right - left, bottom - top)
            cx     = (left + right) / 2
            cy     = (top + bottom) / 2
            left   = max(0, cx - size / 2)
            top    = max(0, cy - size / 2)
            right  = min(width,  left + size)
            bottom = min(height, top  + size)

            cropped = img.crop((left, top, right, bottom))
            cropped.thumbnail((512, 512), Image.LANCZOS)

            # Square pad to 512×512
            thumb = Image.new("RGB", (512, 512), (248, 248, 248))
            offset = ((512 - cropped.width) // 2, (512 - cropped.height) // 2)
            thumb.paste(cropped, offset)

            thumb_filename = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
            thumb_path     = os.path.join(upload_folder, thumb_filename)
            thumb.save(thumb_path, "JPEG", quality=88, optimize=True)

            refined = [
                int(ymin + (b2 - b0) * pad * 500),
                int(xmin + (b3 - b1) * pad * 500),
                int(ymax - (b2 - b0) * pad * 500),
                int(xmax - (b3 - b1) * pad * 500),
            ]
            return thumb_path, refined

    except Exception as e:
        log.warning("thumbnail_crop_failed", item=item_name, error=str(e))
        return None, rough_box


def _upload_to_storage(supabase, local_path: str, storage_path: str) -> str | None:
    """Upload a file to Supabase Storage and return its public URL."""
    try:
        content_type, _ = mimetypes.guess_type(local_path)
        content_type = content_type or "image/jpeg"
        supabase.storage.from_("scans").upload(
            path=storage_path,
            file=local_path,
            file_options={"content-type": content_type},
        )
        return supabase.storage.from_("scans").get_public_url(storage_path)
    except Exception as e:
        log.error("storage_upload_failed", path=storage_path, error=str(e))
        return None


# ---------------------------------------------------------------------------
# Auto-save threshold — 0.0-1.0 float (was 0-100 int)
# §8.6: items with identification_confidence >= 0.75 are auto-saved
# ---------------------------------------------------------------------------
AUTO_SAVE_THRESHOLD = 0.75


def _item_to_db_payload(
    item: ItemEstimate,
    *,
    user_id: str,
    scan_id: str | None,
    home_name: str,
    room_name: str,
    original_image_url: str | None,
    thumbnail_url: str | None,
) -> dict:
    """
    Build the DB insert payload from a validated ItemEstimate.
    Uses §6 column names (cents integers) — no string price ranges.
    No maintenance_note — that column was dropped in migration 003.
    """
    db = item.to_db_dict()
    db.update({
        "user_id": user_id,
        "scan_id": scan_id,
        "home_name": home_name,
        "room_name": room_name,
        "original_image_url": original_image_url,
        "thumbnail_url": thumbnail_url,
        "is_archived": False,
        "user_confirmed": False,
        "ai_model_id": scanner.VISION_MODEL,
    })
    return db


# ---------------------------------------------------------------------------
# Scan Endpoint
# ---------------------------------------------------------------------------

@scan_bp.route("/scan", methods=["POST"])
def scan_image():
    if "image" not in request.files:
        return jsonify({"error": "No image in request"}), 400

    files = request.files.getlist("image")
    if not files or files[0].filename == "":
        return jsonify({"error": "No files selected"}), 400

    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    home_name  = request.form.get("home_name", "My Home")
    room_name  = request.form.get("room_name", "General Room")
    user_notes = request.form.get("user_notes", "").strip() or None
    supabase   = get_supabase()

    all_results: list[dict] = []
    errors: list[str] = []

    # One scan DB record for all photos in this batch
    scan_id: str | None = None

    for file in files:
        if not file or not allowed_file(file.filename):
            continue

        filename = secure_filename(file.filename)
        filepath = os.path.join(Config.UPLOAD_FOLDER, filename)
        file.save(filepath)

        # ── 1. Upload room photo ──────────────────────────────
        room_url: str | None = None
        if supabase:
            storage_path = f"room_{uuid.uuid4().hex[:8]}_{filename}"
            room_url = _upload_to_storage(supabase, filepath, storage_path)
            if room_url:
                log.info("room_image_uploaded", url=room_url)

        # ── 2. Blur detection ─────────────────────────────────
        try:
            blur = compute_blur_score(filepath)
            if blur < 25:
                errors.append(f"'{filename}' is too blurry (score: {blur:.0f}). Retake with better focus.")
                log.warning("blur_rejected", file=filename, score=blur)
                if os.path.exists(filepath):
                    os.remove(filepath)
                continue
        except Exception as e:
            log.warning("blur_check_skipped", file=filename, error=str(e))

        # ── 3. AI Room Analysis (returns list[ItemEstimate]) ─────
        try:
            items: list[ItemEstimate] = scanner.analyze_room(
                filepath,
                user_notes=user_notes,
                user_id=user_id,
            )
            log.info("scan_items_identified", count=len(items), file=filename)

        except ParseError as e:
            log.error("scan_parse_error", file=filename, error=str(e))
            errors.append(f"AI returned invalid JSON: {e}")
            continue
        except (GeminiQuotaError, GeminiUnavailableError) as e:
            log.warning("scan_quota_or_unavailable", error=str(e))
            errors.append(f"AI service temporarily unavailable: {type(e).__name__}")
            continue
        except GeminiScanError as e:
            log.error("scan_gemini_error", file=filename, error=str(e))
            errors.append(f"Scan failed: {e}")
            continue
        except Exception as e:
            log.error("scan_unexpected_error", file=filename, error=str(e))
            errors.append(str(e))
            continue
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

        # ── 4. Create scan DB record (once per batch) ─────────
        if scan_id is None and supabase and items:
            try:
                scan_res = supabase.table("scans").insert({
                    "user_id": user_id,
                    "status": "completed",
                    "original_image_url": room_url,
                    "home_name": home_name,
                    "room_name": room_name,
                }).execute()
                if scan_res.data:
                    scan_id = scan_res.data[0]["id"]
                    log.info("scan_record_created", scan_id=scan_id)
            except Exception as e:
                log.warning("scan_record_failed", error=str(e))

        # ── 5. Sniper Mode: thumbnail per item ────────────────
        for i, item in enumerate(items):
            thumb_url: str | None = None
            rough_box = list(item.bounding_box) if item.bounding_box else []

            if Config.ENABLE_SNIPER_MODE and rough_box and supabase:
                thumb_path, refined_box = get_refined_thumbnail(
                    filepath if os.path.exists(filepath) else "",
                    item.item_name, rough_box, Config.UPLOAD_FOLDER
                )
                if thumb_path:
                    storage_name = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
                    thumb_url = _upload_to_storage(supabase, thumb_path, storage_name)
                    if os.path.exists(thumb_path):
                        os.remove(thumb_path)
                    if thumb_url:
                        log.info("thumbnail_uploaded", item=item.item_name, idx=i)

            # ── 6. Build scan_dict (backward-compat for frontend) ──
            item_dict = item.to_scan_dict()
            item_dict.update({
                "original_image_url": room_url,
                "thumbnail_url": thumb_url,
                "home_name": home_name,
                "room_name": room_name,
            })

            all_results.append(item_dict)

    # ── 7. Web image fallback enrichment ─────────────────────────
    try:
        all_results = enrich_items_with_images(all_results)
    except Exception as e:
        log.warning("image_enrichment_failed", error=str(e))

    if not all_results and errors:
        return jsonify({"error": "Failed to process any items.", "details": errors}), 500

    # ── 8. Smart auto-save: split by confidence ───────────────────
    auto_saved: list[dict] = []
    needs_review: list[dict] = []

    for item_dict in all_results:
        confidence = float(item_dict.get("identification_confidence", 0))

        if confidence >= AUTO_SAVE_THRESHOLD and user_id and supabase:
            try:
                # Re-validate back to ItemEstimate to use to_db_dict()
                # item_dict has all the fields we need
                payload = {
                    "user_id": user_id,
                    "scan_id": scan_id,
                    "name": item_dict.get("name"),
                    "category": item_dict.get("category"),
                    "brand": item_dict.get("brand") or item_dict.get("make"),
                    "model": item_dict.get("model"),
                    "quantity": item_dict.get("quantity", 1),
                    "is_set": item_dict.get("is_set", False),
                    "condition": item_dict.get("condition"),
                    "condition_confidence": item_dict.get("condition_confidence"),
                    "condition_evidence": item_dict.get("condition_evidence"),
                    "identification_confidence": confidence,
                    "identification_basis": item_dict.get("identification_basis"),
                    "resale_low_cents": item_dict.get("resale_low_cents", 0),
                    "resale_high_cents": item_dict.get("resale_high_cents", 0),
                    "retail_replacement_low_cents": item_dict.get("retail_replacement_low_cents", 0),
                    "retail_replacement_high_cents": item_dict.get("retail_replacement_high_cents", 0),
                    "insurance_replacement_low_cents": item_dict.get("insurance_replacement_low_cents", 0),
                    "insurance_replacement_high_cents": item_dict.get("insurance_replacement_high_cents", 0),
                    "pricing_rationale": item_dict.get("pricing_rationale"),
                    "bounding_box": item_dict.get("bounding_box"),
                    "bounding_box_coordinate_system": "yxyx_1000",
                    "flags": item_dict.get("flags", []),
                    "thumbnail_url": item_dict.get("thumbnail_url"),
                    "original_image_url": item_dict.get("original_image_url"),
                    "home_name": item_dict.get("home_name", home_name),
                    "room_name": item_dict.get("room_name", room_name),
                    "is_archived": False,
                    "user_confirmed": False,
                    "ai_model_id": scanner.VISION_MODEL,
                    "metadata": {"subcategory": item_dict.get("subcategory"),
                                 "color_material": item_dict.get("color_material"),
                                 "dimensions_estimate": item_dict.get("dimensions_estimate")},
                }

                res = supabase.table("items").insert(payload).execute()
                if res.data:
                    item_dict["id"] = res.data[0]["id"]
                    item_dict["auto_saved"] = True
                    auto_saved.append(item_dict)
                    log.info("auto_saved", name=item_dict.get("name"), confidence=f"{confidence:.0%}")
                else:
                    item_dict["auto_saved"] = False
                    needs_review.append(item_dict)

            except Exception as e:
                log.error("auto_save_failed", name=item_dict.get("name"), error=str(e))
                item_dict["auto_saved"] = False
                needs_review.append(item_dict)
        else:
            item_dict["auto_saved"] = False
            item_dict["review_reason"] = (
                f"Confidence {confidence:.0%} (threshold: {AUTO_SAVE_THRESHOLD:.0%})"
            )
            needs_review.append(item_dict)

    log.info("scan_complete", auto_saved=len(auto_saved), needs_review=len(needs_review))

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
        "errors": errors or None,
    })
