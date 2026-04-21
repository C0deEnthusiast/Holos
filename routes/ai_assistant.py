"""
AI Home Assistant Route
Provides a Gemini-powered chat endpoint for homeowner questions.
"""
import logging
from flask import Blueprint, request, jsonify
from routes.auth import get_current_user_id

logger = logging.getLogger("holos.ai_assistant")
ai_bp = Blueprint("ai_assistant", __name__, url_prefix="/api/ai")

SYSTEM_CONTEXT = """You are a knowledgeable and friendly AI Home Assistant built into the Holos home management platform.
You help homeowners with:
- Seasonal maintenance schedules and task checklists
- Home improvement project advice and ROI estimates
- Energy efficiency tips and upgrades
- Insurance coverage guidance
- Appliance care and troubleshooting
- Home value improvement strategies
- Plumbing, HVAC, electrical basics (safety first)
- Landscaping and exterior care

Keep your answers practical, clear, and actionable. Use bullet points where helpful.
If a question is outside home management, politely redirect to home-related topics.
Keep responses concise (under 300 words unless more detail is clearly needed)."""


@ai_bp.route("/chat", methods=["POST"])
def chat():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json() or {}
    message = body.get("message", "").strip()
    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        from scanner import client as gemini_client

        full_prompt = f"{SYSTEM_CONTEXT}\n\nHomeowner question: {message}"

        response = gemini_client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=full_prompt,
        )
        reply = response.text.strip()
        return jsonify({"success": True, "reply": reply})

    except Exception as e:
        logger.error("AI chat failed: %s", e)
        return jsonify({"error": f"AI error: {str(e)}"}), 500
