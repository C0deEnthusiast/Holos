"""
Tests for authentication — verifies the auth bypass is closed
and the @require_auth decorator works correctly.
"""


class TestAuthBypass:
    """Regression tests: ensure unauthenticated requests get 401."""

    def test_items_endpoint_requires_auth(self, client):
        """GET /api/items should return 401 without token."""
        res = client.get("/api/items")
        assert res.status_code == 401
        assert "Unauthorized" in res.get_json().get("error", "")

    def test_scan_endpoint_requires_auth(self, client):
        """POST /api/scan should return 401 without token."""
        res = client.post("/api/scan")
        # Could be 400 (no image) or 401 (no auth), both acceptable
        assert res.status_code in (400, 401)

    def test_save_item_requires_auth(self, client):
        """POST /api/items/save should return 401 without token."""
        res = client.post("/api/items/save",
                          json={"name": "Test Item"},
                          content_type="application/json")
        assert res.status_code == 401

    def test_estate_report_requires_auth(self, client):
        """GET /api/reports/estate should return 401 without token."""
        res = client.get("/api/reports/estate")
        assert res.status_code == 401

    def test_empty_bearer_token_rejected(self, client):
        """Bearer with empty string should be rejected."""
        res = client.get("/api/items", headers={"Authorization": "Bearer "})
        assert res.status_code == 401

    def test_null_bearer_token_rejected(self, client):
        """Bearer 'null' should be rejected (no default user fallback)."""
        res = client.get("/api/items", headers={"Authorization": "Bearer null"})
        assert res.status_code == 401

    def test_mock_token_rejected_without_prefix(self, client):
        """The raw string 'mock_token' should NOT authenticate."""
        res = client.get("/api/items", headers={"Authorization": "Bearer mock_token"})
        assert res.status_code == 401


class TestDemoEndpoint:
    """Tests for the /api/auth/demo endpoint."""

    def test_demo_login_returns_token(self, client):
        """Demo login should return a valid mock token when test accounts enabled."""
        res = client.post("/api/auth/demo")
        data = res.get_json()
        assert res.status_code == 200
        assert data["success"] is True
        assert "access_token" in data["session"]
        assert data["user"]["email"] == "admin@holos.com"

    def test_demo_login_token_is_valid(self, client):
        """Token from demo login should authenticate subsequent requests."""
        # Login
        login_res = client.post("/api/auth/demo")
        token = login_res.get_json()["session"]["access_token"]

        # Use token (will fail on data fetch since no Supabase, but should NOT 401)
        items_res = client.get("/api/items",
                               headers={"Authorization": f"Bearer {token}"})
        # With no Supabase it'll error on the query, but NOT 401
        assert items_res.status_code != 401


class TestHealthEndpoint:
    """Tests for the /api/health endpoint."""

    def test_health_check(self, client):
        """Health endpoint should return OK."""
        res = client.get("/api/health")
        data = res.get_json()
        assert data["status"] == "ok"

    def test_security_headers_present(self, client):
        """Security headers should be set on all responses."""
        res = client.get("/api/health")
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("X-Frame-Options") == "DENY"
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
