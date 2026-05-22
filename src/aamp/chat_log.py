"""Transcript logger for the chat client.

Writes every chat session to two files in ``logs/``:

- ``chat_<timestamp>.jsonl`` — one event per line, machine-readable.
  Events: ``session_start``, ``user``, ``assistant_text``, ``tool_call``,
  ``tool_result``, ``token_usage``, ``error``, ``session_reset``,
  ``session_end`` (the last carries the accumulated session totals).

- ``chat_<timestamp>.md`` — human-readable transcript with collapsible
  ``<details>`` blocks around tool results so the scrollback is scannable.

Both files are line-buffered so they're complete-up-to-the-crash if the
process dies mid-conversation. Tool results are stored in full; nothing
is truncated. The logger does not filter sensitive content (system prompt
is logged once at the session_start line) — be aware if you share transcripts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Scrubber — strips known secret values out of logged text
# ---------------------------------------------------------------------------

class Scrubber:
    """Replaces every literal occurrence of any registered secret with a mask.

    Used to defend the on-disk chat transcript against accidental leakage —
    e.g. if a tool result somehow includes a password, the substring gets
    masked before the JSONL/Markdown write. Defense in depth: the upstream
    layers (VAPIX scrubber in device.py, chat agent behavior) should
    already prevent this, but the transcript is the last writable copy.

    Substrings shorter than :attr:`MIN_LEN` are silently skipped — replacing
    a 4-character password like "axis" would corrupt every occurrence of
    that word in unrelated text. Short passwords aren't safe anyway.

    Idempotent. Safe to call on already-scrubbed strings.
    """

    MASK = "********"        # fixed length, no character-count leak
    MIN_LEN = 6

    def __init__(self, secret_values: Iterable[str]) -> None:
        # Sort by length descending so longer values are replaced first —
        # handles cases where one secret is a prefix of another.
        self._values = sorted(
            {v for v in secret_values if v and len(v) >= self.MIN_LEN},
            key=len, reverse=True,
        )

    def scrub(self, text: str) -> str:
        """Mask every registered secret in ``text``."""
        if not text or not self._values:
            return text
        out = text
        for v in self._values:
            if v in out:
                out = out.replace(v, self.MASK)
        return out

    def scrub_obj(self, obj: Any) -> Any:
        """Recursively walk ``obj`` (dict/list/tuple/str) and scrub every string leaf."""
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, dict):
            return {k: self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub_obj(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.scrub_obj(v) for v in obj)
        return obj


def _null_scrubber() -> Scrubber:
    """A no-op scrubber for callers that don't want filtering (tests)."""
    return Scrubber([])


# ---------------------------------------------------------------------------
# Token usage accumulator
# ---------------------------------------------------------------------------

@dataclass
class UsageAccumulator:
    """Running totals of Gemini token usage across a chat session.

    Mirrors the fields exposed by ``GenerateContentResponseUsageMetadata``
    in the google-genai SDK. Anything Gemini doesn't report stays zero.
    """
    turns: int = 0
    prompt_tokens: int = 0           # request side (input)
    candidates_tokens: int = 0       # response side (output)
    cached_tokens: int = 0           # prompt cache hits
    thoughts_tokens: int = 0         # extended-thinking output (when enabled)
    tool_use_prompt_tokens: int = 0  # overhead from injecting tool declarations
    total_tokens: int = 0            # SDK-reported total (may exceed sum of others)

    def add(self, usage_metadata: Any) -> dict[str, int]:
        """Fold one turn's usage_metadata into the running totals.

        Returns the per-turn dict for logging.
        """
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
        self.prompt_tokens += turn["prompt_tokens"]
        self.candidates_tokens += turn["candidates_tokens"]
        self.cached_tokens += turn["cached_tokens"]
        self.thoughts_tokens += turn["thoughts_tokens"]
        self.tool_use_prompt_tokens += turn["tool_use_prompt_tokens"]
        self.total_tokens += turn["total_tokens"]
        return turn

    def summary_line(self) -> str:
        """One-line human-readable summary for the REPL footer."""
        parts = [f"{self.turns} turn(s)"]
        if self.prompt_tokens or self.candidates_tokens:
            parts.append(f"{self.prompt_tokens:,} in + {self.candidates_tokens:,} out")
        extras: list[str] = []
        if self.cached_tokens:
            extras.append(f"{self.cached_tokens:,} cached")
        if self.thoughts_tokens:
            extras.append(f"{self.thoughts_tokens:,} thinking")
        if self.tool_use_prompt_tokens:
            extras.append(f"{self.tool_use_prompt_tokens:,} tool-overhead")
        if extras:
            parts.append("(" + ", ".join(extras) + ")")
        if self.total_tokens:
            parts.append(f"= {self.total_tokens:,} total")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, int]:
        return {
            "turns": self.turns,
            "prompt_tokens": self.prompt_tokens,
            "candidates_tokens": self.candidates_tokens,
            "cached_tokens": self.cached_tokens,
            "thoughts_tokens": self.thoughts_tokens,
            "tool_use_prompt_tokens": self.tool_use_prompt_tokens,
            "total_tokens": self.total_tokens,
        }


class TranscriptLogger:
    """Append-only chat transcript writer (sync file I/O; one writer per session).

    Optionally accepts a :class:`Scrubber` that is applied to all logged
    text before disk write. Use this to keep secrets out of the on-disk
    transcript — see :meth:`aamp.chat.run_chat` for the wiring.
    """

    def __init__(self, log_dir: Path, *, scrubber: Optional[Scrubber] = None) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = log_dir / f"chat_{self.session_id}.jsonl"
        self.md_path = log_dir / f"chat_{self.session_id}.md"
        self._jsonl = self.jsonl_path.open("a", encoding="utf-8", buffering=1)
        self._md = self.md_path.open("a", encoding="utf-8", buffering=1)
        self._scrubber = scrubber or _null_scrubber()

    def _s(self, text: str) -> str:
        """Shorthand for scrubbing a single string."""
        return self._scrubber.scrub(text)

    def _so(self, obj: Any) -> Any:
        """Shorthand for scrubbing an arbitrary object tree."""
        return self._scrubber.scrub_obj(obj)

    # -- private helpers --------------------------------------------------

    @staticmethod
    def _ts() -> str:
        return datetime.now().isoformat(timespec="milliseconds")

    def _write_jsonl(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", self._ts())
        try:
            self._jsonl.write(json.dumps(event, default=str) + "\n")
        except Exception:
            # Logging must never crash the chat.
            pass

    def _write_md(self, text: str) -> None:
        try:
            self._md.write(text)
            if not text.endswith("\n"):
                self._md.write("\n")
        except Exception:
            pass

    @staticmethod
    def _safe_fence(content: str) -> str:
        """Pick a code fence that won't collide with content."""
        if "````" in content:
            return "`````"
        if "```" in content:
            return "````"
        return "```"

    # -- public logging API ----------------------------------------------

    def log_session_start(
        self,
        *,
        model: str,
        system_prompt_path: Any,
        system_prompt_chars: int,
        tools_count: int,
        system_prompt_text: Optional[str] = None,
    ) -> None:
        ts = self._ts()
        self._write_jsonl({
            "kind": "session_start",
            "model": model,
            "system_prompt_path": str(system_prompt_path),
            "system_prompt_chars": system_prompt_chars,
            "tools_count": tools_count,
            # System prompt logged once for full reproducibility; scrubber
            # is still applied so any password value that appears in the
            # prompt (shouldn't!) gets masked.
            "system_prompt": self._s(system_prompt_text) if system_prompt_text else None,
        })
        self._write_md(f"# Chat transcript — {ts}\n\n")
        self._write_md(f"- **Model:** `{model}`\n")
        self._write_md(f"- **System prompt:** `{system_prompt_path}` ({system_prompt_chars} chars)\n")
        self._write_md(f"- **Tools loaded:** {tools_count}\n\n")
        self._write_md("---\n\n")

    def log_user(self, text: str) -> None:
        text = self._s(text)
        self._write_jsonl({"kind": "user", "text": text})
        self._write_md(f"## You — {self._ts()}\n\n{text}\n\n")

    def log_assistant_text(self, text: str, *, finish_reason: Optional[str] = None) -> None:
        text = self._s(text)
        self._write_jsonl({"kind": "assistant_text", "text": text, "finish_reason": finish_reason})
        header = f"## Assistant — {self._ts()}"
        if finish_reason and finish_reason not in ("STOP", "TOOL_USE"):
            header += f"  _(finish: {finish_reason})_"
        self._write_md(f"{header}\n\n{text}\n\n")

    def log_tool_call(self, name: str, args: dict[str, Any], *, call_id: Optional[str] = None) -> None:
        args = self._so(args)
        self._write_jsonl({"kind": "tool_call", "name": name, "args": args, "call_id": call_id})
        self._write_md(f"### Tool call: `{name}`")
        if call_id:
            self._write_md(f"  _(id: {call_id})_")
        self._write_md("\n\n")
        if args:
            pretty = json.dumps(args, indent=2, default=str)
            fence = self._safe_fence(pretty)
            self._write_md(f"{fence}json\n{pretty}\n{fence}\n\n")
        else:
            self._write_md("_(no args)_\n\n")

    def log_tool_result(self, name: str, result: str, *, call_id: Optional[str] = None,
                         is_error: bool = False) -> None:
        result = self._s(result or "")
        chars = len(result)
        self._write_jsonl({
            "kind": "tool_result",
            "name": name,
            "call_id": call_id,
            "result": result,
            "result_chars": chars,
            "is_error": is_error,
        })
        label = "ERROR" if is_error else "result"
        summary = f"{name} {label} — {chars} chars"
        fence = self._safe_fence(result)
        self._write_md(f"<details><summary>{summary}</summary>\n\n")
        self._write_md(f"{fence}\n{result}\n{fence}\n\n")
        self._write_md("</details>\n\n")

    def log_error(self, kind: str, message: str) -> None:
        self._write_jsonl({"kind": "error", "error_kind": kind, "message": message})
        self._write_md(f"### ERROR ({kind})\n\n```\n{message}\n```\n\n")

    def log_token_usage(self, per_turn: dict[str, int], running_total: dict[str, int]) -> None:
        """Per-turn token usage (Gemini ``response.usage_metadata``). Recorded
        in JSONL only — the markdown view stays focused on the conversation.
        """
        self._write_jsonl({"kind": "token_usage", "turn": per_turn, "running": running_total})

    def log_session_reset(self) -> None:
        self._write_jsonl({"kind": "session_reset"})
        self._write_md("---\n\n_(conversation reset)_\n\n---\n\n")

    def log_session_end(self, usage_summary: Optional[dict[str, int]] = None) -> None:
        """Final event of a session. Carries the accumulated usage totals."""
        self._write_jsonl({"kind": "session_end", "usage": usage_summary or {}})
        if usage_summary:
            self._write_md("---\n\n## Session totals\n\n")
            for k, v in usage_summary.items():
                self._write_md(f"- **{k}:** {v:,}\n")
            self._write_md("\n")

    def close(self, usage_summary: Optional[dict[str, int]] = None) -> None:
        self.log_session_end(usage_summary)
        for fh in (self._jsonl, self._md):
            try:
                fh.close()
            except Exception:
                pass

    def __enter__(self) -> "TranscriptLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Null logger (used when --no-log is passed)
# ---------------------------------------------------------------------------

class NullLogger:
    """No-op logger with the same API. ``isinstance`` check not needed —
    callers can use whichever is wired in."""

    jsonl_path = None
    md_path = None

    def log_session_start(self, **_kw) -> None: pass
    def log_user(self, _t: str) -> None: pass
    def log_assistant_text(self, _t: str, **_kw) -> None: pass
    def log_tool_call(self, _n: str, _a: dict, **_kw) -> None: pass
    def log_tool_result(self, _n: str, _r: str, **_kw) -> None: pass
    def log_error(self, _k: str, _m: str) -> None: pass
    def log_token_usage(self, _t: dict, _r: dict) -> None: pass
    def log_session_reset(self) -> None: pass
    def log_session_end(self, _s: dict | None = None) -> None: pass
    def close(self, _s: dict | None = None) -> None: pass
    def __enter__(self) -> "NullLogger": return self
    def __exit__(self, *exc) -> None: pass
