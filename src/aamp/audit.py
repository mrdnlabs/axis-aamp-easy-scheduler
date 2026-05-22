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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .credentials import CredentialStore


DEFAULT_AUDIT_PATH = Path.home() / ".aamp_audit.log"


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
        principal: str = "process",
        decision: str = "ok",
        reason: str = "",
    ) -> None:
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
