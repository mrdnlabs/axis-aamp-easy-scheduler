"""Append-only audit log for credential access.

Every ``CredentialStore.get`` / ``set`` / ``delete`` / ``list_accounts``
call gets a JSONL record. The log lives at ``~/.aamp_audit.log`` — per-user,
outside the project tree (so it can't accidentally be committed). No
credential VALUES are ever logged — only the fact of access.

Schema per line::

    {
      "ts": "2026-05-22T03:55:12.345",
      "op": "get" | "set" | "delete" | "list" | "denied",
      "account_id": "<account_id>",
      "field": "<field>",        # empty for list
      "principal": "process",     # extensible: "llm" / "human:<username>" later
      "decision": "ok" | "denied",
      "reason": ""
    }

Failures inside :class:`AuditLog.record` are SWALLOWED — credential
access must never fail because the audit log can't be written. Mirrors
the ``chat_log.py`` resilience pattern.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .credentials import CredentialStore


DEFAULT_AUDIT_PATH = Path.home() / ".aamp_audit.log"


# Request-scoped principal. The web sidecar's PeerIdentityMiddleware
# sets this to the connecting Windows user at the top of each request;
# AuditingStore.get/set/delete and other call sites pick it up through
# ``record(principal=None)`` — see the ``record()`` resolution below.
#
# CLI / MCP-server callers never set the contextvar, so they get the
# default ``"process"`` — same behavior as before.
principal_context: ContextVar[str] = ContextVar("aamp_audit_principal", default="process")


@dataclass
class AuditLog:
    """Append-only JSONL credential audit log."""
    path: Path = DEFAULT_AUDIT_PATH

    def record(
        self,
        op: str,
        account_id: str,
        field: str = "",
        *,
        principal: Optional[str] = None,
        decision: str = "ok",
        reason: str = "",
    ) -> None:
        # Resolution order for principal:
        #   1. Explicit kwarg passed by the caller (e.g., the capture
        #      endpoint may want to attribute differently).
        #   2. ``principal_context`` ContextVar — set by the web sidecar's
        #      auth middleware to the connecting Windows user.
        #   3. ``"process"`` default — CLI / MCP-server invocations.
        if principal is None:
            principal = principal_context.get()
        entry = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "op": op,
            "account_id": account_id,
            "field": field,
            "principal": principal,
            "decision": decision,
            "reason": reason,
        }
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            # Logging must never crash callers.
            pass


# ---------------------------------------------------------------------------
# AuditingStore decorator
# ---------------------------------------------------------------------------

class AuditingStore(CredentialStore):
    """Wraps any :class:`CredentialStore`, audit-logging every access.

    All credential reads/writes pass through here so we can later prove
    (via the audit log) that no rogue access happened. When the web UI
    lands and we introduce a second principal (``"human:<user>"``), only
    the principal argument needs updating — the rest of the surface is
    identical.
    """

    def __init__(self, inner: CredentialStore, audit: Optional[AuditLog] = None) -> None:
        self._inner = inner
        self._audit = audit or AuditLog()

    @property
    def is_writable(self) -> bool:
        return self._inner.is_writable

    @property
    def name(self) -> str:
        return f"Auditing({self._inner.name})"

    def get(self, account_id: str, field: str) -> Optional[str]:
        val = self._inner.get(account_id, field)
        self._audit.record(
            "get", account_id, field,
            decision=("ok" if val is not None else "miss"),
        )
        return val

    def set(self, account_id: str, field: str, value: str) -> None:
        try:
            self._inner.set(account_id, field, value)
            self._audit.record("set", account_id, field)
        except Exception as e:
            self._audit.record("set", account_id, field,
                                decision="denied", reason=f"{type(e).__name__}: {e}")
            raise

    def delete(self, account_id: str, field: str) -> None:
        try:
            self._inner.delete(account_id, field)
            self._audit.record("delete", account_id, field)
        except Exception as e:
            self._audit.record("delete", account_id, field,
                                decision="denied", reason=f"{type(e).__name__}: {e}")
            raise

    def list_accounts(self) -> list[tuple[str, list[str]]]:
        out = self._inner.list_accounts()
        self._audit.record("list", "*", "*", reason=f"{len(out)} accounts")
        return out
