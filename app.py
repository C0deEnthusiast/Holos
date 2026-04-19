"""
Holos — AI-Powered Home Cataloging
Main application entry point.

This file initializes Flask, Supabase, and registers modular route Blueprints.
All business logic lives in routes/ and scanner.py.
"""
import os

from flask import Flask, render_template
from supabase import create_client, Client

from config import Config

# ─── App Factory ─────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

# Ensure upload directory exists
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

# ─── Supabase Client ────────────────────────────────────────

supabase: Client = None  # type: ignore

if Config.SUPABASE_URL and (Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY):
    active_key = Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_KEY
    supabase = create_client(Config.SUPABASE_URL, active_key)
else:
    print("⚠️  WARNING: Supabase not configured — running in local-only mode.")

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

# ─── Health Check ────────────────────────────────────────────

@app.route("/api/health")
def health():
    return {
        "status": "ok",
        "supabase": supabase is not None,
        "ai_model": Config.GEMINI_MODEL,
        "test_accounts": Config.ENABLE_TEST_ACCOUNTS,
        "sniper_mode": Config.ENABLE_SNIPER_MODE,
    }

# ─── Run ─────────────────────────────────────────────────────

if __name__ == "__main__":
    Config.validate()
    print("\n* Holos Backend Starting...")
    print(f"  AI Model:       {Config.GEMINI_MODEL}")
    print(f"  Supabase:       {'[v] Connected' if supabase else '[x] Not configured'}")
    print(f"  Test Accounts:  {'Enabled' if Config.ENABLE_TEST_ACCOUNTS else 'Disabled'}")
    print(f"  Sniper Mode:    {'Enabled' if Config.ENABLE_SNIPER_MODE else 'Disabled'}")
    print()
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=5001)
