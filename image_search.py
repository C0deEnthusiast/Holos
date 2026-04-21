"""
Image Search — Google Custom Search API
Enriches scanned items with product images from the web.
Used by routes/scan.py (enrich_items_with_images) and
routes/items.py (search_product_image).
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger("holos.image_search")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def search_product_image(query: str, num: int = 1) -> Optional[str]:
    """
    Search Google Custom Search for a product image URL.
    Returns the first image URL or None if unavailable.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logger.debug("Google CSE not configured — skipping image search")
        return None

    try:
        resp = requests.get(
            CSE_ENDPOINT,
            params={
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query,
                "searchType": "image",
                "num": num,
                "imgSize": "medium",
                "safe": "active",
            },
            timeout=5,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return items[0].get("link")
    except Exception as e:
        logger.warning("image_search_failed query=%s error=%s", query, e)
    return None


def enrich_items_with_images(items: list[dict]) -> list[dict]:
    """
    Given a list of item dicts, attempt to find a web image URL
    for items that don't already have one. Modifies in-place.
    """
    for item in items:
        if item.get("photo_url"):
            continue
        name = item.get("name", "")
        brand = item.get("brand", "")
        query = f"{brand} {name}".strip()
        if query:
            url = search_product_image(query)
            if url:
                item["photo_url"] = url
    return items
