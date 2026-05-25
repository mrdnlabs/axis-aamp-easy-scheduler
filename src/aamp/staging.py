"""Staged-diff registry for the apply-confirm-commit chat workflow.

The chat-first interface pattern (per ``docs/design/BRIEF.md``) is:

  1. The LLM understands the user's request and constructs a list of
     schedule changes as ``Operation`` objects.
  2. It calls :func:`stage` → receives a ``staging_id`` + diff summary
     ready to render in the chat as a ``ScheduleDiffCard``.
  3. The user reviews the diff inline; either confirms ("apply") or
     drops it ("discard").
  4. On confirm, the LLM calls :func:`apply` which dispatches each
     operation through the existing MCP write tools.

This module owns only the staging registry and the operation schema.
The actual dispatch (calling ``create_event``, ``schedule_template``,
etc.) lives in :mod:`aamp.mcp_server` to avoid an import cycle — see
``apply_staged_changes`` there.

**Lifetime.** Staging sets are in-process, single-use, and expire after
30 minutes if neither applied nor discarded. They never touch disk;
restarting the server invalidates pending stagings (which is fine —
the user can re-issue the request).

**Why a fresh module instead of extending the existing write tools?**

The existing write surface (``create_event`` etc.) is mature and used
by Claude Code today. Refactoring all of it to take an optional
``staging_id`` parameter would be invasive and risk regressions. The
staging layer is additive: the LLM picks whichever pattern fits the
turn — direct write for single explicit user instructions; staging for
batched or interpretive changes.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Operation schema
# ---------------------------------------------------------------------------

class CreateEventOp(BaseModel):
    """One-off event creation — e.g. a fire-drill bell next Tuesday."""
    kind: Literal["create_event"] = "create_event"
    template_id: int
    destination_id: int
    label: str = Field(..., description="Human-readable name for the diff (e.g. 'Fire drill bell').")
    start_time: str = Field(..., description="ISO datetime when the event fires.")
    detail: str = Field("", description="Short prose explanation rendered under the row.")
    destination_name: str = Field("", description="Pretty destination label for the diff chip.")


class DeleteEventOp(BaseModel):
    """Cancel an entire recurring scheduler or a one-off event."""
    kind: Literal["delete_event"] = "delete_event"
    scheduler_id: int
    label: str
    detail: str = ""


class ScheduleTemplateOp(BaseModel):
    """Bind an existing template to a destination on a recurrence pattern."""
    kind: Literal["schedule_template"] = "schedule_template"
    template_id: int
    destination_id: int
    days_of_week: list[str] = Field(..., description="['Mon','Tue',...] — uses short English day labels.")
    start_date: str
    end_date: str
    label: str
    detail: str = ""
    destination_name: str = ""


class CancelOccurrenceOp(BaseModel):
    """Skip a template's bells on a single date (snow day, holiday, etc.)."""
    kind: Literal["cancel_one_occurrence"] = "cancel_one_occurrence"
    template_id: int
    destination_id: int
    exception_date: str = Field(..., description="ISO date — YYYY-MM-DD.")
    label: str
    detail: str = ""


#: Discriminated union of every operation we know how to stage.
#: Extending: add a new BaseModel subclass with a unique ``kind`` literal,
#: add it to this union, and add a dispatch arm in ``mcp_server.apply_staged_changes``.
Operation = Annotated[
    Union[
        CreateEventOp,
        DeleteEventOp,
        ScheduleTemplateOp,
        CancelOccurrenceOp,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Staged changeset + registry
# ---------------------------------------------------------------------------

DEFAULT_STAGING_TTL_SECONDS = 30 * 60   # 30 minutes


@dataclass
class StagedChangeset:
    """One pending diff. Created by :func:`stage`; consumed by :func:`apply`/:func:`discard`."""
    staging_id: str
    title: str
    effective: str
    operations: list[Operation]
    expires_at: float                       # monotonic seconds
    summary: str = ""                       # one-line description, used by ApplyConfirmCard

    def to_diff_card(self) -> dict[str, Any]:
        """Render to the JSON shape ScheduleDiffCard expects on the frontend."""
        return {
            "staging_id": self.staging_id,
            "title": self.title,
            "effective": self.effective,
            "changes": [_op_to_change(op) for op in self.operations],
        }


_LOCK = threading.Lock()
_REGISTRY: dict[str, StagedChangeset] = {}


def stage(
    title: str,
    effective: str,
    operations: list[Operation],
    *,
    summary: str = "",
    ttl_seconds: int = DEFAULT_STAGING_TTL_SECONDS,
) -> StagedChangeset:
    """Register a new staging set. Returns the StagedChangeset for diff display."""
    if not operations:
        raise ValueError("staging requires at least one operation")
    sid = "stg_" + secrets.token_urlsafe(8)
    cs = StagedChangeset(
        staging_id=sid,
        title=title,
        effective=effective,
        operations=list(operations),
        expires_at=time.monotonic() + ttl_seconds,
        summary=summary or title,
    )
    with _LOCK:
        _gc_expired_locked()
        _REGISTRY[sid] = cs
    return cs


def get(staging_id: str) -> Optional[StagedChangeset]:
    """Look up a staging set without consuming it."""
    with _LOCK:
        cs = _REGISTRY.get(staging_id)
        _gc_expired_locked()
    if cs is None or time.monotonic() > cs.expires_at:
        return None
    return cs


def pop(staging_id: str) -> Optional[StagedChangeset]:
    """Consume a staging set (used by both apply and discard)."""
    with _LOCK:
        cs = _REGISTRY.pop(staging_id, None)
        _gc_expired_locked()
    if cs is None or time.monotonic() > cs.expires_at:
        return None
    return cs


def list_pending() -> list[StagedChangeset]:
    """Snapshot of every active staging set. Useful for the audit / debug UI."""
    with _LOCK:
        _gc_expired_locked()
        return list(_REGISTRY.values())


def _gc_expired_locked() -> None:
    """Evict expired entries. Caller must hold ``_LOCK``."""
    now = time.monotonic()
    expired = [sid for sid, cs in _REGISTRY.items() if now > cs.expires_at]
    for sid in expired:
        _REGISTRY.pop(sid, None)


# ---------------------------------------------------------------------------
# Diff-card rendering helpers
# ---------------------------------------------------------------------------

def _op_to_change(op: Operation) -> dict[str, Any]:
    """Map an ``Operation`` to the ``ScheduleChange`` shape the frontend renders."""
    if isinstance(op, CreateEventOp):
        return {
            "kind": "add",
            "label": op.label,
            "detail": op.detail or "New event",
            "time": _time_from_iso(op.start_time),
            "destination": op.destination_name or None,
        }
    if isinstance(op, DeleteEventOp):
        return {
            "kind": "delete",
            "label": op.label,
            "detail": op.detail or "Remove this scheduler",
        }
    if isinstance(op, ScheduleTemplateOp):
        return {
            "kind": "add",
            "label": op.label,
            "detail": op.detail or (
                f"{', '.join(op.days_of_week)} from {op.start_date} to {op.end_date}"
            ),
            "destination": op.destination_name or None,
        }
    if isinstance(op, CancelOccurrenceOp):
        return {
            "kind": "delete",
            "label": op.label,
            "detail": op.detail or f"Skip occurrence on {op.exception_date}",
        }
    # Defensive — shouldn't reach here given the discriminated union
    return {"kind": "add", "label": "unknown", "detail": repr(op)}


def _time_from_iso(ts: str) -> Optional[str]:
    """Return the HH:MM portion of an ISO datetime, or None."""
    if "T" in ts:
        try:
            t = ts.split("T", 1)[1]
            return t[:5]  # HH:MM
        except IndexError:
            return None
    return None
