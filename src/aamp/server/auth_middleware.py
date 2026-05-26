"""FastAPI middleware: gate every request on Windows peer identity.

The flow on each request:

1. Skip auth for a small allowlist of always-public routes (healthz,
   config status, the ``/api/auth/me`` probe itself).
2. Skip for FastAPI ``TestClient`` requests (no real socket). This is
   the ONE bypass — see the test-mode discussion below.
3. Otherwise read ``request.client.host:port``, the connecting peer's
   address. Read the local port the request arrived on from the
   uvicorn server-side scope.
4. Delegate to :func:`aamp.server.peer_identity.identify_socket_owner`
   to walk the Windows TCP table and resolve the user.
5. If the user isn't in the configured admin group SID, return a
   well-formatted 403 JSON the frontend can branch on.
6. If they are, stash :class:`SocketIdentity` on
   ``request.state.current_user`` AND set the
   ``aamp.audit.principal_context`` ContextVar so audit-log entries
   pick up the real username.

**Test-mode bypass.** FastAPI's ``TestClient`` short-circuits without
real sockets — ``request.client.host`` is ``"testclient"`` and there's
no TCP table entry. The middleware substitutes a synthetic admin
identity in that case so the existing 11+ in-process tests still
work without needing to inject mock TCP-table data. Real loopback
clients always come in as ``127.0.0.1`` or ``::1``.

**Allowlist.** Public routes are explicitly named below — any new
route is gated by default. Note that ``/api/auth/me`` is public on
purpose: the frontend uses it to *discover* whether the user is an
admin (so it knows to render the access-denied screen vs the chat).
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .. import audit
from .. import settings as _settings
from . import peer_identity


log = logging.getLogger(__name__)


# Public routes that bypass the admin check. Keep this list small.
ALLOWLIST_EXACT: frozenset[str] = frozenset({
    "/healthz",
    "/api/healthz",
    "/api/config/status",
    "/api/auth/me",
})


# Synthetic identity used in TestClient mode. Tests always run as the
# user invoking pytest, so granting admin here is consistent with the
# real loopback-only model.
_TESTCLIENT_IDENTITY = peer_identity.SocketIdentity(
    pid=-1,
    username="TESTCLIENT\\admin",
    sid="S-1-5-32-544",   # masquerade as BUILTIN\\Administrators
    is_admin=True,
)


def _is_testclient(request: Request) -> bool:
    """FastAPI's TestClient sets ``client.host = "testclient"``."""
    client = request.client
    return client is not None and client.host == "testclient"


def _local_port_from_scope(request: Request) -> int | None:
    """uvicorn populates ``scope["server"] = (host, port)``."""
    server = request.scope.get("server")
    if not server:
        return None
    try:
        return int(server[1])
    except (TypeError, IndexError, ValueError):
        return None


def _admin_group_sid() -> str:
    """Pulled fresh on every request so a Settings-panel edit takes
    immediate effect. Costs one ``~/.aamp_settings.json`` read; the
    file is tiny and the OS caches it."""
    return str(_settings.get_setting("auth_required_group_sid") or "S-1-5-32-544")


class PeerIdentityMiddleware(BaseHTTPMiddleware):
    """Sits between Starlette's HTTP layer and the FastAPI routes.

    See module docstring for behavior. Only ``dispatch`` matters here
    — everything else is shared across all middleware in this app.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # 1. Allowlisted routes pass through unidentified.
        if path in ALLOWLIST_EXACT:
            return await call_next(request)

        # 2. TestClient mode — short-circuit identification.
        if _is_testclient(request):
            request.state.current_user = _TESTCLIENT_IDENTITY
            token = audit.principal_context.set(_TESTCLIENT_IDENTITY.username)
            try:
                return await call_next(request)
            finally:
                audit.principal_context.reset(token)

        # 3. Real request. Identify the peer.
        client = request.client
        if client is None:
            return _deny(403, "no_client", "Request has no client info; cannot identify peer.")
        local_port = _local_port_from_scope(request)
        if local_port is None:
            return _deny(500, "no_local_port", "Server scope missing local port.")

        result = peer_identity.identify_socket_owner(
            local_port=local_port,
            remote_addr=client.host,
            remote_port=client.port,
            admin_group_sid=_admin_group_sid(),
        )
        if isinstance(result, peer_identity.IdentifyError):
            log.warning(
                "peer-identity failed for %s:%s -> local %s: %s",
                client.host, client.port, local_port, result.reason,
            )
            return _deny(403, "identify_failed", result.reason)

        if not result.is_admin:
            log.info(
                "peer-identity allowed-list rejection: user=%s sid=%s",
                result.username, result.sid,
            )
            return _deny(
                403, "not_admin",
                f"User {result.username!r} is not a member of the required "
                f"group ({_admin_group_sid()}). Sign in as an administrator "
                f"to use ChAAMP.",
                extra={"username": result.username, "sid": result.sid},
            )

        # 4. Allowed — wire the principal in and run the route.
        request.state.current_user = result
        token = audit.principal_context.set(result.username)
        try:
            return await call_next(request)
        finally:
            audit.principal_context.reset(token)


def _deny(status: int, code: str, detail: str, *, extra: dict | None = None) -> JSONResponse:
    """A consistent JSON envelope so the frontend can branch reliably.

    The web client checks ``status === 403`` then reads ``code`` to
    decide which copy to show ("not admin" vs "identify failed").
    """
    body = {"detail": detail, "code": code}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body)
