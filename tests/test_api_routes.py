"""Non-LLM integration tests for the new sidecar routes.

These tests hit the FastAPI app via the in-process ``TestClient`` —
no live server required, no Gemini billing. They cover the routes
added in C1 of the UI-implementation plan: settings, credentials,
audit, site-overview.

Run with::

    pytest tests/test_api_routes.py -v

Fast — should finish in under 5 seconds. If they get slow, something's
gone wrong (e.g., the DB connection is being established on every
request).
"""

from __future__ import annotations

import pytest

from aamp.server.app import app


pytest.importorskip("fastapi", reason="fastapi (server deps) not installed")

from fastapi.testclient import TestClient  # noqa: E402  (after importorskip)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# /api/settings
# ---------------------------------------------------------------------------


def test_settings_list_returns_all_known(client: TestClient) -> None:
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    # Lock in the set of known settings so a future addition is a
    # deliberate change (update both the count + the keys).
    keys = sorted(row["key"] for row in rows)
    assert keys == sorted([
        "max_history_turns",
        "default_discovery_timeout_seconds",
        "capture_token_ttl_seconds",
        "capture_rate_limit_per_minute",
        "auth_required_group_sid",
    ]), f"got {keys}"
    # Shape check: each row carries enough for the UI to render.
    for row in rows:
        assert set(row.keys()) >= {
            "key", "value", "default", "type", "category", "description",
        }, f"row missing fields: {row.keys()}"
        assert row["type"] in {"int", "float", "bool", "string", "json"}


def test_settings_get_one(client: TestClient) -> None:
    r = client.get("/api/settings/max_history_turns")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "max_history_turns"
    assert body["type"] == "int"
    assert body["category"] == "chat"


def test_settings_get_unknown_404(client: TestClient) -> None:
    r = client.get("/api/settings/this_does_not_exist")
    assert r.status_code == 404


def test_settings_put_roundtrip(client: TestClient) -> None:
    """Write a known-good value, read it back, then reset to default
    by sending ``null``. Verifies the reset path too."""
    # Save original so we leave the system as we found it even if the
    # test bails in the middle.
    original = client.get("/api/settings/max_history_turns").json()["value"]
    try:
        # Write a new value.
        r = client.put("/api/settings/max_history_turns", json={"value": 25})
        assert r.status_code == 200, r.text
        assert r.json()["value"] == 25

        # Confirm it stuck.
        r = client.get("/api/settings/max_history_turns")
        assert r.json()["value"] == 25

        # Reset to default by sending null.
        r = client.put("/api/settings/max_history_turns", json={"value": None})
        assert r.status_code == 200
        body = r.json()
        # After delete, the live value should equal the default.
        assert body["value"] == body["default"]
    finally:
        # Restore.
        client.put("/api/settings/max_history_turns", json={"value": original})


def test_settings_put_unknown_404(client: TestClient) -> None:
    r = client.put("/api/settings/this_does_not_exist", json={"value": 1})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/credentials
# ---------------------------------------------------------------------------


def test_credentials_list_shape(client: TestClient) -> None:
    r = client.get("/api/credentials")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 4, f"expected at least 4 known credential slots, got {len(rows)}"
    for row in rows:
        assert set(row.keys()) >= {
            "account_id", "field", "description", "env_var", "is_csv_list", "stored",
        }
        assert isinstance(row["stored"], bool)
        # Values must NEVER cross the wire.
        assert "value" not in row, f"value leaked in row: {row}"


# ---------------------------------------------------------------------------
# /api/audit
# ---------------------------------------------------------------------------


def test_audit_list_default(client: TestClient) -> None:
    r = client.get("/api/audit")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    # We may or may not have audit entries on this machine — assert
    # only shape, not count.
    for row in rows:
        # ``extra`` always present; the rest may be None on legacy rows.
        assert "extra" in row


def test_audit_limit_param(client: TestClient) -> None:
    r = client.get("/api/audit?limit=1")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) <= 1


def test_audit_limit_clamp(client: TestClient) -> None:
    # Over-cap should 422 (FastAPI Query validation kicks in).
    r = client.get("/api/audit?limit=99999")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /api/site-overview
# ---------------------------------------------------------------------------


def test_site_overview_shape(client: TestClient) -> None:
    r = client.get("/api/site-overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"site_id", "site_label", "headline", "source"}
    assert body["site_id"] == 1
    assert body["source"] in {"intent_doc", "placeholder", "missing"}
    # If source != intent_doc, site_label must be None — the UI uses
    # that as the signal to show a generic fallback.
    if body["source"] != "intent_doc":
        assert body["site_label"] is None


def test_chat_request_accepts_attachments_shape() -> None:
    """Construct a ChatRequest with an attachment and verify it validates.

    We're not actually sending it through the LLM (that's a separate
    suite); we just want to confirm the wire shape compiles. This
    catches accidental regression of the FileAttachment schema."""
    from aamp.server.chat import ChatRequest, FileAttachment

    req = ChatRequest(
        text="here's a file",
        attachments=[
            FileAttachment(
                name="hello.txt",
                mime_type="text/plain",
                # b"hello world" base64-encoded
                data_b64="aGVsbG8gd29ybGQ=",
            ),
        ],
    )
    assert req.attachments[0].name == "hello.txt"
    assert req.attachments[0].mime_type == "text/plain"
    # Pydantic min_length=1 should reject empty data, but valid b64 is fine.
    assert len(req.attachments[0].data_b64) >= 1


def test_site_overview_explicit_site_id(client: TestClient) -> None:
    r = client.get("/api/site-overview?site_id=999")
    assert r.status_code == 200
    body = r.json()
    assert body["site_id"] == 999
    assert body["source"] == "missing"
    assert body["site_label"] is None


# ---------------------------------------------------------------------------
# /api/auth/me + peer-identity middleware
# ---------------------------------------------------------------------------


def test_auth_me_returns_synthetic_admin_in_testclient(client: TestClient) -> None:
    """TestClient short-circuits real socket auth — the middleware
    substitutes a synthetic admin identity. Verify the route reflects
    that so other tests can rely on the bypass."""
    r = client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_admin"] is True
    assert body["username"] is not None
    assert body["source"] == "windows_peer"
    assert body["required_group_sid"] == "S-1-5-32-544"


def test_auth_me_picks_up_settings_change(client: TestClient) -> None:
    """Required-group SID is configurable. Change it and re-fetch:
    the new value should appear in /auth/me."""
    # Save original to restore — we don't want this test to leave the
    # system in an unexpected state.
    saved = client.get("/api/settings/auth_required_group_sid").json()["value"]
    try:
        client.put(
            "/api/settings/auth_required_group_sid",
            json={"value": "S-1-5-32-545"},
        )
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["required_group_sid"] == "S-1-5-32-545"
    finally:
        client.put(
            "/api/settings/auth_required_group_sid",
            json={"value": saved},
        )


def test_middleware_blocks_when_not_admin(monkeypatch) -> None:
    """Force a non-admin identification result and assert that ALL
    non-allowlisted routes 403. We monkey-patch the identifier rather
    than the middleware itself so the production code path runs.

    This also exercises the JSON envelope shape — the frontend
    branches on ``code`` to choose copy."""
    from aamp.server import auth_middleware, peer_identity

    # Pretend we're a real loopback client (not testclient) and that
    # peer-identity resolved to a non-admin. The middleware uses
    # ``_is_testclient`` to decide whether to bypass; we override.
    monkeypatch.setattr(auth_middleware, "_is_testclient", lambda request: False)
    monkeypatch.setattr(
        peer_identity,
        "identify_socket_owner",
        lambda local_port, remote_addr, remote_port, admin_group_sid: peer_identity.SocketIdentity(
            pid=1234,
            username="WORKGROUP\\guest",
            sid="S-1-5-21-FAKE",
            is_admin=False,
        ),
    )
    # Also override the scope-port resolution since TestClient's
    # scope server tuple may be missing.
    monkeypatch.setattr(
        auth_middleware,
        "_local_port_from_scope",
        lambda request: 7331,
    )

    # New client picks up the patched middleware.
    from fastapi.testclient import TestClient as TC
    from aamp.server.app import app as live_app
    with TC(live_app) as c:
        r = c.get("/api/settings")
        assert r.status_code == 403
        body = r.json()
        assert body["code"] == "not_admin"
        assert "guest" in body["detail"]
        assert body["username"] == "WORKGROUP\\guest"

        # Allowlisted routes still pass even when not admin.
        r = c.get("/api/auth/me")
        assert r.status_code == 200
        r = c.get("/api/config/status")
        assert r.status_code == 200
