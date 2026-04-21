"""
Pytest configuration and shared fixtures for Holos tests.
"""
import os
import sys
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set safe test defaults BEFORE importing app
os.environ.setdefault("FLASK_DEBUG", "false")
os.environ.setdefault("ENABLE_TEST_ACCOUNTS", "true")
os.environ.setdefault("SUPABASE_URL", "")  # Disable Supabase in tests
os.environ.setdefault("SUPABASE_KEY", "")
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")


@pytest.fixture
def app():
    """Create a test Flask application."""
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Return headers with a valid mock auth token."""
    return {"Authorization": "Bearer mock_token_admin"}


@pytest.fixture
def unauth_headers():
    """Return headers with no auth."""
    return {}
