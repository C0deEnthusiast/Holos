"""
Async scan endpoint — Agent 4: Strangler-Fig FastAPI migration.

Key improvements over Flask routes/scan.py:
- Fully async: all blocking I/O and AI calls run in asyncio.to_thread()
- Structured error handling via FastAPI HTTPException
- No Flask context required — safe to run standalone via uvicorn

Functionality is identical to the Flask endpoint; this is a drop-in
replacement that can be validated before cutting over the reverse proxy.
"""
import asyncio
import json
import mimetypes
import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import scanner
from config import Config
from observability import get_logger, init_scan_cost, finalize_scan_cost
from backend_v2.dependencies import get_current_user_id, get_supabase

log = get_logger("backend_v2.scan", agent_id="4")

router = APIRouter(prefix="/api/v2", tags=["scan"])

AUTO_SAVE_THRESHOLD = 75


# ── Sync helpers (run inside asyncio.to_thread) ───────────────────────────────

def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def _upload_to_supabase(supabase, bucket: str, storage_path: str, local_path: str) -> str:
    """Upload a local file to Supabase Storage and return its public URL."""
    content_type, _ = mimetypes.guess_type(local_path)
    content_type = content_type or "image/jpeg"
    supabase.storage.from_(bucket).upload(
        path=storage_path,
        file=local_path,
        file_options={"content-type": content_type},
    )
    return supabase.storage.from_(bucket).get_public_url(storage_path)


def _crop_thumbnail(original_path: str, item_name: str, rough_box: list, upload_folder: str):
    """
    Crop a thumbnail from the original image using Gemini bounding-box coords.
    Identical to Flask routes/scan.py:get_refined_thumbnail().
    Returns (thumb_path_or_None, normalized_box).
    """
    from PIL import Image

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
        log.error("crop_error_v2", item_name=item_name, error=str(e))
        return None, rough_box


def _fetch_product_image_url(name: str, make=None, model=None) -> Optional[str]:
    """Web image fallback via Google Custom Search. Duplicated from routes/scan.py."""
    api_key = Config.GOOGLE_API_KEY
    cse_id = Config.GOOGLE_CSE_ID
    if not api_key or not cse_id:
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
        log.warning("web_image_search_failed_v2", item_name=name, error=str(e))
    return None


def _supabase_insert(supabase, table: str, payload: dict):
    return supabase.table(table).insert(payload).execute()


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/scan")
async def scan_image(
    image: UploadFile = File(...),
    home_name: str = Form(default="My Home"),
    room_name: str = Form(default="General Room"),
    user_notes: str = Form(default=""),
    user_id: Optional[str] = Depends(get_current_user_id),
):
    """
    Async room scan endpoint.

    Accepts a single room photo, runs Gemini identification in a thread,
    applies the deterministic pricing engine (schemas.py), crops thumbnails,
    uploads to Supabase Storage, and auto-saves high-confidence items.

    Returns the same JSON shape as POST /api/scan so clients need no changes.
    """
    init_scan_cost()

    allowed = Config.ALLOWED_EXTENSIONS
    filename = image.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Allowed: {', '.join(sorted(allowed))}",
        )

    upload_folder = Config.UPLOAD_FOLDER
    os.makedirs(upload_folder, exist_ok=True)

    tmp_name = f"v2_{uuid.uuid4().hex[:8]}_{filename}"
    filepath = os.path.join(upload_folder, tmp_name)

    # Read upload into memory then write to disk in a thread
    contents = await image.read()
    await asyncio.to_thread(_write_file, filepath, contents)

    supabase = get_supabase()
    room_url: Optional[str] = None

    try:
        # 1. Upload original room photo to Supabase Storage (blocking I/O → thread)
        if supabase:
            try:
                storage_path = f"room_{uuid.uuid4().hex[:8]}_{tmp_name}"
                room_url = await asyncio.to_thread(
                    _upload_to_supabase, supabase, "scans", storage_path, filepath
                )
                log.info("room_image_uploaded_v2", url=room_url)
            except Exception as e:
                log.error("room_upload_failed_v2", error=str(e))

        # 2. AI identification (blocking Gemini call → thread)
        notes = user_notes.strip() or None
        result_str = await asyncio.to_thread(scanner.analyze_room, filepath, notes)

        if result_str in ("QUOTA_EXHAUSTED", "API_UNAVAILABLE"):
            raise HTTPException(status_code=503, detail=f"AI service unavailable: {result_str}")

        cleaned = result_str.strip().replace("```json", "").replace("```", "").strip()
        try:
            items = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error("json_parse_failed_v2", error=str(e), raw=cleaned[:200])
            raise HTTPException(status_code=502, detail="AI returned invalid JSON")

        if not isinstance(items, list):
            items = [items]

        log.info("items_identified_v2", count=len(items))

        # 3. Per-item: metadata, sniper-mode crop, web fallback
        for i, item in enumerate(items):
            item["original_image_url"] = room_url
            item["home_name"] = home_name
            item["room_name"] = room_name

            rough_box = item.get("bounding_box")
            if Config.ENABLE_SNIPER_MODE and rough_box and supabase:
                thumb_path, refined_box = await asyncio.to_thread(
                    _crop_thumbnail, filepath, item.get("name", ""), rough_box, upload_folder
                )
                if thumb_path:
                    try:
                        thumb_storage = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
                        thumb_url = await asyncio.to_thread(
                            _upload_to_supabase, supabase, "scans", thumb_storage, thumb_path
                        )
                        item["thumbnail_url"] = thumb_url
                        item["bounding_box"] = refined_box
                        log.debug("thumbnail_uploaded_v2", index=i, url=thumb_url)
                    except Exception as e:
                        log.error("thumbnail_upload_failed_v2", index=i, error=str(e))
                    finally:
                        if thumb_path and os.path.exists(thumb_path):
                            os.remove(thumb_path)

            if not item.get("thumbnail_url"):
                web_url = await asyncio.to_thread(
                    _fetch_product_image_url,
                    item.get("name", ""),
                    item.get("make"),
                    item.get("model"),
                )
                if web_url:
                    item["thumbnail_url"] = web_url
                    item["thumbnail_source"] = "web"
                    log.debug("web_image_fallback_v2", item_name=item.get("name"))

        # 4. Smart auto-save: split by confidence threshold
        auto_saved = []
        needs_review = []

        for item in items:
            confidence = item.get("confidence_score", 0)
            if isinstance(confidence, str):
                try:
                    confidence = int(str(confidence).replace("%", "").strip())
                except (ValueError, TypeError):
                    confidence = 0

            if confidence >= AUTO_SAVE_THRESHOLD and user_id and supabase:
                try:
                    price_str = str(item.get("estimated_price_usd") or "0").replace("$", "").replace(",", "")
                    numbers = re.findall(r"[-+]?\d*\.?\d+", price_str)
                    price = float(numbers[0]) if numbers else 0.0

                    maintenance_note = json.dumps({
                        "home": home_name,
                        "room": room_name,
                        "make": item.get("make"),
                        "model": item.get("model"),
                        "quantity": item.get("quantity", 1),
                        "is_set": item.get("is_set", False),
                        "estimated_age_years": item.get("estimated_age_years"),
                        "condition_notes": item.get("condition_notes"),
                        "estimated_dimensions": item.get("estimated_dimensions"),
                        "bounding_box": item.get("bounding_box"),
                        "confidence_score": item.get("confidence_score"),
                        "unit_price_usd": item.get("unit_price_usd"),
                        "resale_value_usd": item.get("resale_value_usd"),
                        "retail_replacement_usd": item.get("retail_replacement_usd"),
                        "insurance_replacement_usd": item.get("insurance_replacement_usd"),
                        "price_basis": item.get("price_basis"),
                        "identification_basis": item.get("identification_basis"),
                    })
                    to_save = {
                        "user_id": user_id,
                        "name": item.get("name"),
                        "category": item.get("category"),
                        "make": item.get("make"),
                        "model": item.get("model"),
                        "estimated_dimensions": item.get("estimated_dimensions"),
                        "suggested_replacements": item.get("suggested_replacements"),
                        "estimated_price_usd": price,
                        "condition": item.get("condition"),
                        "thumbnail_url": item.get("thumbnail_url"),
                        "is_archived": False,
                        "maintenance_note": maintenance_note,
                    }

                    # Create scan record first to get scan_id
                    try:
                        scan_payload = {
                            "user_id": user_id,
                            "status": "auto_saved",
                            "original_image_url": item.get("original_image_url"),
                            "home_name": home_name,
                            "room_name": room_name,
                        }
                        scan_res = await asyncio.to_thread(
                            _supabase_insert, supabase, "scans", scan_payload
                        )
                        if scan_res.data:
                            to_save["scan_id"] = scan_res.data[0]["id"]
                    except Exception as scan_err:
                        log.warning("scan_record_failed_v2", error=str(scan_err))

                    res = await asyncio.to_thread(_supabase_insert, supabase, "items", to_save)
                    if res.data:
                        item["id"] = res.data[0]["id"]
                        item["auto_saved"] = True
                        auto_saved.append(item)
                        log.info("item_auto_saved_v2", name=item.get("name"), confidence=confidence)
                    else:
                        item["auto_saved"] = False
                        needs_review.append(item)

                except Exception as save_err:
                    log.error("auto_save_failed_v2", name=item.get("name"), error=str(save_err))
                    item["auto_saved"] = False
                    needs_review.append(item)
            else:
                item["auto_saved"] = False
                item["review_reason"] = f"Confidence {confidence}% (threshold: {AUTO_SAVE_THRESHOLD}%)"
                needs_review.append(item)
                reason = "low_confidence" if confidence < AUTO_SAVE_THRESHOLD else "no_auth"
                log.info("item_needs_review_v2", name=item.get("name"), confidence=confidence, reason=reason)

        total_cost = finalize_scan_cost()
        log.info(
            "scan_complete_v2",
            auto_saved=len(auto_saved),
            needs_review=len(needs_review),
            total_cost_cents=total_cost,
        )

        return {
            "success": True,
            "api_version": "v2",
            "data": items,
            "auto_saved": auto_saved,
            "needs_review": needs_review,
            "summary": {
                "total": len(items),
                "auto_saved_count": len(auto_saved),
                "needs_review_count": len(needs_review),
                "threshold": AUTO_SAVE_THRESHOLD,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error("scan_failed_v2", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
