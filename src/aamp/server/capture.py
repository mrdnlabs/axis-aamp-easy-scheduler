"""Credential-capture sidecar.

The web client's :file:`SecureCaptureModal` POSTs the typed password
directly to this module's HTTP endpoints — bypassing the LLM entirely.
The value goes straight to the OS credential vault via the existing
:func:`aamp.credentials.get_credential_store` interface.

**Token model.** Capture is gated by short-lived single-use tokens:

1. The LLM calls the MCP tool ``request_credential_capture(account_id, field)``.
2. That tool calls :func:`start_capture` which generates a token via
   ``secrets.token_urlsafe`` and registers it in the in-process registry.
3. The web client receives the token + URL and renders the modal.
4. The user submits a value to ``POST /capture/{token}``.
5. :func:`submit_capture` validates the token, pops it from the registry
   (single-use), writes the value to keyring, and returns success.

Tokens expire after 600 seconds and are evicted from the registry on
the next access. The registry lives in-process; restarting the server
invalidates every pending capture.

**Trust boundary.** ``/capture/{token}`` is the ONLY place in the system
that accepts a cleartext password from a network request. It is bound
to 127.0.0.1 (via the uvicorn invocation in :mod:`aamp.server.app`) so
remote attackers cannot reach it. Auditing every call is mandatory.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..audit import AuditLog
from ..credentials import get_credential_store, secret_for


# ---------------------------------------------------------------------------
# Token registry — in-process, thread-safe
# ---------------------------------------------------------------------------

DEFAULT_TTL_SECONDS = 600   # 10 minutes
MIN_VALUE_LENGTH = 4         # short floor; actual policy is up to the user


@dataclass
class CaptureToken:
    token: str
    account_id: str
    field: str
    expires_at: float          # monotonic time
    description: str           # cached for the modal's "what am I setting?" line


_LOCK = threading.Lock()
_TOKENS: dict[str, CaptureToken] = {}
_AUDIT = AuditLog()   # uses the same default ~/.aamp_audit.log

# Per-source rate-limit state. Stores deque of recent mint timestamps
# per source identifier (typically client IP). Sliding 60-second window;
# limit comes from ``settings.capture_rate_limit_per_minute``.
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_rate_buckets: dict[str, deque[float]] = {}
_rate_lock = threading.Lock()


def _rate_limit_check(source: str, limit_per_minute: int) -> Optional[int]:
    """Sliding-window rate limiter.

    Records the mint attempt against ``source`` and returns ``None`` if
    we're under the limit, or the number of seconds the caller must wait
    before the next attempt would succeed (suitable for an HTTP
    Retry-After header) if over.

    Stateless aside from the in-process buckets. Restarting the server
    clears the buckets — which is fine; a confused client will mostly
    have given up by then.
    """
    if limit_per_minute <= 0:
        return None  # disabled
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    with _rate_lock:
        bucket = _rate_buckets.setdefault(source, deque())
        # Drop timestamps that are older than the window.
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit_per_minute:
            # Caller must wait until the oldest timestamp falls out of
            # the window for a slot to free up.
            retry_after = int(bucket[0] + _RATE_LIMIT_WINDOW_SECONDS - now) + 1
            return max(1, retry_after)
        bucket.append(now)
        return None


# ---------------------------------------------------------------------------
# Public API (called by MCP tool + the FastAPI route)
# ---------------------------------------------------------------------------

def start_capture(
    account_id: str,
    field: str,
    *,
    ttl_seconds: Optional[int] = None,
) -> CaptureToken:
    """Mint a short-lived token for capturing ``(account_id, field)``.

    Validates the slot against ``KNOWN_SECRETS`` so the LLM can't open a
    capture for a typo. Audits the request. TTL defaults to the
    ``capture_token_ttl_seconds`` setting (10 min out of the box).
    """
    if ttl_seconds is None:
        from .. import settings as _settings
        ttl_seconds = int(_settings.get_setting("capture_token_ttl_seconds") or DEFAULT_TTL_SECONDS)
    s = secret_for(account_id, field)
    if s is None:
        _AUDIT.record(
            "capture_start", account_id, field,
            decision="denied", reason="unknown credential slot",
        )
        raise ValueError(
            f"{account_id}/{field} is not a known credential slot — refusing to mint a capture token."
        )

    token = secrets.token_urlsafe(18)   # 24 chars, ~144 bits entropy
    record = CaptureToken(
        token=token,
        account_id=account_id,
        field=field,
        expires_at=time.monotonic() + ttl_seconds,
        description=s.description,
    )
    with _LOCK:
        _TOKENS[token] = record
        _gc_expired_locked()

    _AUDIT.record(
        "capture_start", account_id, field,
        reason=f"ttl={ttl_seconds}s",
    )
    return record


def submit_capture(token: str, value: str) -> CaptureToken:
    """Pop the token, write the value to keyring, return the captured slot.

    Single-use: the token is removed regardless of write success/failure
    so a replay can't try again. Raises ``LookupError`` for unknown/expired
    tokens, ``ValueError`` for invalid values.
    """
    with _LOCK:
        record = _TOKENS.pop(token, None)
        _gc_expired_locked()

    if record is None:
        _AUDIT.record(
            "capture_submit", "?", "?",
            decision="denied", reason="unknown or expired token",
        )
        raise LookupError("unknown or expired capture token")

    if time.monotonic() > record.expires_at:
        _AUDIT.record(
            "capture_submit", record.account_id, record.field,
            decision="denied", reason="token expired between mint and submit",
        )
        raise LookupError("capture token expired")

    if not value or len(value) < MIN_VALUE_LENGTH:
        _AUDIT.record(
            "capture_submit", record.account_id, record.field,
            decision="denied", reason=f"value too short (< {MIN_VALUE_LENGTH} chars)",
        )
        raise ValueError(f"credential value must be at least {MIN_VALUE_LENGTH} characters")

    # Write to the configured credential store (keyring + chained fallback).
    store = get_credential_store()
    store.set(record.account_id, record.field, value)
    _AUDIT.record("capture_submit", record.account_id, record.field)
    return record


def status_for(token: str) -> Optional[CaptureToken]:
    """Look up a token without consuming it. Used by the modal to display
    countdown info. Never returns the value (we never store the value here)."""
    with _LOCK:
        record = _TOKENS.get(token)
        _gc_expired_locked()
    if record is None:
        return None
    if time.monotonic() > record.expires_at:
        return None
    return record


def _gc_expired_locked() -> None:
    """Evict expired tokens from the registry. Caller must hold ``_LOCK``."""
    now = time.monotonic()
    expired = [t for t, r in _TOKENS.items() if now > r.expires_at]
    for t in expired:
        _TOKENS.pop(t, None)


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/credential-capture", tags=["capture"])


class StartRequest(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    field: str = Field(..., min_length=1, max_length=64)


class StartResponse(BaseModel):
    token: str
    account_id: str
    field: str
    description: str
    expires_in_seconds: int


class StatusResponse(BaseModel):
    account_id: str
    field: str
    description: str
    expires_in_seconds: int


class SubmitRequest(BaseModel):
    value: str = Field(..., min_length=MIN_VALUE_LENGTH)


class SubmitResponse(BaseModel):
    captured: bool
    account_id: str
    field: str


@router.post("/start", response_model=StartResponse)
def http_start(req: StartRequest, request: Request) -> StartResponse:
    """Mint a capture token. Normally called by the MCP tool; exposed here
    for testing and for clients that want to invoke capture directly.

    Rate-limited per client IP using the sliding-window in
    :func:`_rate_limit_check`. Limit comes from the
    ``capture_rate_limit_per_minute`` setting.
    """
    from .. import settings as _settings
    limit = _settings.get_setting("capture_rate_limit_per_minute") or 20
    source = request.client.host if request.client else "unknown"
    retry_after = _rate_limit_check(source, int(limit))
    if retry_after is not None:
        _AUDIT.record(
            "capture_start", req.account_id, req.field,
            decision="denied",
            reason=f"rate limit ({limit}/min) exceeded from {source}",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many capture requests from this source. Try again "
                f"in {retry_after}s. (Limit: {limit}/min, configurable via "
                f"the capture_rate_limit_per_minute setting.)"
            ),
            headers={"Retry-After": str(retry_after)},
        )
    try:
        rec = start_capture(req.account_id, req.field)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return StartResponse(
        token=rec.token,
        account_id=rec.account_id,
        field=rec.field,
        description=rec.description,
        expires_in_seconds=int(rec.expires_at - time.monotonic()),
    )


@router.get("/{token}/status", response_model=StatusResponse)
def http_status(token: str) -> StatusResponse:
    """Modal calls this on open to render the countdown and confirm the slot."""
    rec = status_for(token)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown or expired token")
    return StatusResponse(
        account_id=rec.account_id,
        field=rec.field,
        description=rec.description,
        expires_in_seconds=int(rec.expires_at - time.monotonic()),
    )


@router.post("/{token}", response_model=SubmitResponse)
def http_submit(token: str, req: SubmitRequest) -> SubmitResponse:
    """Receive the user's password. Single-use. Writes to keyring on success.

    THIS IS THE ONLY ENDPOINT IN THE SYSTEM THAT ACCEPTS A CLEARTEXT
    PASSWORD FROM A NETWORK REQUEST. It must remain 127.0.0.1-only.
    """
    try:
        rec = submit_capture(token, req.value)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # pragma: no cover — keyring backend failures
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"keyring write failed: {type(e).__name__}: {e}",
        )
    return SubmitResponse(captured=True, account_id=rec.account_id, field=rec.field)
