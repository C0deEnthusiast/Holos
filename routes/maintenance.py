"""
Routes for Home Maintenance — Phase 2
CRUD for maintenance tasks + AI-generated schedules via Gemini.
"""
import logging
import json
import uuid
from datetime import datetime, date, timedelta
from flask import Blueprint, request, jsonify, g

from routes.auth import get_current_user_id
from config import Config

logger = logging.getLogger("holos.maintenance")

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")

# ════════════════════════════════════════════════════════
# In-memory store (will migrate to Supabase table later)
# Key: user_id → list of task dicts
# ════════════════════════════════════════════════════════
_maintenance_store = {}


def _get_tasks(user_id):
    """Get tasks for a user, initializing if needed."""
    if user_id not in _maintenance_store:
        _maintenance_store[user_id] = []
    return _maintenance_store[user_id]


# ── GET /api/maintenance ──────────────────────────────
@maintenance_bp.route("", methods=["GET"])
def list_tasks():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    tasks = _get_tasks(user_id)
    return jsonify({"success": True, "data": tasks})


# ── POST /api/maintenance ─────────────────────────────
@maintenance_bp.route("", methods=["POST"])
def create_task():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    task = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": body.get("title", "Untitled Task"),
        "description": body.get("description", ""),
        "category": body.get("category", "General"),
        "season": body.get("season", "All Year"),
        "frequency": body.get("frequency", "annual"),
        "priority": body.get("priority", "medium"),
        "due_date": body.get("due_date"),
        "completed_at": None,
        "cost": body.get("cost"),
        "notes": body.get("notes", ""),
        "is_recurring": body.get("is_recurring", True),
        "created_at": datetime.utcnow().isoformat(),
    }

    _get_tasks(user_id).append(task)
    return jsonify({"success": True, "data": task}), 201


# ── PATCH /api/maintenance/<id> ───────────────────────
@maintenance_bp.route("/<task_id>", methods=["PATCH"])
def update_task(task_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    tasks = _get_tasks(user_id)
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    body = request.get_json() or {}
    for key in ["title", "description", "category", "season", "frequency",
                 "priority", "due_date", "cost", "notes", "is_recurring"]:
        if key in body:
            task[key] = body[key]

    # Mark as complete
    if body.get("completed"):
        task["completed_at"] = datetime.utcnow().isoformat()
    elif body.get("completed") is False:
        task["completed_at"] = None

    return jsonify({"success": True, "data": task})


# ── DELETE /api/maintenance/<id> ──────────────────────
@maintenance_bp.route("/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    tasks = _get_tasks(user_id)
    idx = next((i for i, t in enumerate(tasks) if t["id"] == task_id), None)
    if idx is None:
        return jsonify({"error": "Task not found"}), 404

    tasks.pop(idx)
    return jsonify({"success": True})


# ── POST /api/maintenance/generate ────────────────────
# AI-generated maintenance schedule using Gemini
@maintenance_bp.route("/generate", methods=["POST"])
def generate_schedule():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    property_name = body.get("property_name", "My House")
    address = body.get("address", "")
    bedrooms = body.get("bedrooms", 3)
    bathrooms = body.get("bathrooms", 2)
    rooms = body.get("rooms", [])

    try:
        # Reuse the scanner's pre-initialized Gemini client (same key + endpoint)
        from scanner import client as gemini_client
        prompt = f"""You are a home maintenance expert. Generate a comprehensive annual maintenance schedule for this property:

Property: {property_name}
Address: {address or 'Not specified'}
Bedrooms: {bedrooms}
Bathrooms: {bathrooms}
Rooms: {', '.join(rooms) if rooms else 'Standard'}

Generate exactly 15-20 maintenance tasks organized by season. For each task, return a JSON object with these exact fields:
- "title": Short task name (e.g. "Change HVAC Filters")
- "description": 1-2 sentence explanation of what to do and why
- "category": One of: HVAC, Plumbing, Electrical, Exterior, Interior, Appliance, Safety, Landscaping
- "season": One of: Spring, Summer, Fall, Winter, Monthly
- "frequency": One of: monthly, quarterly, semi-annual, annual
- "priority": One of: low, medium, high, critical
- "estimated_cost": Number (estimated cost in USD, 0 if DIY)

Return ONLY a JSON array of these objects. No explanation text, no markdown formatting, no code blocks — just the raw JSON array.
"""

        response = gemini_client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )

        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        ai_tasks = json.loads(raw)
        logger.info("AI generated %d maintenance tasks for %s", len(ai_tasks), property_name)

        # Convert AI output to our task format and store
        today = date.today()
        season_months = {"Spring": 3, "Summer": 6, "Fall": 9, "Winter": 12, "Monthly": today.month}
        created_tasks = []

        for item in ai_tasks:
            season = item.get("season", "Spring")
            month = season_months.get(season, 3)
            due = date(today.year if month >= today.month else today.year + 1, month, 15)

            task = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "title": item.get("title", "Maintenance Task"),
                "description": item.get("description", ""),
                "category": item.get("category", "General"),
                "season": season,
                "frequency": item.get("frequency", "annual"),
                "priority": item.get("priority", "medium"),
                "due_date": due.isoformat(),
                "completed_at": None,
                "cost": item.get("estimated_cost", 0),
                "notes": "",
                "is_recurring": True,
                "created_at": datetime.utcnow().isoformat(),
            }
            created_tasks.append(task)

        # Replace existing tasks for this user
        _maintenance_store[user_id] = created_tasks

        return jsonify({"success": True, "data": created_tasks, "count": len(created_tasks)})

    except json.JSONDecodeError as e:
        logger.error("Failed to parse AI maintenance response: %s", e)
        return jsonify({"error": "AI returned invalid data. Please try again."}), 500
    except Exception as e:
        logger.error("Maintenance schedule generation failed: %s", e)
        return jsonify({"error": f"Generation failed: {str(e)}"}), 500
