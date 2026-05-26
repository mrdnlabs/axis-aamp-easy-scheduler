"""Integration tests for the ChAAMP chat endpoint, driven by the user
stories in ``docs/user_stories.md``.

These hit the live FastAPI sidecar + Gemini. Each test costs ~$0.01 at
current Gemini Pro pricing. The conftest auto-skips the whole module if
the server isn't reachable or the Gemini key isn't configured.

Run with::

    pytest tests/test_chat_integration.py -v

Or one at a time::

    pytest tests/test_chat_integration.py::test_m1_greeting -v -s
"""

from __future__ import annotations

import pytest

# Read-side tool surface names — used in "model called a read-tool"
# style assertions. Kept here so the test file shows the model is free
# to pick any of them, not pinned to one specific call.
READ_TOOLS_SITE = {"describe_site", "list_sites"}
READ_TOOLS_ZONES = {"list_physical_zones", "describe_site"}
READ_TOOLS_SCHEDULE = {"list_schedule_events", "describe_site"}
DISCOVERY_TOOLS = {"discover_axis_devices", "test_axis_discovery_methods"}


# ---------------------------------------------------------------------------
# Maya — K-12 administrator
# ---------------------------------------------------------------------------


def test_m1_greeting(chat):
    """M1: bare 'hi' must produce a real response.

    This is the canonical empty-STOP test — before the round-0 retry fix
    this failed ~57% of the time."""
    result = chat.say("hi")
    assert result.finish_reason == "STOP"
    assert any(r.strip() for r in result.text_replies), \
        f"No text in any reply. text_replies={result.text_replies}"
    # We allow up to 3 rounds because the model legitimately needs the
    # current date + site context to greet usefully.
    # (The conftest enforces the no-empty / no-hallucinated-tool invariants.)


def test_m2_list_zones(chat):
    """M2: 'list zones' → read-side tool + zones in reply.

    The model has latitude over which read tool it uses; the assertion
    is the *category* of tool, not a specific name."""
    result = chat.say("List the physical zones at this site.")
    assert result.used_any_tool(list(READ_TOOLS_ZONES)), (
        f"Expected one of {READ_TOOLS_ZONES}; got {result.tool_names()}"
    )
    # Site fixture has classrooms, gym, cafeteria, lounge — model
    # should mention at least one. Lowercase substring match.
    text = result.all_text
    zone_keywords = ["classroom", "gym", "cafeteria", "lounge", "zone"]
    assert any(k in text for k in zone_keywords), (
        f"Expected at least one of {zone_keywords} in reply. Got: {text[:400]!r}"
    )


def test_m3_whats_on_today(chat):
    """M3: 'what's scheduled today' → grounds date + reads schedule."""
    result = chat.say("What's scheduled to play today?")
    # The model should ground "today" against the real date.
    assert result.used_tool("get_local_date_time"), (
        f"Expected get_local_date_time call; got {result.tool_names()}"
    )
    # And it should look at the schedule somehow.
    assert result.used_any_tool(list(READ_TOOLS_SCHEDULE)), (
        f"Expected schedule read; got {result.tool_names()}"
    )
    assert any(r.strip() for r in result.text_replies)


def test_m4_multi_turn_context(chat):
    """M4: greeting then follow-up must use history, not restart."""
    turn1 = chat.say("hi")
    assert turn1.finish_reason == "STOP"

    turn2 = chat.say("What zones are at this site?")
    assert turn2.finish_reason == "STOP"
    assert turn2.used_any_tool(list(READ_TOOLS_ZONES)), (
        f"Turn 2 should call a read tool; got {turn2.tool_names()}"
    )
    text = turn2.all_text
    assert any(k in text for k in ["classroom", "gym", "cafeteria", "lounge", "zone"]), (
        f"Turn 2 should mention zones. Got: {text[:400]!r}"
    )


# ---------------------------------------------------------------------------
# Tom — IT director (network-permitting)
# ---------------------------------------------------------------------------


def test_t1_discover_devices(chat):
    """T1: 'discover speakers' → model calls a discovery tool.

    The hit count is LAN-dependent — we only assert the tool ran cleanly
    (no TOOL_ERROR via the conftest invariant). Zero devices found is a
    legitimate result on a test bench."""
    result = chat.say("Discover Axis speakers on the network.")
    assert result.used_any_tool(list(DISCOVERY_TOOLS)), (
        f"Expected a discovery tool; got {result.tool_names()}"
    )


# ---------------------------------------------------------------------------
# Sarah — front-office manager
# ---------------------------------------------------------------------------


def test_s1_capability_discovery(chat):
    """S1: 'what can you help with?' → either a capability overview OR a
    legitimate engagement question (site-setup prompt is fine).

    The system prompt currently leads with "ask for site name first" on
    a fresh session, so the model may answer "what can you help with?"
    by asking about the site instead of listing capabilities. Both
    paths are acceptable engagement — what we reject is a non-response
    or a topic-dodging reply about something unrelated.
    """
    result = chat.say("What can you help me with?")
    assert result.finish_reason == "STOP"
    text = result.all_text
    # Either: capability keywords present, OR setup-engagement keywords
    # present. Failure mode would be: neither set matches (model went
    # off-topic).
    capability_kw = ["schedule", "audio", "announc", "device", "zone",
                     "play", "bell", "music", "speaker"]
    setup_kw = ["site name", "kind of organization", "school",
                "business", "what kind of place", "tell me about"]
    cap_hits = sum(1 for k in capability_kw if k in text)
    setup_hits = sum(1 for k in setup_kw if k in text)
    assert cap_hits >= 2 or setup_hits >= 1, (
        f"Expected either a capability overview ({cap_hits} of "
        f"{capability_kw} matched) or a setup-engagement prompt "
        f"({setup_hits} of {setup_kw} matched). "
        f"Got: {text[:500]!r}"
    )


# ---------------------------------------------------------------------------
# David — AV integrator
# ---------------------------------------------------------------------------


def test_o1_org_intake_on_fresh_session(chat):
    """O1: with placeholder Description AND Audio use profile in the
    intent doc, a fresh session should elicit at least one org-level
    intake question (org type OR audio use cases). The model is NOT
    expected to ask about the human in front of it (no name/role) —
    intake is about the organization."""
    # An open prompt that invites the model to lead the intake.
    result = chat.say("Hi, I'd like to set up audio scheduling here.")
    text = result.all_text

    # Org-level intake keywords.
    org_intake = [
        "kind of", "what kind", "school", "office", "retail",
        "healthcare", "worship", "type of", "what's the name",
        "name of your organization", "name of your site",
        "audio for", "use the audio", "use cases", "what do you",
        "use it for", "primarily", "mainly", "what does", "what's its",
        "what kind of place",
    ]
    org_hits = sum(1 for k in org_intake if k in text)
    assert org_hits >= 1, (
        f"Expected at least one org-level intake question. "
        f"Got: {text[:500]!r}"
    )

    # User-level intake we want to AVOID. The intake is about the org,
    # not the human. (Allow "you" as the org's operator, but reject
    # explicit name/role asks.)
    user_asks = [
        "what's your name", "what is your name", "your full name",
        "what's your role", "what is your role", "what's your title",
        "your job title", "who am i speaking",
    ]
    user_hits = [k for k in user_asks if k in text]
    assert not user_hits, (
        f"Model asked for user identity instead of org details: "
        f"{user_hits}. Got: {text[:500]!r}"
    )


def test_d1_describe_site(chat):
    """D1: 'describe this site' → calls describe_site + multi-topic reply."""
    result = chat.say("Tell me about this site — what's already configured?")
    assert result.used_tool("describe_site"), (
        f"Expected describe_site call; got {result.tool_names()}"
    )
    text = result.all_text
    # Should touch multiple aspects of the site.
    topics = ["zone", "destination", "source", "schedule", "template",
              "classroom", "gym", "cafeteria"]
    matches = sum(1 for t in topics if t in text)
    assert matches >= 3, (
        f"Site overview should mention at least 3 of {topics}. "
        f"Got {matches}: {text[:500]!r}"
    )
