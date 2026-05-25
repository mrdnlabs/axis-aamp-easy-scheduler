"""CLI to drive the running aamp-server chat endpoint programmatically.

Useful for diagnostics (reproducing UI behavior from a script), for
regression smoke tests, and for asking the chat backend questions
without spinning up the web UI. The chat backend is stateless on the
wire, so this client maintains its own history across messages.

Example::

    aamp-chat-send "hi"
    aamp-chat-send --multiline           # paste text, end with Ctrl+Z (or Ctrl+D)
    aamp-chat-send --history history.json "what changed?"
    aamp-chat-send --raw "hi"            # dump raw SSE events

The script POSTs to ``/api/chat/message`` (defaulting to the local
sidecar at http://127.0.0.1:7331) and prints each SSE event as it
arrives. Returns 0 on a clean ``done`` event, non-zero on errors or
empty responses (so it's usable in CI).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------


def _parse_sse_event(raw: bytes) -> tuple[str, Any]:
    """Decode one SSE record (lines separated by single newline,
    records separated by blank line) into ``(event, data)``.

    Mirrors the parser in ``web/lib/api.ts`` so we render the same
    way the browser does.
    """
    event = "message"
    data_lines: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return event, None
    data_str = "\n".join(data_lines)
    try:
        return event, json.loads(data_str)
    except json.JSONDecodeError:
        return event, data_str


# ---------------------------------------------------------------------------
# Pretty-printing
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _render_event(event: str, data: Any, *, raw: bool) -> None:
    """Print one parsed SSE event. The ``raw`` flag dumps the whole
    payload verbatim (JSON pretty-printed) — useful when chasing a
    backend bug. The default rendering is concise and oriented at
    "what did the user see"."""
    if raw:
        print(f"--- event: {event} ---")
        if data is None:
            print("(no data)")
        elif isinstance(data, str):
            print(data)
        else:
            print(json.dumps(data, indent=2, default=str))
        return

    if event == "session":
        sid = (data or {}).get("session_id")
        tp = (data or {}).get("transcript_path")
        print(f"[session]      id={sid}")
        if tp:
            print(f"               transcript={tp}")
        return

    if event == "usage":
        per = (data or {}).get("per_turn") or {}
        tot = (data or {}).get("request_totals") or {}
        print(
            f"[usage]        prompt={per.get('prompt_tokens')}"
            f"  candidates={per.get('candidates_tokens')}"
            f"  cached={per.get('cached_tokens')}"
            f"  total={per.get('total_tokens')}"
        )
        return

    if event == "error":
        d = data or {}
        print(f"[error]        stage={d.get('stage')!r}  detail={d.get('detail')!r}")
        return

    if event == "done":
        d = data or {}
        print(f"[done]         finish_reason={d.get('finish_reason')!r}")
        ei = d.get("empty_info")
        if ei:
            print(f"               empty_info={json.dumps(ei, default=str)}")
        return

    if event == "part":
        d = data or {}
        kind = d.get("kind")
        if kind == "text":
            print(f"[text]         {d.get('body', '')}")
        elif kind == "tool_call":
            status = d.get("status")
            name = d.get("name")
            cid = (d.get("call_id") or "")[-8:]
            dur = d.get("duration_ms")
            if status == "running":
                print(f"[tool_call ▶]  {name}  call_id=…{cid}")
                if d.get("args"):
                    for ln in str(d["args"]).splitlines():
                        print(f"               args: {ln}")
            else:
                tag = "✓" if status == "success" else "✗"
                dur_s = f"  {dur}ms" if dur is not None else ""
                print(f"[tool_call {tag}]  {name}  call_id=…{cid}{dur_s}")
                if d.get("result"):
                    print(f"               result: {_truncate(str(d['result']), 400)}")
        elif kind == "artifact_pill":
            print(
                f"[artifact]     {d.get('artifact')}  key={d.get('key')!r}  title={d.get('title')!r}"
            )
            if d.get("data"):
                print(f"               data={_truncate(json.dumps(d['data'], default=str), 200)}")
        elif kind == "schedule_diff":
            print(f"[diff]         {d.get('title')!r}  changes={len(d.get('changes', []))}")
        elif kind == "secure_capture":
            print(f"[capture]      {d.get('credential_key')}")
        else:
            print(f"[part:{kind}]   {json.dumps(d, default=str)[:200]}")
        return

    # Anything else.
    print(f"[?{event}]      {json.dumps(data, default=str)[:200]}")


# ---------------------------------------------------------------------------
# HTTP I/O
# ---------------------------------------------------------------------------


def stream_chat_message(
    text: str,
    *,
    history: list[dict[str, str]] | None = None,
    session_id: str | None = None,
    server: str = "http://127.0.0.1:7331",
    timeout: float = 180.0,
) -> dict[str, Any]:
    """POST one message to the chat endpoint and stream the response.

    Yields nothing — this is a synchronous helper that prints events
    as they arrive and returns a result summary at the end. Returns a
    dict::

        {
            "session_id": "...",
            "transcript_path": "...",
            "finish_reason": "STOP" | "EMPTY" | ...,
            "events": [...],
            "text_replies": [...],
            "tool_calls": [{"name", "status", "duration_ms"}],
            "empty_info": {...} | None,
            "elapsed_ms": int,
        }

    Raises ``RuntimeError`` if the HTTP request itself fails (server
    unreachable, non-2xx response). In-stream ``error`` SSE events are
    recorded in the return dict, not raised.
    """
    import urllib.error
    import urllib.request

    payload = {
        "text": text,
        "history": history or [],
        "session_id": session_id or str(uuid.uuid4()),
    }
    url = f"{server.rstrip('/')}/api/chat/message"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    summary: dict[str, Any] = {
        "session_id": payload["session_id"],
        "transcript_path": None,
        "finish_reason": None,
        "events": [],
        "text_replies": [],
        "tool_calls": [],
        "empty_info": None,
        "elapsed_ms": 0,
    }
    t0 = time.monotonic()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buf = b""
            saw_done = False
            while not saw_done:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    raw, _, buf = buf.partition(b"\n\n")
                    event, data = _parse_sse_event(raw)
                    if not event:
                        continue
                    summary["events"].append({"event": event, "data": data})
                    _on_event(event, data, summary)
                    yield event, data
                    if event == "done":
                        # Server closes the stream right after ``done``.
                        # Stop reading immediately so we don't block on
                        # the next read() call.
                        saw_done = True
                        break
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"connection failed: {e.reason}. Is aamp-server running on {server}?"
        ) from e

    summary["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return summary


def _on_event(event: str, data: Any, summary: dict[str, Any]) -> None:
    """Mutate the summary dict with this event's data. Pulled out so
    tests can drive ``_on_event`` directly with synthesized events."""
    if event == "session" and isinstance(data, dict):
        summary["transcript_path"] = data.get("transcript_path")
    elif event == "done" and isinstance(data, dict):
        summary["finish_reason"] = data.get("finish_reason")
        if data.get("empty_info"):
            summary["empty_info"] = data["empty_info"]
    elif event == "part" and isinstance(data, dict):
        kind = data.get("kind")
        if kind == "text":
            summary["text_replies"].append(data.get("body", ""))
        elif kind == "tool_call":
            summary["tool_calls"].append({
                "name": data.get("name"),
                "status": data.get("status"),
                "duration_ms": data.get("duration_ms"),
                "call_id": data.get("call_id"),
            })


# ---------------------------------------------------------------------------
# Console entry point — `aamp-chat-send`
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    # Windows consoles default to cp1252; force UTF-8 so the unicode
    # arrows + checkmarks we use in the friendly renderer don't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(
        prog="aamp-chat-send",
        description=__doc__.splitlines()[0] if __doc__ else None,
    )
    parser.add_argument("text", nargs="?", help="Message text to send. Omit to read from stdin.")
    parser.add_argument("--server", default="http://127.0.0.1:7331",
                        help="Sidecar base URL (default: http://127.0.0.1:7331)")
    parser.add_argument("--session-id", default=None,
                        help="Session id (default: random uuid; supply to continue an existing transcript)")
    parser.add_argument("--history", type=Path, default=None,
                        help="Path to a JSON file with prior messages: [{role, text}, ...]")
    parser.add_argument("--save-history", type=Path, default=None,
                        help="Append this turn (user + assistant) to the given history JSON")
    parser.add_argument("--raw", action="store_true",
                        help="Print raw SSE events (full JSON payload) instead of the friendly view.")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout, seconds")
    args = parser.parse_args(argv)

    if args.text is None:
        text = sys.stdin.read().strip()
        if not text:
            print("ERROR: no message text on stdin or argv", file=sys.stderr)
            return 2
    else:
        text = args.text

    history: list[dict[str, str]] = []
    if args.history and args.history.exists():
        history = json.loads(args.history.read_text(encoding="utf-8"))

    print(f"→ POST {args.server}/api/chat/message")
    print(f"  text: {text!r}")
    print(f"  history: {len(history)} prior turn(s)")
    print()

    summary: dict[str, Any] = {}
    try:
        gen = stream_chat_message(
            text,
            history=history,
            session_id=args.session_id,
            server=args.server,
            timeout=args.timeout,
        )
        # The generator yields (event, data) tuples; the final return
        # value (a dict) we recover by inspecting its StopIteration.
        try:
            while True:
                event, data = next(gen)
                _render_event(event, data, raw=args.raw)
        except StopIteration as stop:
            summary = stop.value or {}
    except RuntimeError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 3

    print()
    print("─" * 70)
    print(f"session_id      : {summary.get('session_id')}")
    print(f"transcript      : {summary.get('transcript_path')}")
    print(f"finish_reason   : {summary.get('finish_reason')}")
    print(f"text_replies    : {len(summary.get('text_replies') or [])}")
    print(f"tool_calls      : {len(summary.get('tool_calls') or [])}")
    if summary.get("empty_info"):
        print(f"empty_info      : {json.dumps(summary['empty_info'], default=str)}")
    print(f"elapsed         : {summary.get('elapsed_ms')} ms")

    if args.save_history is not None:
        assistant_text = "\n\n".join(summary.get("text_replies") or [])
        new_hist = list(history) + [
            {"role": "user", "text": text},
            {"role": "assistant", "text": assistant_text},
        ]
        args.save_history.write_text(
            json.dumps(new_hist, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"saved history → {args.save_history}")

    # Exit non-zero on empty / error finishes — useful for CI loops.
    fr = summary.get("finish_reason")
    if fr in (None, "EMPTY"):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
