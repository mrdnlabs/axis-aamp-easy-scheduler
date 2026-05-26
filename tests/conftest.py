"""Shared fixtures for the ChAAMP integration test suite.

The tests in ``test_chat_integration.py`` hit the live FastAPI sidecar
(default http://127.0.0.1:7331) and therefore depend on:

  - ``aamp-server`` running locally
  - ``gemini/api_key`` configured (via keyring or env)
  - The AAM Pro database being reachable for read-tool tests

This conftest provides a single ``chat`` fixture that wraps the test
client + applies cross-cutting invariants on every turn (no hallucinated
tools, no safety blocks, no empty responses).
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

# Import directly from the package so we don't have to spawn the CLI for
# every test (saves a process per turn).
from aamp.server.chat_test_client import stream_chat_message


# ---------------------------------------------------------------------------
# Reachability check — fail fast with a clear message instead of cryptic
# urllib errors on every test
# ---------------------------------------------------------------------------

DEFAULT_SERVER = os.environ.get("AAMP_TEST_SERVER", "http://127.0.0.1:7331")


def _server_reachable(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{url}/healthz", timeout=2) as r:
            return (r.status == 200, f"{r.status}")
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:  # pragma: no cover - defensive
        return False, f"{type(e).__name__}: {e}"


def _gemini_configured(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{url}/api/config/status", timeout=2) as r:
            import json
            data = json.loads(r.read().decode("utf-8"))
            return bool(data.get("gemini_configured")), str(data)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@pytest.fixture(scope="session")
def server_url() -> str:
    """Validate the sidecar before any tests run. If the server is
    unreachable or Gemini isn't configured, skip the whole module with
    a clear reason — otherwise every test would individually report a
    cryptic ``ConnectionRefusedError``."""
    ok, msg = _server_reachable(DEFAULT_SERVER)
    if not ok:
        pytest.skip(
            f"aamp-server not reachable at {DEFAULT_SERVER}: {msg}. "
            f"Start it with `aamp-server` in another terminal."
        )
    ok, msg = _gemini_configured(DEFAULT_SERVER)
    if not ok:
        pytest.skip(
            f"Gemini key not configured: {msg}. "
            f"Run `aamp-set-credential gemini/api_key`."
        )
    return DEFAULT_SERVER


# ---------------------------------------------------------------------------
# Chat helper — turn the test client into something pytest-shaped
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    """Everything a test wants to assert on for one chat turn.

    Mirrors what ``stream_chat_message`` returns, plus convenience
    accessors. ``raw`` preserves the full event sequence so a failing
    test can dump the timeline without re-running.
    """
    session_id: str
    transcript_path: Optional[str]
    finish_reason: Optional[str]
    text_replies: list[str]
    tool_calls: list[dict[str, Any]]
    empty_info: Optional[dict[str, Any]]
    elapsed_ms: int
    raw: list[dict[str, Any]] = field(default_factory=list)

    @property
    def all_text(self) -> str:
        """Lowercase-joined assistant text for substring assertions."""
        return "\n".join(self.text_replies).lower()

    def tool_names(self) -> list[str]:
        """Names of every tool the model called, in order. Includes both
        running and final events; deduped to avoid double-counting the
        running/completed pair."""
        seen = set()
        out: list[str] = []
        for tc in self.tool_calls:
            name = tc.get("name")
            cid = tc.get("call_id")
            key = (name, cid)
            if name and key not in seen:
                seen.add(key)
                out.append(name)
        return out

    def tool_errors(self) -> list[str]:
        """Tool calls whose result starts with ``TOOL_ERROR:``. A non-
        empty list means the model hallucinated a tool name or a tool
        raised."""
        errs: list[str] = []
        for ev in self.raw:
            if ev.get("event") != "part":
                continue
            d = ev.get("data") or {}
            if d.get("kind") == "tool_call" and d.get("status") in ("failed",):
                result = (d.get("result") or "").strip()
                if result.startswith("TOOL_ERROR:"):
                    errs.append(f"{d.get('name')}: {result.splitlines()[0]}")
        return errs

    def used_tool(self, name: str) -> bool:
        return name in self.tool_names()

    def used_any_tool(self, names: list[str]) -> bool:
        return any(self.used_tool(n) for n in names)


class ChatHelper:
    """Stateful chat client for tests. Tracks history across turns so
    multi-turn stories can be expressed naturally::

        helper.say("hi")
        result = helper.say("what zones are here?")

    The helper enforces three cross-cutting invariants (X1, X2, X3) on
    every turn unless ``check_invariants=False`` is passed. Stories that
    deliberately test broken cases pass ``False``.
    """

    def __init__(self, server: str, *, session_id: Optional[str] = None) -> None:
        self.server = server
        self.session_id = session_id
        self.history: list[dict[str, str]] = []

    def say(
        self,
        text: str,
        *,
        check_invariants: bool = True,
        timeout: float = 180.0,
    ) -> TurnResult:
        """Send one turn, return a TurnResult, optionally enforce X1/X2/X3."""
        gen = stream_chat_message(
            text,
            history=self.history,
            session_id=self.session_id,
            server=self.server,
            timeout=timeout,
        )
        events: list[dict[str, Any]] = []
        summary: dict[str, Any] = {}
        try:
            while True:
                ev, data = next(gen)
                events.append({"event": ev, "data": data})
        except StopIteration as stop:
            summary = stop.value or {}

        # Lock in the session id for any follow-up turns in this helper.
        if not self.session_id:
            self.session_id = summary.get("session_id")

        result = TurnResult(
            session_id=summary.get("session_id") or self.session_id or "",
            transcript_path=summary.get("transcript_path"),
            finish_reason=summary.get("finish_reason"),
            text_replies=summary.get("text_replies") or [],
            tool_calls=summary.get("tool_calls") or [],
            empty_info=summary.get("empty_info"),
            elapsed_ms=summary.get("elapsed_ms") or 0,
            raw=events,
        )

        # Maintain history for the NEXT turn (the wire is stateless).
        assistant_text = "\n\n".join(result.text_replies)
        self.history.append({"role": "user", "text": text})
        self.history.append({"role": "assistant", "text": assistant_text})

        if check_invariants:
            _check_invariants(result)

        return result


_BROKEN_RESPONSE_MARKERS = (
    "_Gemini returned no output",
    "blocked by Gemini's safety filter",
)


def _check_invariants(result: TurnResult) -> None:
    """X1, X2, X3 — applied to every turn unless a test opts out.

    Note on empty_info: it CAN appear in the done event even on a clean
    user-facing turn (when the hardcoded-greeting fallback fires after
    all retries empty). We don't reject on its mere presence — we
    reject when the user-visible text is the diagnostic placeholder."""
    # X3 — finite response. ``None`` would mean the stream closed
    # without ever emitting a ``done`` event.
    assert result.finish_reason is not None, (
        f"No finish_reason — stream ended without a done event. "
        f"Events: {[e['event'] for e in result.raw]}"
    )

    # X2 — the USER saw something useful. If the reply text matches any
    # known-broken marker, the chat is showing diagnostic copy in place
    # of a real response.
    joined = " ".join(result.text_replies)
    bad_markers = [m for m in _BROKEN_RESPONSE_MARKERS if m in joined]
    assert not bad_markers, (
        f"User-visible response contains diagnostic placeholder text: "
        f"{bad_markers}. empty_info={result.empty_info}. "
        f"text={joined[:300]!r}"
    )

    # X1 — no hallucinated tools.
    errs = result.tool_errors()
    assert not errs, (
        f"Model called non-existent / failed tool(s): {errs}. "
        f"Either add the tool to mcp_server.py or trim the prompt so the "
        f"model stops asking for it."
    )


@pytest.fixture
def chat(server_url) -> ChatHelper:
    """Fresh chat helper per test. New session id, empty history."""
    return ChatHelper(server_url)
