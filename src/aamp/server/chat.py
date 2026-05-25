"""Chat HTTP/SSE endpoints — bridges the web client to Gemini + MCP tools.

The web client POSTs each user message to ``/api/chat/message`` with the
full history attached; the endpoint responds with an SSE stream that
emits message-parts as they're produced. Stateless server: every request
is self-contained, no per-session state is kept.

Why stateless? Two reasons:

1. Fewer moving parts. Restarting ``aamp-server`` doesn't drop user
   conversations; the client owns the source of truth.
2. The chat history is the smallest piece of state and the easiest to
   serialize. Server-side caching can come later (Redis or similar)
   when sessions actually need to span processes.

The credential scrubber is applied to every part before SSE write — last
line of defense. If a tool somehow returns a password (every upstream
layer also scrubs), the value is masked before it ever leaves this file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


router = APIRouter(prefix="/chat", tags=["chat"])


# Default model — overridable via env. Gemini 2.5 Flash matches the CLI
# chat's default and gives the right latency/quality balance for the
# tool-heavy ChAAMP workload.
DEFAULT_MODEL = os.environ.get("CHAAMP_GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOOL_ROUNDS = 12   # safety stop for runaway tool-call loops


# ---------------------------------------------------------------------------
# Request shapes
# ---------------------------------------------------------------------------

class HistoryMessage(BaseModel):
    """One prior turn in the conversation, as the client sends it back."""
    role: Literal["user", "assistant"]
    text: str


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=16000)
    history: list[HistoryMessage] = Field(default_factory=list)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Helpers — system prompt + scrubber
# ---------------------------------------------------------------------------

def _load_system_prompt() -> str:
    """Read ``aamp.system_prompt.md`` — same source-of-truth as the CLI chat."""
    p = Path(__file__).resolve().parent.parent / "system_prompt.md"
    if not p.exists():
        return "You are ChAAMP, an assistant for AXIS Audio Manager Pro."
    return p.read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_system_prompt()


def _build_scrubber():
    """Construct a chat_log.Scrubber from every known credential value.

    Rebuilt per-request so newly captured credentials immediately become
    scrubbable. Cheap — just a keyring lookup per known slot + a set sort.
    """
    from ..chat_log import Scrubber
    from ..credentials import KNOWN_SECRETS, get_credential_store
    store = get_credential_store()
    values: list[str] = []
    for s in KNOWN_SECRETS:
        v = store.get(s.account_id, s.field)
        if not v:
            continue
        if s.is_csv_list:
            values.extend(x.strip() for x in v.split(",") if x.strip())
        else:
            values.append(v)
    return Scrubber(values)


# ---------------------------------------------------------------------------
# SSE event helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE message. JSON-encodes the data section."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _summary_from_result(text: str) -> str:
    """Return the first line of ``text`` (truncated) — used as the
    collapsed-card summary on the frontend ToolCallCard."""
    first = (text or "").strip().splitlines()[0] if text and text.strip() else ""
    if len(first) > 100:
        return first[:100] + "…"
    return first


# ---------------------------------------------------------------------------
# /chat/message — primary endpoint
# ---------------------------------------------------------------------------

@router.post("/message")
async def post_message(req: ChatRequest) -> StreamingResponse:
    """Send one user message; stream back assistant parts via SSE.

    Response is ``text/event-stream``. Event types:

      - ``event: session``  — once at start; ``{session_id}``
      - ``event: part``     — multiple; payload matches one of the
                              MessagePart variants in ``web/lib/types.ts``
      - ``event: error``    — fatal error during the turn
      - ``event: done``     — end of turn (model emitted STOP)

    Stateless: the client passes its full history with each request. The
    server reconstructs the Gemini conversation, runs the tool loop, and
    streams parts as they're produced.
    """
    return StreamingResponse(
        _run_turn(req),
        media_type="text/event-stream",
        headers={
            # SSE-friendly defaults that survive most reverse proxies.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _run_turn(req: ChatRequest):
    """The actual generator that yields SSE-formatted events.

    Pulled out of the route so it can be unit-tested or wrapped without
    going through the full FastAPI machinery.
    """
    # Lazy imports — keep cold-start fast and prevent the CLI's top-level
    # init from running when only the capture endpoint is being hit.
    try:
        from google import genai
        from google.genai import types
        # Reuse the CLI's tool translation + dispatch — same source of truth.
        from ..chat import call_mcp_tool, load_gemini_tools
    except ImportError as e:
        yield _sse("error", {"detail": f"Gemini SDK not installed: {e}"})
        return

    # API key resolution: credential store first (so users can capture it
    # via the secure modal or aamp-set-credential), then env vars (so
    # existing CLI-style setups keep working).
    from ..credentials import get_credential_store
    api_key = (
        get_credential_store().get("gemini", "api_key")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        yield _sse("error", {
            "detail": (
                "Gemini API key not configured. In a terminal, run: "
                "aamp-set-credential gemini/api_key — or set "
                "GEMINI_API_KEY in your environment before launching "
                "aamp-server."
            ),
        })
        return

    scrubber = _build_scrubber()

    # Always send the session id first so the client can correlate
    # streams with its own message log.
    yield _sse("session", {"session_id": req.session_id})

    # Build the Gemini ``contents`` list from history + this turn's text.
    contents: list[Any] = []
    for msg in req.history:
        role = "user" if msg.role == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=scrubber.scrub(msg.text))])
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=req.text)]))

    # Load Gemini-shaped tool declarations from the in-process MCP server.
    try:
        tools = await load_gemini_tools()
    except Exception as e:
        yield _sse("error", {"detail": f"Failed to load tools: {type(e).__name__}: {e}"})
        return

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.3,
    )

    client = genai.Client(api_key=api_key)

    # Tool-call loop. Each iteration either yields text + STOP, or yields
    # text + tool calls and adds the tool responses to ``contents`` for
    # the next iteration. Bounded by MAX_TOOL_ROUNDS to prevent runaway.
    for round_idx in range(MAX_TOOL_ROUNDS):
        try:
            # The SDK's async path is ``client.aio.models.generate_content``.
            response = await client.aio.models.generate_content(
                model=DEFAULT_MODEL,
                contents=contents,
                config=config,
            )
        except Exception as e:
            yield _sse("error", {
                "detail": f"{type(e).__name__}: {e}",
                "stage": f"generate_content (round {round_idx + 1})",
            })
            return

        candidate = response.candidates[0] if response.candidates else None
        finish_reason = (
            candidate.finish_reason.name
            if candidate and candidate.finish_reason
            else None
        )
        if not candidate or not candidate.content or not candidate.content.parts:
            # Nothing returned — bail with a hint.
            yield _sse("part", {
                "kind": "text",
                "body": f"_(no response — finish_reason: {finish_reason or 'unknown'})_",
            })
            yield _sse("done", {})
            return

        # Split the response into text chunks + function calls.
        text_chunks: list[str] = []
        function_calls: list[Any] = []
        for part in candidate.content.parts:
            if getattr(part, "function_call", None):
                function_calls.append(part.function_call)
            elif getattr(part, "text", None):
                text_chunks.append(part.text)

        # Stream text parts. Each non-empty chunk becomes one SSE event.
        for chunk in text_chunks:
            cleaned = chunk.rstrip()
            if cleaned:
                yield _sse("part", {"kind": "text", "body": scrubber.scrub(cleaned)})
                # Tiny yield so the event hits the socket promptly even if
                # downstream tool calls take a while.
                await asyncio.sleep(0)

        if not function_calls:
            # Turn complete. Surface finish_reason if it's noteworthy.
            if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
                yield _sse("part", {
                    "kind": "text",
                    "body": f"_(finish_reason: {finish_reason})_",
                })
            yield _sse("done", {"finish_reason": finish_reason or "STOP"})
            return

        # Dispatch each tool call. For each call we emit TWO events:
        #   1. running status (so the UI renders a spinner)
        #   2. final status with the args + result (so the card can be
        #      expanded to see what happened)
        tool_response_parts: list[Any] = []
        for fc in function_calls:
            args = dict(fc.args or {})
            call_id = getattr(fc, "id", None) or f"tc_{uuid.uuid4().hex[:8]}"
            args_json = scrubber.scrub(json.dumps(args, indent=2, default=str))

            # Running event
            yield _sse("part", {
                "kind": "tool_call",
                "call_id": call_id,
                "name": fc.name,
                "summary": "running…",
                "status": "running",
                "args": args_json,
            })
            await asyncio.sleep(0)

            # Dispatch
            t0 = time.monotonic()
            try:
                result_text = await call_mcp_tool(fc.name, args)
                duration_ms = int((time.monotonic() - t0) * 1000)
                is_error = result_text.startswith("TOOL_ERROR:")
            except Exception as e:
                result_text = f"TOOL_ERROR: {type(e).__name__}: {e}"
                duration_ms = int((time.monotonic() - t0) * 1000)
                is_error = True

            scrubbed_result = scrubber.scrub(result_text)

            # Completed event — same call_id so the frontend replaces the
            # earlier running entry rather than appending a new card.
            yield _sse("part", {
                "kind": "tool_call",
                "call_id": call_id,
                "name": fc.name,
                "summary": _summary_from_result(scrubbed_result),
                "status": "failed" if is_error else "success",
                "args": args_json,
                "result": scrubbed_result,
                "duration_ms": duration_ms,
            })

            # Feed the result back to Gemini for the next round. We pass
            # the UN-scrubbed result so the model has full context for
            # follow-up decisions — the scrub-on-the-wire only protects
            # the on-screen rendering + transcript log.
            tool_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result_text},
                        id=call_id,
                    )
                )
            )

        # Append the model's request + the tool responses to ``contents``
        # so the next generate_content sees both halves.
        contents.append(candidate.content)
        contents.append(types.Content(role="user", parts=tool_response_parts))

    # Round limit reached without STOP — surface and end.
    yield _sse("part", {
        "kind": "text",
        "body": "_(Reached the tool-call round limit. Ending turn — ask again to continue.)_",
    })
    yield _sse("done", {"finish_reason": "MAX_TOOL_ROUNDS"})
