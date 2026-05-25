"""Chat HTTP/SSE endpoints — bridges the web client to the chat backend.

**Current status: scaffold.** This module exposes the route shape the
web client expects, but the Gemini integration is stubbed — sending a
message returns a canned reply that exercises every chat-inline widget
so the frontend SSE wiring can be tested end-to-end.

The real implementation will:
- Manage per-session chat history server-side
- Stream tokens from Gemini via SSE
- Dispatch tool calls through the existing FastMCP ``_tool_manager``
- Apply the credential scrubber to every part before writing to the SSE
  stream (defense-in-depth — the scrubber on the chat_log layer is the
  last line)

The session ID is currently client-supplied. A real implementation
should mint server-side tokens, persist history, and authenticate.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Demo / stub data — replaced by real Gemini integration in a follow-up
# ---------------------------------------------------------------------------

CANNED_STREAM_PARTS: list[dict[str, Any]] = [
    {"kind": "text", "body": "Got it — let me check the current schedule for that destination."},
    {
        "kind": "tool_call",
        "call_id": "tc_demo_1",
        "name": "describe_site",
        "summary": "Loaded 4 destinations, 3 active templates",
        "status": "success",
        "duration_ms": 320,
        "args": '{"site_id": 1}',
        "result": "Site Lincoln MS — 4 destinations (Elementary, Middle School, Gym, Lobby) · 12 devices · 3 active templates.",
    },
    {
        "kind": "text",
        "body": "Here's what I see today. **Lincoln MS** has 4 destinations (Elementary, Middle School, Gym, Lobby) with 12 devices and 3 templates active.",
    },
]


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------

class SendRequest(BaseModel):
    """User message + optional client-side session identifier."""
    text: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class SendAck(BaseModel):
    """Synchronous ack of receipt. The actual response streams via SSE."""
    session_id: str
    accepted: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/message", response_model=SendAck)
async def send_message(req: SendRequest) -> SendAck:
    """Accept a user message. The client should already have an open
    ``/chat/{session_id}/stream`` SSE connection — the response parts
    will arrive there.

    For the scaffold, the SSE stream below produces canned parts
    immediately on connect; this endpoint just echoes the session id.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="empty message")
    return SendAck(session_id=req.session_id, accepted=True)


@router.get("/{session_id}/stream")
async def stream(session_id: str) -> StreamingResponse:
    """SSE stream of message parts for ``session_id``.

    Stub: emits the canned conversation once and closes. Real
    implementation will hold the stream open and feed parts as the
    LLM produces them.
    """
    return StreamingResponse(_canned_event_stream(session_id), media_type="text/event-stream")


async def _canned_event_stream(session_id: str):
    """Demo SSE generator. Yields one ``data:`` line per chat part with a
    small delay between parts so the frontend can demonstrate streaming."""
    yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"
    await asyncio.sleep(0.3)
    for part in CANNED_STREAM_PARTS:
        yield f"event: part\ndata: {json.dumps(part)}\n\n"
        await asyncio.sleep(0.6)
    yield "event: done\ndata: {}\n\n"
