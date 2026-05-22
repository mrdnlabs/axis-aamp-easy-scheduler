"""Smoke check: TranscriptLogger writes both JSONL and markdown correctly,
and UsageAccumulator folds Gemini usage_metadata fields correctly."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from aamp.chat_log import TranscriptLogger, UsageAccumulator


def test_usage_accumulator() -> None:
    """Verify accumulator handles realistic Gemini usage_metadata objects."""
    accum = UsageAccumulator()
    # Turn 1: standard
    meta1 = SimpleNamespace(
        prompt_token_count=1500,
        candidates_token_count=320,
        total_token_count=1820,
        cached_content_token_count=0,
        thoughts_token_count=0,
        tool_use_prompt_token_count=400,
    )
    per_turn = accum.add(meta1)
    assert per_turn["prompt_tokens"] == 1500
    assert per_turn["candidates_tokens"] == 320
    # Turn 2: with cache hit + thinking
    meta2 = SimpleNamespace(
        prompt_token_count=2000,
        candidates_token_count=180,
        total_token_count=2180,
        cached_content_token_count=1200,
        thoughts_token_count=450,
        tool_use_prompt_token_count=400,
    )
    accum.add(meta2)
    assert accum.turns == 2
    assert accum.prompt_tokens == 3500
    assert accum.candidates_tokens == 500
    assert accum.cached_tokens == 1200
    assert accum.thoughts_tokens == 450
    assert accum.tool_use_prompt_tokens == 800
    assert accum.total_tokens == 4000
    # None usage_metadata is gracefully ignored
    accum.add(None)
    assert accum.turns == 2  # unchanged
    print(f"UsageAccumulator OK — summary: {accum.summary_line()}")


def main() -> None:
    test_usage_accumulator()
    print()
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        with TranscriptLogger(log_dir) as logger:
            logger.log_session_start(
                model="gemini-3.5-flash",
                system_prompt_path="system_prompt.md",
                system_prompt_chars=8958,
                tools_count=27,
                system_prompt_text="You are AampEasyScheduler...",
            )
            logger.log_user("what do i currently have scheduled?")
            logger.log_tool_call("describe_site", {}, call_id="call_001")
            logger.log_tool_result(
                "describe_site",
                "# AXIS Audio Manager Pro\n\n## Destinations\n- destination01...\n",
                call_id="call_001",
            )
            logger.log_assistant_text(
                "Here's what's currently scheduled:\n\n- **destination01**: bell02 on Mon/Wed/Fri at 17:16, 18:16, 19:16, 20:16.\n",
                finish_reason="STOP",
            )
            logger.log_user("delete destination02")
            logger.log_tool_call("delete_destination", {"destination_id": 10}, call_id="call_002")
            logger.log_tool_result(
                "delete_destination",
                "TOOL_ERROR: ApiError: DELETE /webapi/v1/zones/10 -> 409: zone is referenced by active scheduler",
                call_id="call_002",
                is_error=True,
            )
            logger.log_assistant_text(
                "I can't delete destination02 — it's still being used by the background music scheduler. Want me to remove that schedule first?",
                finish_reason="STOP",
            )
            # Per-turn usage logging — uses dicts like UsageAccumulator emits.
            logger.log_token_usage(
                per_turn={"prompt_tokens": 1500, "candidates_tokens": 320, "total_tokens": 1820},
                running_total={"turns": 1, "prompt_tokens": 1500, "candidates_tokens": 320, "total_tokens": 1820},
            )
            session_usage = {"turns": 2, "prompt_tokens": 3500, "candidates_tokens": 500, "total_tokens": 4000}

        # __exit__ closes with no usage; do an explicit close-with-summary instead.
        # (But __exit__ already ran inside the `with`; verify by reading files.)
        jsonl = log_dir / f"chat_{logger.session_id}.jsonl"
        md = log_dir / f"chat_{logger.session_id}.md"
        print(f"JSONL: {jsonl.exists()} ({jsonl.stat().st_size} bytes)")
        print(f"MD:    {md.exists()} ({md.stat().st_size} bytes)")
        print()

        # Validate JSONL event sequence
        events = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line]
        kinds = [e["kind"] for e in events]
        print(f"JSONL events ({len(events)} total): {kinds}")
        expected = ["session_start", "user", "tool_call", "tool_result", "assistant_text",
                    "user", "tool_call", "tool_result", "assistant_text",
                    "token_usage", "session_end"]
        assert kinds == expected, f"unexpected event sequence: {kinds}"
        assert events[3]["result_chars"] > 0
        assert events[7]["is_error"] is True
        # token_usage event has per-turn + running fields
        assert events[9]["turn"]["prompt_tokens"] == 1500
        assert events[9]["running"]["total_tokens"] == 1820
        print("JSONL: event sequence + content OK (includes token_usage event)")

        # Validate markdown is readable and has key structure
        md_text = md.read_text(encoding="utf-8")
        print()
        print("=== MARKDOWN PREVIEW (first 1500 chars) ===")
        print(md_text[:1500])

        for marker in ("# Chat transcript", "## You", "### Tool call: `describe_site`",
                       "<details>", "## Assistant", "ERROR"):
            assert marker in md_text, f"missing marker: {marker!r}"
        print("\n=== ALL ASSERTIONS PASSED ===")


if __name__ == "__main__":
    main()
