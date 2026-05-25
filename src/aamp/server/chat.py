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
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


router = APIRouter(prefix="/chat", tags=["chat"])


# Default model — overridable via env. Gemini 2.5 Flash matches the CLI
# chat's default and gives the right latency/quality balance for the
# tool-heavy ChAAMP workload.
DEFAULT_MODEL = os.environ.get("CHAAMP_GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOOL_ROUNDS = 12   # safety stop for runaway tool-call loops

# Transcript log directory. One JSONL per session. Created on demand.
TRANSCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "logs"


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
# Transcript log writer
# ---------------------------------------------------------------------------

class TranscriptWriter:
    """Append-only JSONL writer for the chat transcript.

    One file per session — :data:`TRANSCRIPT_DIR` / ``chat_<session_id>_<ts>.jsonl``.
    Events mirror the SSE stream shape so the file IS the recorded
    conversation, no extra translation needed.

    Resilient: every write is try/except'd. The chat must never fail
    because the log can't be written (disk full, perms, etc.).
    """

    def __init__(self, session_id: str) -> None:
        try:
            TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path: Optional[Path] = TRANSCRIPT_DIR / f"chat_web_{ts}_{session_id[:8]}.jsonl"
            self._fp = self.path.open("a", encoding="utf-8", buffering=1)
        except OSError:
            self.path = None
            self._fp = None

    def write(self, kind: str, **payload: Any) -> None:
        """Write one record. ``payload`` should already be scrubbed."""
        if self._fp is None:
            return
        try:
            self._fp.write(
                json.dumps(
                    {
                        "ts": datetime.now().isoformat(timespec="milliseconds"),
                        "kind": kind,
                        **payload,
                    },
                    default=str,
                )
                + "\n"
            )
        except Exception:
            # Logging must never crash the chat.
            pass

    def close(self) -> None:
        if self._fp is None:
            return
        try:
            self._fp.close()
        except Exception:
            pass
        self._fp = None


@contextmanager
def transcript_session(session_id: str) -> Iterator[TranscriptWriter]:
    """Context manager that ensures the log file closes even on stream errors."""
    w = TranscriptWriter(session_id)
    try:
        yield w
    finally:
        w.close()


# ---------------------------------------------------------------------------
# Token usage accumulator (per-request)
# ---------------------------------------------------------------------------

class UsageAcc:
    """Mirrors :class:`aamp.chat_log.UsageAccumulator` but in-server.

    Per-request lifetime — the client owns the session totals (they
    add up the per-request totals it receives). This keeps the server
    stateless.
    """
    def __init__(self) -> None:
        self.turns = 0
        self.prompt = 0
        self.candidates = 0
        self.cached = 0
        self.thoughts = 0
        self.tool_overhead = 0
        self.total = 0

    def add(self, usage_metadata: Any) -> dict[str, int]:
        """Fold one turn's usage and return the per-turn dict for the wire."""
        if usage_metadata is None:
            return {}
        turn = {
            "prompt_tokens": getattr(usage_metadata, "prompt_token_count", 0) or 0,
            "candidates_tokens": getattr(usage_metadata, "candidates_token_count", 0) or 0,
            "cached_tokens": getattr(usage_metadata, "cached_content_token_count", 0) or 0,
            "thoughts_tokens": getattr(usage_metadata, "thoughts_token_count", 0) or 0,
            "tool_use_prompt_tokens": getattr(usage_metadata, "tool_use_prompt_token_count", 0) or 0,
            "total_tokens": getattr(usage_metadata, "total_token_count", 0) or 0,
        }
        self.turns += 1
        self.prompt += turn["prompt_tokens"]
        self.candidates += turn["candidates_tokens"]
        self.cached += turn["cached_tokens"]
        self.thoughts += turn["thoughts_tokens"]
        self.tool_overhead += turn["tool_use_prompt_tokens"]
        self.total += turn["total_tokens"]
        return turn

    def request_totals(self) -> dict[str, int]:
        """Rollup across all tool rounds in this request."""
        return {
            "turns": self.turns,
            "prompt_tokens": self.prompt,
            "candidates_tokens": self.candidates,
            "cached_tokens": self.cached,
            "thoughts_tokens": self.thoughts,
            "tool_use_prompt_tokens": self.tool_overhead,
            "total_tokens": self.total,
        }


# ---------------------------------------------------------------------------
# SSE event helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE message. JSON-encodes the data section."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_artifact_pill_from_args(args: dict[str, Any], scrubber: Any) -> Optional[dict[str, Any]]:
    """Translate an ``emit_artifact_pill`` MCP call into the SSE part payload.

    Parses the LLM-supplied ``data_json`` (if any) and packages everything
    into the shape the frontend's ``ArtifactPillPart`` expects. Returns
    ``None`` if the args are malformed — the chat backend silently skips
    the pill in that case (the original tool-call card still shows what
    happened).

    The data payload is scrubbed before going on the wire — defense in
    depth in case the LLM accidentally embedded a secret in the JSON.
    """
    artifact = args.get("artifact")
    key = args.get("key")
    title = args.get("title")
    if not artifact or not key or not title:
        return None
    pill: dict[str, Any] = {
        "artifact": artifact,
        "key": str(key),
        "title": scrubber.scrub(str(title)),
    }
    subtitle = args.get("subtitle")
    if subtitle:
        pill["subtitle"] = scrubber.scrub(str(subtitle))
    data_json = args.get("data_json")
    if data_json:
        try:
            data = json.loads(data_json)
            # Walk the payload through the scrubber too — strings only.
            pill["data"] = _scrub_obj(data, scrubber)
        except (json.JSONDecodeError, TypeError):
            # Bad JSON — skip the data; the pill still renders with the
            # frontend's demo fallback or shows an empty pane.
            pass
    return pill


def _scrub_obj(obj: Any, scrubber: Any) -> Any:
    """Recursively scrub every string leaf in a JSON-like structure."""
    if isinstance(obj, str):
        return scrubber.scrub(obj)
    if isinstance(obj, dict):
        return {k: _scrub_obj(v, scrubber) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_obj(v, scrubber) for v in obj]
    return obj


def _summary_from_result(text: str) -> str:
    """Return the first line of ``text`` (truncated) — used as the
    collapsed-card summary on the frontend ToolCallCard."""
    first = (text or "").strip().splitlines()[0] if text and text.strip() else ""
    if len(first) > 100:
        return first[:100] + "…"
    return first


def _enum_name(v: Any) -> Optional[str]:
    """Best-effort enum-name extraction. Gemini SDK enums expose ``.name``;
    legacy paths sometimes hand back a raw int. Falls back to ``str(v)``
    so something useful always reaches the transcript."""
    if v is None:
        return None
    name = getattr(v, "name", None)
    if name:
        return str(name)
    return str(v)


def _safety_ratings_to_list(ratings: Any) -> list[dict[str, Any]]:
    """Convert Gemini ``safety_ratings`` (list of objects) to a plain
    list-of-dicts the JSON logger can serialize.

    Each rating exposes ``category``, ``probability`` (LOW / MEDIUM / HIGH)
    and ``blocked`` (bool). We capture all three so we can tell which
    safety category fired without re-running the request.
    """
    out: list[dict[str, Any]] = []
    for r in ratings or []:
        out.append({
            "category": _enum_name(getattr(r, "category", None)),
            "probability": _enum_name(getattr(r, "probability", None)),
            "blocked": bool(getattr(r, "blocked", False)),
        })
    return out


def _gather_empty_response_info(response: Any, candidate: Any) -> dict[str, Any]:
    """Pull everything potentially-diagnostic out of an empty Gemini reply.

    Three independent signals worth capturing:

    1. ``prompt_feedback`` — set when the **prompt** itself was blocked.
       ``block_reason`` indicates which gate fired (``SAFETY``,
       ``OTHER``, ``BLOCKLIST``, ``PROHIBITED_CONTENT``…), and
       ``safety_ratings`` give per-category detail.
    2. ``candidate.finish_reason`` + ``candidate.safety_ratings`` —
       set when the **response** started generating then got cut off.
       Distinct from (1).
    3. ``candidates`` length — zero means the prompt was rejected; one
       with empty content means the model emitted nothing.

    Returns a dict shaped for JSON logging. Empty-safe; missing fields
    just don't appear in the result.
    """
    info: dict[str, Any] = {
        "candidates_count": len(response.candidates) if response.candidates else 0,
    }

    pf = getattr(response, "prompt_feedback", None)
    if pf is not None:
        pf_info: dict[str, Any] = {}
        block_reason = _enum_name(getattr(pf, "block_reason", None))
        if block_reason and block_reason not in ("BLOCK_REASON_UNSPECIFIED", "None"):
            pf_info["block_reason"] = block_reason
        block_msg = getattr(pf, "block_reason_message", None)
        if block_msg:
            pf_info["block_reason_message"] = str(block_msg)
        ratings = _safety_ratings_to_list(getattr(pf, "safety_ratings", None))
        if ratings:
            pf_info["safety_ratings"] = ratings
        if pf_info:
            info["prompt_feedback"] = pf_info

    if candidate is not None:
        cand_info: dict[str, Any] = {}
        fr = _enum_name(getattr(candidate, "finish_reason", None))
        if fr:
            cand_info["finish_reason"] = fr
        fm = getattr(candidate, "finish_message", None)
        if fm:
            cand_info["finish_message"] = str(fm)
        ratings = _safety_ratings_to_list(getattr(candidate, "safety_ratings", None))
        if ratings:
            cand_info["safety_ratings"] = ratings
        content = getattr(candidate, "content", None)
        cand_info["had_content"] = bool(content)
        cand_info["parts_count"] = len(content.parts) if content and content.parts else 0
        info["candidate"] = cand_info

    return info


def _format_empty_response_message(empty_info: dict[str, Any]) -> str:
    """Turn the diagnostic dict into one Markdown line for the chat.

    The verbose JSON goes to the transcript; users see a short
    explanation. Three branches mirror the three blocking modes:
    prompt-side, response-side, or "Gemini just sent nothing".
    """
    pf = empty_info.get("prompt_feedback") or {}
    cand = empty_info.get("candidate") or {}

    if pf.get("block_reason"):
        blocked = [
            r["category"] for r in pf.get("safety_ratings", [])
            if r.get("blocked")
        ]
        suffix = f" (categories: {', '.join(blocked)})" if blocked else ""
        return (
            f"_The prompt was blocked by Gemini's safety filter — "
            f"`block_reason: {pf['block_reason']}`{suffix}. "
            f"See the transcript for full per-category ratings._"
        )

    if cand.get("finish_reason") == "SAFETY":
        blocked = [
            r["category"] for r in cand.get("safety_ratings", [])
            if r.get("blocked")
        ]
        suffix = f" (categories: {', '.join(blocked)})" if blocked else ""
        return (
            f"_The response was blocked by Gemini's safety filter "
            f"mid-generation{suffix}. See the transcript for full per-"
            f"category ratings._"
        )

    fr = cand.get("finish_reason") or "unknown"
    return (
        f"_Gemini returned no output (finish_reason: {fr}). This sometimes "
        f"happens on very short prompts against a large tool list — try a "
        f"more specific request. Diagnostic detail in the transcript._"
    )


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
    usage = UsageAcc()

    # Open the transcript writer for this turn. Closed in the finally
    # block at the bottom of this generator (FastAPI's StreamingResponse
    # iterates the generator; the finally fires whether or not we hit
    # an error / done).
    log = TranscriptWriter(req.session_id)
    log.write("turn_start",
              session_id=req.session_id,
              user_text=scrubber.scrub(req.text),
              history_chars=sum(len(m.text) for m in req.history),
              transcript_path=str(log.path) if log.path else None)

    # Always send the session id first so the client can correlate
    # streams with its own message log.
    yield _sse("session", {
        "session_id": req.session_id,
        "transcript_path": str(log.path) if log.path else None,
    })

    # Apply history trim (configurable via aamp.settings).
    from .. import settings as _settings
    max_turns = _settings.get_setting("max_history_turns")
    trimmed_history = req.history
    trimmed_count = 0
    if isinstance(max_turns, int) and max_turns > 0 and len(req.history) > max_turns:
        trimmed_count = len(req.history) - max_turns
        trimmed_history = req.history[-max_turns:]
        log.write("history_trimmed",
                  original=len(req.history), kept=max_turns,
                  dropped=trimmed_count)

    # Build the Gemini ``contents`` list from history + this turn's text.
    contents: list[Any] = []
    for msg in trimmed_history:
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
    # The try/finally guards the log close — even if the SSE generator
    # is dropped mid-stream (client disconnect, exception), the transcript
    # file gets flushed.
    try:
        for round_idx in range(MAX_TOOL_ROUNDS):
            try:
                # The SDK's async path is ``client.aio.models.generate_content``.
                response = await client.aio.models.generate_content(
                    model=DEFAULT_MODEL,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                log.write("error", stage=f"generate_content (round {round_idx + 1})", detail=msg)
                yield _sse("error", {
                    "detail": msg,
                    "stage": f"generate_content (round {round_idx + 1})",
                })
                return

            # Capture token usage for this round (may include cached / thoughts).
            per_turn = usage.add(getattr(response, "usage_metadata", None))
            if per_turn:
                log.write("token_usage", per_turn=per_turn, totals=usage.request_totals())
                yield _sse("usage", {
                    "per_turn": per_turn,
                    "request_totals": usage.request_totals(),
                })

            candidate = response.candidates[0] if response.candidates else None
            finish_reason = (
                candidate.finish_reason.name
                if candidate and candidate.finish_reason
                else None
            )
            if not candidate or not candidate.content or not candidate.content.parts:
                # Nothing came back. Capture enough diagnostic detail in the
                # transcript that the next time this happens we can tell
                # exactly which branch fired: prompt-side safety block,
                # response-side safety block, or just a Gemini empty
                # response on a huge prefix + tiny user message.
                empty_info = _gather_empty_response_info(response, candidate)
                empty_info["round"] = round_idx + 1
                log.write("assistant_empty", **empty_info)
                user_msg = _format_empty_response_message(empty_info)
                yield _sse("part", {"kind": "text", "body": user_msg})
                yield _sse("done", {
                    "finish_reason": finish_reason or "EMPTY",
                    "empty_info": empty_info,
                })
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
                    scrubbed = scrubber.scrub(cleaned)
                    log.write("assistant_text", body=scrubbed, finish_reason=finish_reason)
                    yield _sse("part", {"kind": "text", "body": scrubbed})
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
                log.write("done", finish_reason=finish_reason or "STOP",
                          totals=usage.request_totals())
                yield _sse("done", {
                    "finish_reason": finish_reason or "STOP",
                    "request_totals": usage.request_totals(),
                })
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

                log.write("tool_call", call_id=call_id, name=fc.name,
                          args=args_json, status="running")

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

                log.write("tool_result", call_id=call_id, name=fc.name,
                          status="failed" if is_error else "success",
                          duration_ms=duration_ms, result=scrubbed_result)

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

                # Side effect: if the tool was ``emit_artifact_pill``,
                # also emit a corresponding ``artifact_pill`` part with
                # the parsed data so the frontend can open the side pane
                # and render the rich view. The tool returns a normal
                # confirmation string (above); the pill is a separate
                # SSE event keyed off the same call.
                if fc.name == "emit_artifact_pill" and not is_error:
                    pill = _build_artifact_pill_from_args(args, scrubber)
                    if pill is not None:
                        log.write("artifact_pill", **pill)
                        yield _sse("part", {"kind": "artifact_pill", **pill})

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
        log.write("max_rounds_reached", totals=usage.request_totals())
        yield _sse("part", {
            "kind": "text",
            "body": "_(Reached the tool-call round limit. Ending turn — ask again to continue.)_",
        })
        yield _sse("done", {
            "finish_reason": "MAX_TOOL_ROUNDS",
            "request_totals": usage.request_totals(),
        })
    finally:
        # Flush + close the transcript file. Runs even if the generator
        # is closed early (client disconnect, downstream exception).
        log.close()
