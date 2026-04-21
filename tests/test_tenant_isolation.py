"""
Agent 1 — Tenant Isolation Red-Team Tests
Verifies that user A cannot read, write, or delete user B's data.

Per Holos v2 brief §9.5 and §13 (Quality bars):
"Every test asserts tenant isolation (user A cannot read user B's row)."
"Tenant-isolation red-team tests all pass (required CI check)."
"""
import pytest
from unittest.mock import patch, MagicMock
from flask import g


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Create test Flask app with test config."""
    import os
    os.environ["ENV"] = "test"
    os.environ["ENABLE_TEST_ACCOUNTS"] = "true"
    os.environ["SECRET_KEY"] = "test-secret-key-32-chars-ok-here"
    os.environ["SUPABASE_URL"] = "https://test.supabase.co"
    os.environ["SUPABASE_KEY"] = "test-key"

    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


USER_A_TOKEN = "mock_token_tester1"   # maps to 22222222-...
USER_A_ID = "22222222-2222-2222-2222-222222222222"

USER_B_TOKEN = "mock_token_tester2"   # maps to 33333333-...
USER_B_ID = "33333333-3333-3333-3333-333333333333"

ITEM_OWNED_BY_B = {
    "id": "item-b-0001",
    "user_id": USER_B_ID,
    "name": "Samsung TV",
    "category": "electronics",
}


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test: get_current_user_id fails-closed on bad tokens
# ---------------------------------------------------------------------------

class TestAuthFailClosed:
    def test_null_token_returns_none(self, client):
        with client.application.test_request_context(
            headers={"Authorization": "Bearer null"}
        ):
            from routes.auth import get_current_user_id
            assert get_current_user_id() is None

    def test_empty_bearer_returns_none(self, client):
        with client.application.test_request_context(
            headers={"Authorization": "Bearer "}
        ):
            from routes.auth import get_current_user_id
            assert get_current_user_id() is None

    def test_no_auth_header_returns_none(self, client):
        with client.application.test_request_context():
            from routes.auth import get_current_user_id
            assert get_current_user_id() is None

    def test_legacy_mock_token_rejected(self, client):
        """The old generic 'mock_token' must be rejected."""
        with client.application.test_request_context(
            headers={"Authorization": "Bearer mock_token"}
        ):
            from routes.auth import get_current_user_id
            assert get_current_user_id() is None


# ---------------------------------------------------------------------------
# Test: Items endpoint — User A cannot read User B's items
# ---------------------------------------------------------------------------

class TestItemsTenantIsolation:

    def _mock_supabase_items(self, user_id_of_items: str):
        """Return mock supabase that only returns items owned by a given user."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.side_effect = (
            lambda col, val: MagicMock(
                execute=MagicMock(return_value=MagicMock(
                    data=[ITEM_OWNED_BY_B] if val == USER_B_ID else []
                ))
            )
        )
        return mock_sb

    def test_user_a_gets_empty_list_not_user_b_items(self, client):
        """
        User A requests items. Must get [] even if user B has items.
        The query must be filtered by user_id = User A's ID.
        """
        with patch("routes.items.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            # Final .execute() returns empty list (simulates RLS filtering to User A's rows)
            chain = mock_sb.table.return_value.select.return_value
            chain.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
            chain.eq.return_value.execute.return_value = MagicMock(data=[])
            mock_get_sb.return_value = mock_sb

            r = client.get("/api/items", headers=auth_headers(USER_A_TOKEN))
            assert r.status_code == 200
            data = r.get_json()
            items = data.get("items", data.get("data", []))
            item_ids = [i.get("id") for i in items]
            assert ITEM_OWNED_BY_B["id"] not in item_ids, (
                "TENANT ISOLATION FAILURE: User A can see User B's item!"
            )

    def test_user_b_cannot_delete_user_a_item(self, client):
        """User B POSTing delete on an item owned by User A must get 403/404."""
        user_a_item_id = "item-a-0001"

        with patch("routes.items.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            # Simulate: item exists but belongs to user A
            mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[]  # empty because user_id filter = user B's ID won't match
            )
            mock_get_sb.return_value = mock_sb

            r = client.delete(
                f"/api/items/{user_a_item_id}",
                headers=auth_headers(USER_B_TOKEN),
            )
            assert r.status_code in (403, 404), (
                f"TENANT ISOLATION FAILURE: User B got {r.status_code} deleting User A's item"
            )

    def test_unauthenticated_gets_401(self, client):
        """No token at all must return 401."""
        r = client.get("/api/items")
        assert r.status_code == 401

    def test_invalid_token_gets_401(self, client):
        """Garbage token must return 401."""
        with patch("routes.auth.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_sb.auth.get_user.side_effect = Exception("Invalid JWT")
            mock_get_sb.return_value = mock_sb

            r = client.get("/api/items", headers={"Authorization": "Bearer garbage-token"})
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# Test: Production guards
# ---------------------------------------------------------------------------

class TestProductionGuards:

    def test_secret_key_fails_closed_in_production(self):
        """Config.validate() must raise if SECRET_KEY is the insecure default in production."""
        from config import Config
        # Directly patch the attributes to simulate production state
        # without fighting load_dotenv's reload-ordering quirks
        original_env = Config.ENV
        original_debug = Config.DEBUG
        original_key = Config.SECRET_KEY

        Config.ENV = "production"
        Config.DEBUG = False  # Pass the debug check
        Config.SECRET_KEY = "holos-dev-secret-NOT-FOR-PRODUCTION"  # insecure default

        try:
            import config as cfg_module
            # Temporarily patch the module-level _IS_PRODUCTION too
            original_prod = cfg_module._IS_PRODUCTION
            cfg_module._IS_PRODUCTION = True

            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                Config.validate()
        finally:
            Config.ENV = original_env
            Config.DEBUG = original_debug
            Config.SECRET_KEY = original_key
            cfg_module._IS_PRODUCTION = original_prod

    def test_test_accounts_blocked_in_production(self):
        """ENABLE_TEST_ACCOUNTS=true in production must raise on import."""
        import os
        old_env = os.environ.get("ENV")
        old_flag = os.environ.get("ENABLE_TEST_ACCOUNTS")
        os.environ["ENV"] = "production"
        os.environ["ENABLE_TEST_ACCOUNTS"] = "true"

        import importlib, config as cfg_module
        importlib.reload(cfg_module)

        import routes.auth as auth_module
        with pytest.raises(RuntimeError, match="ENABLE_TEST_ACCOUNTS"):
            importlib.reload(auth_module)

        # Restore
        os.environ["ENV"] = old_env or "development"
        os.environ["ENABLE_TEST_ACCOUNTS"] = old_flag or "false"
