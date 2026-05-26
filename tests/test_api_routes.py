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
    # We have 4 known settings; lock in the count so a future addition
    # is a deliberate change (update both the count + the keys).
    keys = sorted(row["key"] for row in rows)
    assert keys == sorted([
        "max_history_turns",
        "default_discovery_timeout_seconds",
        "capture_token_ttl_seconds",
        "capture_rate_limit_per_minute",
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
