"""Credentials read-only HTTP surface.

Lists which credential slots are known to the system and whether
each one currently has a value stored. Values themselves NEVER cross
this endpoint — that's the entire point of the secure-capture flow.

Endpoints:

  ``GET /api/credentials``        — list every known slot + ``stored`` bool.

Rotation = re-capture (the SecureCaptureModal already overwrites).
Deletion is intentionally absent over HTTP. If the user really wants
to wipe a credential, they open Windows Credential Manager / macOS
Keychain / Linux libsecret and delete the ``aamp/...`` entry there.

Why not even a "set" endpoint here? Because the secure-capture flow
(``/api/credential-capture/*``) already handles that, and going
through the modal forces the value out of the JS heap quickly.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import credentials as _credentials


router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialSlotView(BaseModel):
    """One row in the Credentials panel."""

    account_id: str
    field: str
    description: str
    env_var: str
    is_csv_list: bool
    stored: bool


@router.get("", response_model=list[CredentialSlotView])
def http_list() -> list[CredentialSlotView]:
    """Every known credential slot + whether a value is currently stored
    anywhere the chained credential store can find it (keyring or
    ``.aamp_credentials`` or matching env var)."""
    store = _credentials.get_credential_store()
    out: list[CredentialSlotView] = []
    for s in _credentials.KNOWN_SECRETS:
        try:
            value = store.get(s.account_id, s.field)
        except Exception:  # pragma: no cover — defensive
            value = None
        out.append(CredentialSlotView(
            account_id=s.account_id,
            field=s.field,
            description=s.description,
            env_var=s.env_var,
            is_csv_list=s.is_csv_list,
            stored=bool(value),
        ))
    return out
