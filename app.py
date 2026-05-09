"""
Holos — AI-Powered Home Cataloging
Main application entry point.

This file initializes Flask, Supabase, registers Blueprints, and wires up
Agent 0B observability (structlog, Sentry, request timing, health endpoint).
"""
import os

from flask import Flask, render_template, jsonify
from supabase import create_client, Client

from config import Config
from observability import (
    setup_observability,
    get_logger,
    check_supabase_status,
    check_gemini_status,
    get_sentry_status,
    get_uptime_seconds,
    get_last_scan_cost,
)

log = get_logger("app", agent_id="1")

# ─── Fail-Closed Config Validation (Agent 1) ─────────────────
# Runs at import time so `flask run` and `python app.py` both enforce it.
Config.validate()

# ─── App Factory ─────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

# ─── Supabase Client ────────────────────────────────────────

supabase: Client = None  # type: ignore

if Config.SUPABASE_URL and (Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY):
    active_key = Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY
    supabase = create_client(Config.SUPABASE_URL, active_key)
    log.info("supabase_connected")
else:
    log.warning("supabase_not_configured", detail="running in local-only mode")

# ─── Observability (Agent 0B) ────────────────────────────────

setup_observability(app, supabase_client=supabase)

# ─── Register Blueprints ────────────────────────────────────

from routes.auth import auth_bp
from routes.scan import scan_bp
from routes.items import items_bp

app.register_blueprint(auth_bp)
app.register_blueprint(scan_bp)
app.register_blueprint(items_bp)

# ─── Web Dashboard ──────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ─── Health Endpoints ────────────────────────────────────────

@app.route("/api/health")
def health():
    """Lightweight liveness check — no expensive operations."""
    return jsonify({"status": "ok"})


@app.route("/api/health/detailed")
def health_detailed():
    """Full system health: connectivity checks, uptime, last scan cost."""
    return jsonify({
        "status": "ok",
        "uptime_seconds": get_uptime_seconds(),
        "supabase": check_supabase_status(supabase),
        "gemini": check_gemini_status(),
        "structlog": "ok",
        "sentry": get_sentry_status(),
        "last_scan_cost_cents": get_last_scan_cost(),
    })

# ─── Run ─────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(
        "holos_starting",
        ai_model=Config.GEMINI_MODEL,
        supabase=supabase is not None,
        test_accounts=Config.ENABLE_TEST_ACCOUNTS,
        sniper_mode=Config.ENABLE_SNIPER_MODE,
    )
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=5001)
