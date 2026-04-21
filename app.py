"""
Holos — AI-Powered Home Cataloging
Main application entry point.

This file initializes Flask, Supabase, and registers modular route Blueprints.
All business logic lives in routes/ and scanner.py.
"""
import os
import logging

from flask import Flask, render_template, request, jsonify
from supabase import create_client, Client
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from observability import setup_observability

# ─── Observability (structlog + Sentry) ──────────────────────
setup_observability()
import structlog
logger = structlog.get_logger("holos.app")

# ─── App Factory ─────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

# Ensure upload directory exists
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

# ─── Rate Limiter ────────────────────────────────────────────

def _get_rate_limit_key():
    """Use user token if available, otherwise fall back to IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and len(auth_header) > 10:
        return auth_header.split(" ")[1][:32]  # Truncate token for key
    return get_remote_address()

limiter = Limiter(
    _get_rate_limit_key,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# ─── Supabase Client ────────────────────────────────────────

supabase: Client = None  # type: ignore

# Use the publishable anon key (not service_role) for the app-level client.
# RLS enforces tenant isolation. service_role is for migrations only.
if Config.SUPABASE_URL and Config.SUPABASE_KEY:
    supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
else:
    logger.warning("supabase_not_configured", detail="running in local-only mode")

# ─── Register Blueprints ────────────────────────────────────

from routes.auth import auth_bp
from routes.scan import scan_bp
from routes.items import items_bp
from routes.maintenance import maintenance_bp
from routes.ai_assistant import ai_bp

app.register_blueprint(auth_bp)
app.register_blueprint(scan_bp)
app.register_blueprint(items_bp)
app.register_blueprint(maintenance_bp)
app.register_blueprint(ai_bp)

# ─── Apply Rate Limits to Expensive Endpoints ───────────────

# Scans cost real Gemini $$. Limit: 50/day, 10/minute per user.
limiter.limit("50/day;10/minute")(
    app.view_functions["scan.scan_image"]
)

# Resale listing generation also calls Gemini
limiter.limit("30/day;5/minute")(
    app.view_functions["items.get_resale_listing"]
)

# Google Image Search — free tier is 100/day
limiter.limit("100/day;20/minute")(
    app.view_functions["items.get_web_image"]
)

# ─── Web Dashboard ──────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ─── Health Check ────────────────────────────────────────────

@app.route("/api/health")
def health():
    db_ok = False
    if supabase:
        try:
            supabase.table("profiles").select("id").limit(1).execute()
            db_ok = True
        except Exception:
            db_ok = False
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "version": os.getenv("APP_VERSION", "dev"),
        "env": os.getenv("ENV", "development"),
        "db": "ok" if db_ok else "error",
        "ai_model": Config.GEMINI_MODEL,
        "test_accounts": Config.ENABLE_TEST_ACCOUNTS,
    })

# ─── Security Headers ──────────────────────────────────────

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if not Config.DEBUG:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ─── Rate Limit Error Handler ────────────────────────────────

@app.errorhandler(429)
def rate_limit_handler(e):
    return jsonify({
        "error": "Rate limit exceeded. Please slow down.",
        "retry_after": e.description,
    }), 429

# ─── Run ─────────────────────────────────────────────────────

if __name__ == "__main__":
    Config.validate()
    logger.info("Holos Backend Starting...")
    logger.info("  AI Model:       %s", Config.GEMINI_MODEL)
    logger.info("  Supabase:       %s", '[v] Connected' if supabase else '[x] Not configured')
    logger.info("  Test Accounts:  %s", 'Enabled' if Config.ENABLE_TEST_ACCOUNTS else 'Disabled')
    logger.info("  Sniper Mode:    %s", 'Enabled' if Config.ENABLE_SNIPER_MODE else 'Disabled')
    logger.info("  Rate Limiting:  Active (50 scans/day, 10/min per user)")
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=5000)

