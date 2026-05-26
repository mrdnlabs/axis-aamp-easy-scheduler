"""Audit-log read-only HTTP surface.

Tails the JSONL audit file written by :mod:`aamp.audit` and exposes
recent entries to the web UI. No write surface — that would let a
client manufacture audit history.

Endpoints:

  ``GET /api/audit?limit=&op=&principal=`` — recent entries.

Reading happens on-demand: each call opens the file, reads from the
tail, and yields filtered rows. For the small audit files we expect
(KB-MB range), this is more than fast enough. If the file ever grows
into the GB range we can swap in a circular-buffer or DuckDB query.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .. import audit as _audit


router = APIRouter(prefix="/audit", tags=["audit"])


# Cap a single request's reply so a wide-open client can't ask for an
# unbounded read. 1000 is roughly a week of activity on a busy local
# setup.
MAX_LIMIT = 1000


class AuditEntry(BaseModel):
    """One row of the audit log. The shape mirrors what
    :meth:`aamp.audit.AuditLog.record` writes — see that method for
    the canonical field list."""

    ts: Optional[str] = None
    op: Optional[str] = None
    account_id: Optional[str] = None
    field: Optional[str] = None
    principal: Optional[str] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    # The audit writer may add fields over time; keep extras around
    # so the UI can pivot on them without a server change.
    extra: dict[str, Any] = {}


def _row_matches(row: dict[str, Any], *, op: Optional[str], principal: Optional[str]) -> bool:
    """Apply the optional filters. Both filters are exact-match — the
    UI sends a value chosen from a dropdown, not a free-text query."""
    if op and row.get("op") != op:
        return False
    if principal and row.get("principal") != principal:
        return False
    return True


@router.get("", response_model=list[AuditEntry])
def http_list(
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    op: Optional[str] = None,
    principal: Optional[str] = None,
) -> list[AuditEntry]:
    """Return up to ``limit`` most-recent matching entries, newest
    first. Missing audit file → empty list (the file is created on
    the first :meth:`AuditLog.record` call)."""
    path: Path = _audit.AuditLog().path
    if not path.exists():
        return []

    # The file is JSONL. Read all lines; for the sizes we expect this
    # is cheaper than seeking from the end. If perf bites later we can
    # switch to a true tail-read.
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # Skip malformed lines silently; the audit writer is
                # supposed to produce valid JSON every time.
                continue
            if not isinstance(row, dict):
                continue
            if _row_matches(row, op=op, principal=principal):
                rows.append(row)

    # Newest first, then cap.
    rows.reverse()
    rows = rows[:limit]

    out: list[AuditEntry] = []
    known = {"ts", "op", "account_id", "field", "principal", "decision", "reason"}
    for row in rows:
        extras = {k: v for k, v in row.items() if k not in known}
        out.append(AuditEntry(
            ts=row.get("ts"),
            op=row.get("op"),
            account_id=row.get("account_id"),
            field=row.get("field"),
            principal=row.get("principal"),
            decision=row.get("decision"),
            reason=row.get("reason"),
            extra=extras,
        ))
    return out
