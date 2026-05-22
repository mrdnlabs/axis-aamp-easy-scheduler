"""Interactive chat client for AampEasyScheduler — Gemini edition.

Drives a Google Gemini conversation against the AAM Pro MCP tool surface.
Tools are loaded from the existing :mod:`aamp.mcp_server` in-process — no
subprocess plumbing — so we share one Python interpreter, one OAuth session,
one set of cached objects. The MCP server can still run as its own stdio
process for external clients (Claude Desktop, voice frontends, etc.).

Usage:

    # Set your Gemini API key first (either env var name works):
    $env:GEMINI_API_KEY = "AIza..."
    # or:  $env:GOOGLE_API_KEY = "AIza..."

    # Then:
    aamp-chat                          # default model: gemini-3.5-flash
    aamp-chat --model gemini-3.1-pro-preview
    aamp-chat --debug                  # print every tool call + JSON

The Gemini SDK is the new unified ``google-genai`` package (NOT the
deprecated ``google-generativeai``). API surfaces here:
  client.chats.create(model=, config=)        — chat session
  chat.send_message(text_or_parts)            — single turn (sync)
  types.GenerateContentConfig(...)            — system_instruction, tools, etc.
  types.FunctionDeclaration(...)              — tool schema
  types.Part.from_function_response(...)      — tool result to send back

Tool calls are returned as ``response.function_calls`` (a flat list across
parts). Multiple parallel calls in one turn are supported.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .chat_log import NullLogger, TranscriptLogger, UsageAccumulator
from .mcp_server import mcp


DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Latest Gemini model lineup (May 2026) — list shown in --help epilog.
MODEL_NOTES = """\
Common model ids (May 2026):
  gemini-3.5-flash             workhorse, just released; recommended (default)
  gemini-3.1-pro-preview       most capable; preview tier
  gemini-3.1-flash-lite        cheapest / fastest
  gemini-2.5-pro               older stable Pro
  gemini-2.5-flash             older stable Flash
  gemini-3.1-flash-live-preview  realtime / voice (separate use case)

Authentication: set GEMINI_API_KEY or GOOGLE_API_KEY in your environment.
"""

# JSON Schema keys Gemini's parameters_json_schema accepts. Anything outside
# this whitelist is stripped from tool schemas before sending. FastMCP can
# emit extras like ``additionalProperties``, ``$schema``, ``title`` which
# may or may not be accepted depending on the model.
ALLOWED_SCHEMA_KEYS = {
    "type", "description", "enum", "format", "items", "properties",
    "required", "nullable", "default", "anyOf", "oneOf",
    "minimum", "maximum", "minItems", "maxItems",
    "minLength", "maxLength", "pattern",
}

# Tool names that on FastMCP can have schemas that Gemini balks at —
# specifically tools with ``dict`` parameters (e.g., ``operations``,
# ``interval``). We'll log but still send them; can extend if needed.
DEBUG_SCHEMAS = False

ANSI = {
    "reset": "\033[0m", "dim": "\033[2m", "bold": "\033[1m",
    "cyan": "\033[36m", "yellow": "\033[33m", "green": "\033[32m",
    "red": "\033[31m", "gray": "\033[90m",
}


def color(s: str, c: str, *, enabled: bool = True) -> str:
    if not enabled:
        return s
    return f"{ANSI.get(c, '')}{s}{ANSI['reset']}"


def load_system_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"system prompt not found at {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Schema sanitization for Gemini's parameters_json_schema
# ---------------------------------------------------------------------------

def sanitize_schema(schema: Any) -> Any:
    """Recursively strip JSON Schema keys Gemini doesn't accept.

    Walks a schema and removes keys outside ``ALLOWED_SCHEMA_KEYS`` at the
    schema-level. Special-cases the container fields so we don't accidentally
    strip user-defined property names:

      - ``properties`` is ``{name: <sub-schema>}`` — keep the names verbatim,
        recurse into each sub-schema.
      - ``items`` is a single sub-schema — recurse.
      - ``anyOf`` / ``oneOf`` are lists of sub-schemas — recurse over each.
      - ``required`` is a list of strings — keep as-is.
      - ``enum`` is a list of literal values — keep as-is.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k not in ALLOWED_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {prop_name: sanitize_schema(sub) for prop_name, sub in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = sanitize_schema(v)
        elif k in ("anyOf", "oneOf") and isinstance(v, list):
            out[k] = [sanitize_schema(sub) for sub in v]
        elif k in ("required", "enum"):
            out[k] = list(v) if isinstance(v, list) else v
        else:
            out[k] = v
    if "properties" in out and "type" not in out:
        out["type"] = "object"
    return out


# ---------------------------------------------------------------------------
# MCP → Gemini tool translation
# ---------------------------------------------------------------------------

async def load_gemini_tools() -> list[types.Tool]:
    """Pull MCP tool definitions and translate to ``types.Tool`` for Gemini."""
    mcp_tools = await mcp.list_tools()
    declarations: list[types.FunctionDeclaration] = []
    for t in mcp_tools:
        schema = sanitize_schema(t.inputSchema or {"type": "object", "properties": {}})
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}
        declarations.append(types.FunctionDeclaration(
            name=t.name,
            description=(t.description or "").strip(),
            parameters_json_schema=schema,
        ))
    if DEBUG_SCHEMAS:
        for d in declarations[:3]:
            print(f"  {d.name}: {json.dumps(d.parameters_json_schema, indent=2)[:300]}")
    # All declarations go inside one Tool; Gemini supports multiple
    # declarations in one Tool object.
    return [types.Tool(function_declarations=declarations)]


async def call_mcp_tool(name: str, args: dict[str, Any]) -> str:
    """Invoke an MCP tool and return its rendered text result."""
    try:
        result = await mcp.call_tool(name, args)
    except Exception as e:  # noqa: BLE001
        return f"TOOL_ERROR: {type(e).__name__}: {e}"
    content = result[0] if isinstance(result, tuple) else result
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            text = getattr(c, "text", None)
            if text is not None:
                parts.append(text)
            else:
                parts.append(str(c))
        return "\n".join(parts) if parts else ""
    return str(content)


# ---------------------------------------------------------------------------
# Gemini chat loop
# ---------------------------------------------------------------------------

async def run_user_turn(
    chat: Any,
    user_input: str,
    *,
    debug: bool,
    use_color: bool,
    logger: Any,
    usage: UsageAccumulator,
) -> None:
    """Send one user message and resolve any number of tool-use rounds.

    Each round:
      1. Send the message (or, on follow-up rounds, a list of tool-result Parts).
      2. Read the response's text + function calls.
      3. Dispatch any tool calls via the in-process MCP server.
      4. If tool calls happened, loop with the tool results as the next message.
      5. Else, print the final text and return.

    Every interaction (user input, model text, tool call, tool result, error)
    is forwarded to the logger.
    """
    message: Any = user_input
    while True:
        try:
            response = chat.send_message(message)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            print(color(f"\n[Gemini API error] {msg}", "red", enabled=use_color))
            logger.log_error("gemini_api", msg)
            return

        # Record token usage for this turn (logged + accumulated).
        per_turn = usage.add(getattr(response, "usage_metadata", None))
        if per_turn:
            logger.log_token_usage(per_turn, usage.to_dict())
            if debug:
                in_t = per_turn.get("prompt_tokens", 0)
                out_t = per_turn.get("candidates_tokens", 0)
                total = per_turn.get("total_tokens", 0)
                extras: list[str] = []
                if per_turn.get("cached_tokens"):
                    extras.append(f"{per_turn['cached_tokens']:,} cached")
                if per_turn.get("thoughts_tokens"):
                    extras.append(f"{per_turn['thoughts_tokens']:,} thinking")
                tail = (" (" + ", ".join(extras) + ")") if extras else ""
                print(color(f"[usage: {in_t:,} in + {out_t:,} out = {total:,} total{tail}]", "gray", enabled=use_color))

        # Pull all text + function_call parts from the response.
        text_chunks: list[str] = []
        function_calls: list[types.FunctionCall] = []
        candidate = response.candidates[0] if response.candidates else None
        finish_reason = candidate.finish_reason.name if candidate and candidate.finish_reason else None
        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if getattr(part, "function_call", None):
                    function_calls.append(part.function_call)
                elif getattr(part, "text", None):
                    text_chunks.append(part.text)

        # Print + log any text the model produced this round.
        for t in text_chunks:
            if t.strip():
                print()
                print(t.rstrip())
                logger.log_assistant_text(t.rstrip(), finish_reason=finish_reason)

        if not function_calls:
            # No tool calls → we're done with this user turn.
            # Helpful diagnostic for unusual finish reasons.
            if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
                print(color(f"\n[finish_reason: {finish_reason}]", "yellow", enabled=use_color))
                if not text_chunks:
                    # Log unusual finish even if there was no text.
                    logger.log_assistant_text("", finish_reason=finish_reason)
            return

        # Dispatch each tool call and collect the response Parts.
        tool_parts: list[types.Part] = []
        for fc in function_calls:
            args = dict(fc.args or {})
            call_id = getattr(fc, "id", None)
            logger.log_tool_call(fc.name, args, call_id=call_id)
            if debug:
                pretty = json.dumps(args, indent=2, default=str)
                print(color(f"\n[tool] {fc.name}({pretty})", "gray", enabled=use_color))
            else:
                preview = ", ".join(f"{k}={json.dumps(v, default=str)[:30]}" for k, v in args.items())
                print(color(f"\n[{fc.name}({preview})]", "gray", enabled=use_color))
            result_text = await call_mcp_tool(fc.name, args)
            is_error = result_text.startswith("TOOL_ERROR:")
            logger.log_tool_result(fc.name, result_text, call_id=call_id, is_error=is_error)
            if debug:
                shown = result_text if len(result_text) <= 800 else result_text[:800] + "...[truncated]"
                print(color(f"[result] {shown}", "gray", enabled=use_color))
            # NOTE: ``Part.from_function_response()`` helper doesn't expose ``id``.
            # We construct the ``FunctionResponse`` directly so the SDK can match
            # parallel calls back to their originating ``function_call.id``.
            fr = types.FunctionResponse(
                name=fc.name,
                response={"result": result_text},
                id=call_id,
            )
            tool_parts.append(types.Part(function_response=fr))
        # Loop back with tool results as the next message.
        message = tool_parts


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

PROMPT = "You> "

# Inline file size cap for `/attach`. Gemini accepts up to 20MB inline; we use
# a conservative 18MB so the encoded request stays under the 20MB limit.
INLINE_FILE_CAP_BYTES = 18 * 1024 * 1024

# MIME types Gemini natively understands well. Other types still attempt but
# may not be parsed (e.g., DOCX/XLSX often need conversion to PDF first).
GEMINI_SUPPORTED_MIMES = {
    "application/pdf",
    "text/plain", "text/csv", "text/markdown", "text/html",
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/heic", "image/heif",
    "audio/wav", "audio/mp3", "audio/aac", "audio/ogg", "audio/flac",
    "video/mp4", "video/mpeg", "video/mov", "video/webm",
}

# Extension → MIME fallback for cases where mimetypes.guess_type doesn't know.
EXT_MIME_FALLBACK = {
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".json": "application/json",
    ".yaml": "text/plain",
    ".yml": "text/plain",
    ".xml": "text/xml",
}


def detect_mime(path: Path) -> str:
    """Best-effort MIME detection from extension."""
    mt, _ = mimetypes.guess_type(str(path))
    if mt:
        return mt
    return EXT_MIME_FALLBACK.get(path.suffix.lower(), "application/octet-stream")


def detect_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def load_attachment(path: Path) -> tuple[types.Part, dict]:
    """Read a file and return a Gemini Part plus a metadata dict (for logging).

    Returns (part, info). ``info`` has keys: path, name, mime, size_bytes, gemini_supported.
    Raises if the file is too large for inline upload (>18 MB) — we'd need to use
    the Files API for those, not yet wired in.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    size = path.stat().st_size
    if size > INLINE_FILE_CAP_BYTES:
        raise ValueError(
            f"File too large for inline attach ({size:,} bytes > {INLINE_FILE_CAP_BYTES:,}). "
            f"Files API support not yet wired — convert/split the file first."
        )
    mime = detect_mime(path)
    data = path.read_bytes()
    part = types.Part.from_bytes(data=data, mime_type=mime)
    info = {
        "path": str(path),
        "name": path.name,
        "mime": mime,
        "size_bytes": size,
        "gemini_supported": mime in GEMINI_SUPPORTED_MIMES,
    }
    return part, info


async def run_repl(
    *,
    model: str,
    system_prompt_path: Path,
    max_tokens: int,
    debug: bool,
    use_color: bool,
    log_dir: Path | None,
) -> int:
    if not detect_api_key():
        print(color("ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) not set.", "red", enabled=use_color))
        print("  Set it with:   $env:GEMINI_API_KEY = 'AIza...'")
        return 2

    system = load_system_prompt(system_prompt_path)
    tools = await load_gemini_tools()
    # google-genai picks up env vars automatically; explicit Client() is fine.
    client = genai.Client()

    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        max_output_tokens=max_tokens,
        # We are a controlled chat client — disable the SDK's auto-execution
        # of Python callables. The model returns function calls; we dispatch
        # them ourselves through the MCP server.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        # Mild safety relaxation for an internal tool — comment out if not needed.
        # safety_settings=[...],
        temperature=0.3,
    )

    chat = client.chats.create(model=model, config=config)

    # Tool count for display
    n_tools = sum(len(t.function_declarations or []) for t in tools)

    # Set up transcript logger (or null logger if disabled).
    # The scrubber holds every secret value we know about and replaces any
    # literal occurrence with a fixed-length mask before disk write. This
    # is defense-in-depth — VAPIX errors and tool returns are already
    # scrubbed upstream, but the transcript is the last writable copy and
    # any future leak path that bypasses upstream layers would land here.
    from .chat_log import Scrubber
    from .credentials import KNOWN_SECRETS, get_credential_store
    store = get_credential_store()
    scrubber_values: list[str] = []
    for s in KNOWN_SECRETS:
        val = store.get(s.account_id, s.field)
        if not val:
            continue
        if s.is_csv_list:
            # device.password_candidates is stored as CSV — split each entry.
            scrubber_values.extend(v.strip() for v in val.split(",") if v.strip())
        else:
            scrubber_values.append(val)
    scrubber = Scrubber(scrubber_values)

    logger: Any
    if log_dir is None:
        logger = NullLogger()
    else:
        logger = TranscriptLogger(log_dir, scrubber=scrubber)
        logger.log_session_start(
            model=model,
            system_prompt_path=system_prompt_path,
            system_prompt_chars=len(system),
            tools_count=n_tools,
            system_prompt_text=system,
        )
    usage = UsageAccumulator()

    print(color("AampEasyScheduler chat (Gemini)", "bold", enabled=use_color))
    print(color(f"  model:         {model}", "dim", enabled=use_color))
    print(color(f"  tools loaded:  {n_tools}", "dim", enabled=use_color))
    print(color(f"  system prompt: {system_prompt_path}  ({len(system)} chars)", "dim", enabled=use_color))
    if not isinstance(logger, NullLogger):
        print(color(f"  logging to:    {logger.md_path}", "dim", enabled=use_color))
    print(color(
        "  Type 'exit' to quit. '/reset' starts a fresh chat. '/history' shows turn count.\n"
        "  '/attach <path>' attaches a file (PDF/CSV/image) to the next message.\n"
        "  '/attachments' lists pending attachments. '/clear-attachments' drops them.",
        "dim", enabled=use_color))
    print()

    # Files attached via /attach that will be included with the next user message.
    pending_attachments: list[tuple[types.Part, dict]] = []

    try:
        while True:
            try:
                user_input = input(color(PROMPT, "cyan", enabled=use_color))
            except (EOFError, KeyboardInterrupt):
                print()
                break

            stripped = user_input.strip()
            cmd_lower = stripped.lower()
            if not stripped:
                continue
            if cmd_lower in ("exit", "quit", "/exit", "/quit"):
                break
            if cmd_lower == "/reset":
                chat = client.chats.create(model=model, config=config)
                print(color("(conversation reset)", "yellow", enabled=use_color))
                logger.log_session_reset()
                pending_attachments.clear()
                continue
            if cmd_lower == "/history":
                history = chat.get_history()
                print(color(f"(turns: {len(history)})", "yellow", enabled=use_color))
                continue
            if cmd_lower == "/attachments":
                if not pending_attachments:
                    print(color("(no pending attachments)", "yellow", enabled=use_color))
                else:
                    for _part, info in pending_attachments:
                        flag = "" if info["gemini_supported"] else " [mime not natively supported]"
                        print(color(
                            f"  - {info['name']}  {info['size_bytes']:,} bytes  ({info['mime']}){flag}",
                            "yellow", enabled=use_color))
                continue
            if cmd_lower == "/clear-attachments":
                n = len(pending_attachments)
                pending_attachments.clear()
                print(color(f"(cleared {n} pending attachment(s))", "yellow", enabled=use_color))
                continue
            if cmd_lower.startswith("/attach "):
                attach_path = Path(stripped[len("/attach "):].strip().strip('"').strip("'"))
                try:
                    part, info = load_attachment(attach_path)
                except (FileNotFoundError, ValueError) as e:
                    print(color(f"  ERROR: {e}", "red", enabled=use_color))
                    continue
                pending_attachments.append((part, info))
                support_note = "" if info["gemini_supported"] else " (warning: MIME not in Gemini's supported list — may be parsed as raw bytes)"
                print(color(
                    f"  attached: {info['name']} ({info['size_bytes']:,} bytes, {info['mime']}){support_note}",
                    "yellow", enabled=use_color))
                continue

            # Regular user message. If we have pending attachments, send them as a
            # list of Parts; otherwise send the plain text string.
            attachment_summary = ""
            if pending_attachments:
                attachment_summary = "  [+ " + ", ".join(
                    info["name"] for _p, info in pending_attachments
                ) + "]"
                logger.log_user(user_input + attachment_summary)
                parts = [types.Part.from_text(text=user_input)]
                parts.extend(p for p, _info in pending_attachments)
                # Log each attachment as a metadata-only event (don't log the bytes).
                for _p, info in pending_attachments:
                    logger.log_tool_call(
                        "user_attachment",
                        {"name": info["name"], "mime": info["mime"], "size_bytes": info["size_bytes"]},
                        call_id=None,
                    )
                pending_attachments.clear()
                message_to_send: Any = parts
            else:
                logger.log_user(user_input)
                message_to_send = user_input

            await run_user_turn(
                chat, message_to_send,
                debug=debug, use_color=use_color, logger=logger, usage=usage,
            )
            print()
    finally:
        # Final session usage summary — printed and logged.
        if usage.turns > 0:
            print(color(f"\nSession usage: {usage.summary_line()}", "dim", enabled=use_color))
        logger.close(usage.to_dict() if usage.turns > 0 else None)

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="aamp-chat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=MODEL_NOTES,
    )
    ap.add_argument("--model", default=os.environ.get("AAMP_CHAT_MODEL", DEFAULT_MODEL),
                    help=f"Gemini model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--max-tokens", type=int, default=4096,
                    help="max_output_tokens for each model response (default: 4096)")
    ap.add_argument("--system-prompt", type=Path, default=DEFAULT_SYSTEM_PROMPT_PATH,
                    help="path to system_prompt.md")
    ap.add_argument("--debug", action="store_true", help="Print full tool calls + results")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI escapes")
    ap.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR,
                    help=f"Directory for chat transcripts (default: {DEFAULT_LOG_DIR})")
    ap.add_argument("--no-log", action="store_true",
                    help="Disable transcript logging")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run_repl(
            model=args.model,
            system_prompt_path=args.system_prompt,
            max_tokens=args.max_tokens,
            debug=args.debug,
            use_color=not args.no_color,
            log_dir=None if args.no_log else args.log_dir,
        ))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
