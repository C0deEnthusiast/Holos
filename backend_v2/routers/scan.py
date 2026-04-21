"""
/v2/scan — Image upload + AI analysis (Agent 4)
Wraps scanner.analyze_room() with FastAPI UploadFile handling.
"""
import os
import uuid
import mimetypes
import tempfile
from typing import Optional, List, Tuple

import structlog
from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from PIL import Image

from backend_v2.deps import CurrentUser, SupabaseDep
from backend_v2.models import ScanResponse, ScanResultItem
import scanner
from scanner import GeminiQuotaError, GeminiUnavailableError, GeminiScanError
from schemas import ParseError

router = APIRouter(tags=["Scan"])
log = structlog.get_logger("holos.v2.scan")

AUTO_SAVE_THRESHOLD = 0.75


def _cents_range(low: int | None, high: int | None) -> str:
    if not low and not high:
        return "N/A"
    return f"${(low or 0) / 100:,.0f}–${(high or 0) / 100:,.0f}"


def _upload_to_storage(supabase, local_path: str, storage_path: str) -> str | None:
    try:
        with open(local_path, "rb") as f:
            supabase.storage.from_("scans").upload(storage_path, f)
        return supabase.storage.from_("scans").get_public_url(storage_path)
    except Exception as e:
        log.error("storage_upload_failed", error=str(e))
        return None


def get_refined_thumbnail(image_path: str, name: str, box: List[float], temp_dir: str) -> Tuple[str | None, str | None]:
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            ymin, xmin, ymax, xmax = box
            left, top, right, bottom = xmin * w / 1000, ymin * h / 1000, xmax * w / 1000, ymax * h / 1000
            crop = img.crop((left, top, right, bottom))
            thumb_path = os.path.join(temp_dir, f"thumb_{uuid.uuid4().hex[:8]}.jpg")
            crop.save(thumb_path, "JPEG")
            return thumb_path, None
    except Exception as e:
        log.error("thumbnail_crop_failed", error=str(e))
        return None, None


@router.post("/scan", response_model=ScanResponse)
async def scan_image(
    user_id: CurrentUser,
    supabase: SupabaseDep,
    image: UploadFile = File(...),
    home_name: str = Form("My Home"),
    room_name: str = Form("General Room"),
    user_notes: Optional[str] = Form(None),
):
    temp_dir = "uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_id = uuid.uuid4().hex[:8]
    image_path = os.path.join(temp_dir, f"scan_{temp_id}_{image.filename}")
    
    with open(image_path, "wb") as buffer:
        buffer.write(await image.read())

    scan_id: str | None = None
    room_url: str | None = None

    if supabase:
        storage_path = f"room_{temp_id}_{image.filename}"
        room_url = _upload_to_storage(supabase, image_path, storage_path)
        try:
            sr = supabase.table("scans").insert({
                "user_id": user_id,
                "status": "processing",
                "original_image_url": room_url,
                "home_name": home_name,
                "room_name": room_name,
            }).execute()
            if sr.data:
                scan_id = sr.data[0]["id"]
        except Exception as e:
            log.warning("scan_record_failed", error=str(e))

    try:
        items = scanner.analyze_room(image_path, user_notes=user_notes, user_id=user_id, scan_id=scan_id)
    except ParseError as e:
        _cleanup(image_path, scan_id, supabase)
        raise HTTPException(status_code=422, detail=f"AI parse error: {e}")
    except GeminiQuotaError as e:
        _cleanup(image_path, scan_id, supabase)
        raise HTTPException(status_code=429, detail=f"Quota: {e}")
    except (GeminiUnavailableError, GeminiScanError) as e:
        _cleanup(image_path, scan_id, supabase)
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")
    except Exception as e:
        _cleanup(image_path, scan_id, supabase)
        raise HTTPException(status_code=500, detail=str(e))

    if scan_id:
        try:
            supabase.table("scans").update({"status": "completed"}).eq("id", scan_id).execute()
        except Exception:
            pass

    all_results: list[ScanResultItem] = []
    auto_saved: list[ScanResultItem] = []
    needs_review: list[ScanResultItem] = []

    for item in items:
        d = item.to_scan_dict()
        
        thumb_url = None
        rough_box = list(item.bounding_box) if item.bounding_box else []
        if rough_box and supabase:
            thumb_path, _ = get_refined_thumbnail(image_path, d.get("name", ""), rough_box, temp_dir)
            if thumb_path:
                storage_name = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
                thumb_url = _upload_to_storage(supabase, thumb_path, storage_name)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)

        d.update({
            "item_name": item.item_name,
            "home_name": home_name,
            "room_name": room_name,
            "resale_display":    _cents_range(item.value_resale_low_cents, item.value_resale_high_cents),
            "retail_display":    _cents_range(item.value_retail_replacement_low_cents, item.value_retail_replacement_high_cents),
            "insurance_display": _cents_range(item.value_insurance_replacement_low_cents, item.value_insurance_replacement_high_cents),
            "resale_low_cents":                   item.value_resale_low_cents,
            "resale_high_cents":                  item.value_resale_high_cents,
            "retail_replacement_low_cents":        item.value_retail_replacement_low_cents,
            "retail_replacement_high_cents":       item.value_retail_replacement_high_cents,
            "insurance_replacement_low_cents":     item.value_insurance_replacement_low_cents,
            "insurance_replacement_high_cents":    item.value_insurance_replacement_high_cents,
            "thumbnail_url":                       thumb_url,
            "original_image_url":                  room_url,
        })

        confidence = float(d.get("identification_confidence", 0))

        if confidence >= AUTO_SAVE_THRESHOLD and supabase:
            try:
                payload = {
                    "user_id":                       user_id,
                    "scan_id":                        scan_id,
                    "name":                           d.get("name"),
                    "category":                       d.get("category"),
                    "brand":                          d.get("brand") or d.get("make"),
                    "model":                          d.get("model"),
                    "condition":                      d.get("condition"),
                    "condition_confidence":            d.get("condition_confidence"),
                    "condition_evidence":              d.get("condition_evidence"),
                    "identification_confidence":       confidence,
                    "identification_basis":            d.get("identification_basis"),
                    "resale_low_cents":                item.value_resale_low_cents,
                    "resale_high_cents":               item.value_resale_high_cents,
                    "retail_replacement_low_cents":    item.value_retail_replacement_low_cents,
                    "retail_replacement_high_cents":   item.value_retail_replacement_high_cents,
                    "insurance_replacement_low_cents": item.value_insurance_replacement_low_cents,
                    "insurance_replacement_high_cents":item.value_insurance_replacement_high_cents,
                    "pricing_rationale":               d.get("pricing_rationale"),
                    "bounding_box":                    list(item.bounding_box),
                    "bounding_box_coordinate_system":  "yxyx_1000",
                    "flags":                           item.flags,
                    "thumbnail_url":                   thumb_url,
                    "original_image_url":              room_url,
                    "home_name":                       home_name,
                    "room_name":                       room_name,
                    "is_archived":                     False,
                    "user_confirmed":                  False,
                    "ai_model_id":                     scanner.VISION_MODEL,
                }
                res = supabase.table("items").insert(payload).execute()
                if res.data:
                    d["id"] = res.data[0]["id"]
                    d["auto_saved"] = True
            except Exception as e:
                log.error("auto_save_failed", name=d.get("name"), error=str(e))
                d["auto_saved"] = False
        else:
            d["auto_saved"] = False

        result_item = ScanResultItem(**{k: v for k, v in d.items() if k in ScanResultItem.model_fields})
        all_results.append(result_item)
        if d.get("auto_saved"):
            auto_saved.append(result_item)
        else:
            needs_review.append(result_item)

    if os.path.exists(image_path):
        os.remove(image_path)

    return ScanResponse(
        data=all_results,
        auto_saved=auto_saved,
        needs_review=needs_review,
        summary={
            "total": len(all_results),
            "auto_saved_count": len(auto_saved),
            "needs_review_count": len(needs_review),
            "threshold": AUTO_SAVE_THRESHOLD,
        },
    )


def _cleanup(filepath: str, scan_id: str | None, supabase) -> None:
    if os.path.exists(filepath):
        os.remove(filepath)
    if scan_id and supabase:
        try:
            supabase.table("scans").update({"status": "failed"}).eq("id", scan_id).execute()
        except Exception:
            pass
