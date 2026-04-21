"""
/v2/items — CRUD endpoints (Agent 4)
Full §6 schema: cents pricing, typed response models, fail-closed auth.
"""
import time
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query

from backend_v2.deps import CurrentUser, SupabaseDep
from backend_v2.models import (
    ItemResponse, ItemsListResponse, SaveItemRequest, EstateReportResponse,
)

router = APIRouter(tags=["Items"])
log = structlog.get_logger("holos.v2.items")


def _cents_range(low: int | None, high: int | None) -> str:
    if not low and not high:
        return "N/A"
    if low == high:
        return f"${(low or 0) / 100:,.0f}"
    return f"${(low or 0) / 100:,.0f}–${(high or 0) / 100:,.0f}"


def _enrich(item: dict) -> dict:
    """Add display strings and backward-compat aliases."""
    item["resale_display"]    = _cents_range(item.get("resale_low_cents"), item.get("resale_high_cents"))
    item["retail_display"]    = _cents_range(item.get("retail_replacement_low_cents"), item.get("retail_replacement_high_cents"))
    item["insurance_display"] = _cents_range(item.get("insurance_replacement_low_cents"), item.get("insurance_replacement_high_cents"))
    item.setdefault("name", item.get("name", ""))
    item.setdefault("flags", [])
    return item


# ---------------------------------------------------------------------------
# GET /v2/items
# ---------------------------------------------------------------------------

@router.get("/items", response_model=ItemsListResponse)
def list_items(
    user_id: CurrentUser,
    supabase: SupabaseDep,
    q: Optional[str] = Query(None),
    archived: bool = Query(False),
    room: Optional[str] = Query(None),
):
    try:
        result = (
            supabase.table("items")
            .select("*, scans(*)")
            .eq("user_id", user_id)
            .execute()
        )
        data = result.data or []
    except Exception as e:
        log.error("list_items_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    output = []
    for item in data:
        scan_info = item.get("scans") or {}
        is_archived = item.get("is_archived") is True
        if archived != is_archived:
            continue

        # Location resolution
        item["home_name"] = item.get("home_name") or scan_info.get("home_name") or "My Home"
        item["room_name"] = item.get("room_name") or scan_info.get("room_name") or "General Room"
        item["original_image_url"] = item.get("original_image_url") or scan_info.get("original_image_url")

        _enrich(item)

        # Room filter
        if room and item["room_name"].lower() != room.lower():
            continue

        # Search filter
        if q:
            searchable = (
                f"{item.get('name')} {item.get('category')} "
                f"{item.get('brand')} {item.get('model')} "
                f"{item['home_name']} {item['room_name']}"
            ).lower()
            if not all(t in searchable for t in q.lower().split()):
                continue

        output.append(item)

    return ItemsListResponse(data=output, total=len(output))


# ---------------------------------------------------------------------------
# POST /v2/items/save
# ---------------------------------------------------------------------------

@router.post("/items/save", response_model=dict, status_code=201)
def save_item(
    body: SaveItemRequest,
    user_id: CurrentUser,
    supabase: SupabaseDep,
):
    payload = body.model_dump()
    payload["user_id"] = user_id
    payload.setdefault("is_archived", False)
    payload.setdefault("user_confirmed", False)

    # Create scan link if not provided
    if not payload.get("scan_id"):
        try:
            sr = supabase.table("scans").insert({
                "user_id": user_id,
                "status": "item_link",
                "home_name": payload.get("home_name", "My Home"),
                "room_name": payload.get("room_name", "General Room"),
            }).execute()
            if sr.data:
                payload["scan_id"] = sr.data[0]["id"]
        except Exception as e:
            log.warning("scan_link_failed", error=str(e))

    try:
        res = supabase.table("items").insert(payload).execute()
        if not res.data:
            raise HTTPException(status_code=400, detail="Item saved but no data returned")
        return {"success": True, "data": _enrich(res.data[0])}
    except HTTPException:
        raise
    except Exception as e:
        log.error("save_item_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /v2/items/{item_id}
# ---------------------------------------------------------------------------

@router.get("/items/{item_id}", response_model=dict)
def get_item(item_id: str, user_id: CurrentUser, supabase: SupabaseDep):
    try:
        res = (
            supabase.table("items")
            .select("*, scans(*)")
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"success": True, "data": _enrich(res.data[0])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# PATCH /v2/items/{item_id}
# ---------------------------------------------------------------------------

@router.patch("/items/{item_id}", response_model=dict)
def update_item(item_id: str, body: dict, user_id: CurrentUser, supabase: SupabaseDep):
    try:
        res = (
            supabase.table("items")
            .update(body)
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        return {"success": True, "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# DELETE /v2/items/{item_id}
# ---------------------------------------------------------------------------

@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, user_id: CurrentUser, supabase: SupabaseDep):
    check = (
        supabase.table("items")
        .select("id")
        .eq("id", item_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not check.data:
        raise HTTPException(status_code=404, detail="Not found")
    supabase.table("items").delete().eq("id", item_id).eq("user_id", user_id).execute()


# ---------------------------------------------------------------------------
# POST /v2/items/{item_id}/archive
# ---------------------------------------------------------------------------

@router.post("/items/{item_id}/archive", response_model=dict)
def archive_item(item_id: str, user_id: CurrentUser, supabase: SupabaseDep):
    supabase.table("items").update({"is_archived": True}).eq("id", item_id).eq("user_id", user_id).execute()
    return {"success": True}


@router.post("/items/{item_id}/unarchive", response_model=dict)
def unarchive_item(item_id: str, user_id: CurrentUser, supabase: SupabaseDep):
    supabase.table("items").update({"is_archived": False}).eq("id", item_id).eq("user_id", user_id).execute()
    return {"success": True}


# ---------------------------------------------------------------------------
# GET /v2/reports/estate
# ---------------------------------------------------------------------------

@router.get("/reports/estate", response_model=dict)
def estate_report(user_id: CurrentUser, supabase: SupabaseDep):
    try:
        res = supabase.table("items").select("*, scans(*)").eq("user_id", user_id).execute()
        items = res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    report: dict = {}
    total_resale = total_insurance = total_items = 0

    for item in items:
        if item.get("is_archived"):
            continue
        scan_info = item.get("scans") or {}
        home = item.get("home_name") or scan_info.get("home_name") or "My Property"
        room = item.get("room_name") or scan_info.get("room_name") or "General Areas"

        report.setdefault(home, {})
        report[home].setdefault(room, {"items": [], "subtotal_resale": 0, "subtotal_insurance": 0})

        resale_mid   = ((item.get("resale_low_cents") or 0) + (item.get("resale_high_cents") or 0)) // 2
        insur_mid    = ((item.get("insurance_replacement_low_cents") or 0) +
                        (item.get("insurance_replacement_high_cents") or 0)) // 2

        report[home][room]["items"].append({
            "name":              item.get("name"),
            "category":          item.get("category"),
            "brand":             item.get("brand"),
            "model":             item.get("model"),
            "condition":         item.get("condition"),
            "resale_midpoint":   round(resale_mid / 100, 2),
            "insurance_midpoint": round(insur_mid / 100, 2),
            "resale_range":      _cents_range(item.get("resale_low_cents"), item.get("resale_high_cents")),
            "insurance_range":   _cents_range(item.get("insurance_replacement_low_cents"), item.get("insurance_replacement_high_cents")),
            "thumbnail":         item.get("thumbnail_url"),
        })
        report[home][room]["subtotal_resale"]    += resale_mid
        report[home][room]["subtotal_insurance"]  += insur_mid
        total_resale   += resale_mid
        total_insurance += insur_mid
        total_items += 1

    for home_data in report.values():
        for room_data in home_data.values():
            room_data["subtotal_resale"]    = round(room_data["subtotal_resale"] / 100, 2)
            room_data["subtotal_insurance"]  = round(room_data["subtotal_insurance"] / 100, 2)

    return {
        "success":               True,
        "report_date":           time.strftime("%Y-%m-%d"),
        "owner_id":              user_id,
        "total_items":           total_items,
        "total_resale_value":    round(total_resale / 100, 2),
        "total_insurance_value": round(total_insurance / 100, 2),
        "properties":            report,
    }
