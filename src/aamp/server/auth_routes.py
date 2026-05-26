"""``/api/auth/me`` — the identity probe.

The frontend hits this on app mount to decide whether to render the
chat workspace or the access-denied screen. It's on the middleware
allowlist (see :mod:`aamp.server.auth_middleware`) — even non-admins
get a 200 response so they can SEE who they're signed in as and what
they need to do.

If peer identification fails entirely (the rare TCP-table-race case),
``username`` is ``null`` and the frontend treats that the same as
not-admin: show the access-denied screen with a generic message.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import settings as _settings
from . import peer_identity


router = APIRouter(prefix="/auth", tags=["auth"])


class MeResponse(BaseModel):
    """Always 200 — the ``username`` field carries authentication state."""

    #: ``DOMAIN\\username`` form. ``None`` when peer identification
    #: failed (TCP-table race, process exited mid-request, …).
    username: Optional[str] = None
    #: String form of the SID. ``None`` when ``username`` is ``None``.
    sid: Optional[str] = None
    #: True iff member of the configured admin group at fetch time.
    is_admin: bool = False
    #: Always ``"windows_peer"`` for now; future flows would add new
    #: source labels (e.g., ``"oauth_aam_pro"``).
    source: str = "windows_peer"
    #: The SID we're checking against — surfaced so the access-denied
    #: screen can show "you need to be in <group>" with real info.
    required_group_sid: str = "S-1-5-32-544"


@router.get("/me", response_model=MeResponse)
def http_me(request: Request) -> MeResponse:
    """Identify the caller without going through the gating
    middleware. We deliberately re-do the lookup here rather than
    reading from ``request.state.current_user``, because this route
    is on the middleware allowlist — non-admins also hit it.

    For TestClient invocations we'd see no real client, so we return
    a synthetic admin identity for parity with the middleware
    test-mode bypass.
    """
    client = request.client
    required_sid = str(_settings.get_setting("auth_required_group_sid") or "S-1-5-32-544")

    # TestClient parity.
    if client is not None and client.host == "testclient":
        return MeResponse(
            username="TESTCLIENT\\admin",
            sid="S-1-5-32-544",
            is_admin=True,
            required_group_sid=required_sid,
        )

    if client is None:
        return MeResponse(required_group_sid=required_sid)

    server = request.scope.get("server")
    if not server:
        return MeResponse(required_group_sid=required_sid)

    result = peer_identity.identify_socket_owner(
        local_port=int(server[1]),
        remote_addr=client.host,
        remote_port=client.port,
        admin_group_sid=required_sid,
    )
    if isinstance(result, peer_identity.IdentifyError):
        return MeResponse(required_group_sid=required_sid)

    return MeResponse(
        username=result.username,
        sid=result.sid,
        is_admin=result.is_admin,
        required_group_sid=required_sid,
    )
