"""Configuration status endpoint.

The web client uses this on load to decide whether the chat composer
should be live or gated by a "Set up Gemini" setup card. We expose only
booleans — never values — so this endpoint is safe to call from the
browser without leaking which keyring backend or env var supplied the
credential.

Reads happen through the credential store so we benefit from the same
chained fallback (keyring → ``.aamp_credentials`` → env) that the chat
backend uses at request time. Additionally we honor ``GEMINI_API_KEY``
/ ``GOOGLE_API_KEY`` as a sufficient signal for Gemini (the chat backend
also accepts these).
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from ..credentials import get_credential_store


router = APIRouter(prefix="/config", tags=["config"])


class ConfigStatus(BaseModel):
    """Boolean rollup of credential / capability state.

    All fields are booleans — no values, no last-set timestamps, no
    backend identifiers. The web client uses these to gate UI; richer
    detail (audit history, last-set time) lives behind the CLI tools.
    """

    #: True when the chat backend has a Gemini API key available (keyring
    #: OR ``GEMINI_API_KEY`` OR ``GOOGLE_API_KEY``). Chat is gated on this.
    gemini_configured: bool
    #: True when the ElevenLabs voice generation key is set.
    elevenlabs_configured: bool
    #: True when the AAM Pro admin password is set (needed for write ops).
    aamp_configured: bool
    #: True when the Axis device fleet password is set (needed for onboarding).
    device_default_password_configured: bool


def _has(account_id: str, field: str) -> bool:
    """True iff the credential store can resolve a non-empty value."""
    try:
        return bool(get_credential_store().get(account_id, field))
    except Exception:  # pragma: no cover - defensive
        return False


@router.get("/status", response_model=ConfigStatus)
def http_status() -> ConfigStatus:
    """Return the credential rollup."""
    gemini = _has("gemini", "api_key") or bool(
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    return ConfigStatus(
        gemini_configured=gemini,
        elevenlabs_configured=_has("elevenlabs", "api_key"),
        aamp_configured=_has("aamp", "password"),
        device_default_password_configured=_has("device", "default_password"),
    )
