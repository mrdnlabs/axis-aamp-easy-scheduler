"""Identify the connecting Windows user from a TCP socket.

Given the 4-tuple of an active TCP connection on this machine, this
module walks the Windows TCP table (``GetExtendedTcpTable``), finds
the entry that matches, opens the owning process, reads its access
token, and resolves the SID to ``DOMAIN\\username``. It also tests
membership in a target group SID (typically BUILTIN\\Administrators).

The output is consumed by the FastAPI middleware in
:mod:`aamp.server.auth_middleware` to gate every request.

**Why this approach.** ChAAMP is a single-machine local tool that
binds loopback-only. Multiple Windows users on the same machine (RDP,
fast-user-switching, separate console + RDP sessions) can all reach
loopback, so a bare network bind isn't enough — we need to identify
the user who actually opened the TCP connection. Windows' TCP
extended table tells us which PID, and the token gives us the user.

**Why not pywin32 alone.** pywin32 wraps :func:`OpenProcess`,
:func:`OpenProcessToken`, :func:`GetTokenInformation`,
:func:`LookupAccountSid`, :func:`CheckTokenMembership`, and the SID
helpers — but it doesn't expose ``GetExtendedTcpTable``. We bind that
one via :mod:`ctypes`; everything else flows through pywin32 for
readability.

**Caching.** Identifying a socket is cheap but not free (system call
+ allocation per table walk). For SSE-style long-lived connections,
we cache the result keyed on (client_addr, client_port) with a
60-second TTL — a connection's 4-tuple is stable for its lifetime,
so the cache is correct as long as the entry hasn't aged out.
"""

from __future__ import annotations

import ctypes
import socket
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional


# Hard refuse on import if this is loaded on a non-Windows platform.
# The sidecar's app.py separately refuses to start, but importing
# this module on Linux/macOS would explode in confusing ways without
# this early check.
if sys.platform != "win32":
    raise RuntimeError(
        "aamp.server.peer_identity is Windows-only. The ChAAMP sidecar "
        "uses Windows peer-identity authentication and cannot run on "
        f"{sys.platform!r}."
    )

import win32api  # noqa: E402  pylint: disable=import-error
import win32con  # noqa: E402  pylint: disable=import-error
import win32process  # noqa: E402  pylint: disable=import-error
import win32security  # noqa: E402  pylint: disable=import-error
import pywintypes  # noqa: E402  pylint: disable=import-error


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SocketIdentity:
    """The connecting user resolved for a single TCP 4-tuple."""

    #: PID of the connecting process (the browser, curl, etc.).
    pid: int
    #: Resolved as ``DOMAIN\\username`` (or ``MACHINE\\username`` for
    #: local accounts). Empty if SID couldn't be resolved.
    username: str
    #: String form of the user's SID.
    sid: str
    #: True iff this user is a member of the target group at check time.
    is_admin: bool


@dataclass(frozen=True)
class IdentifyError:
    """Returned when peer identification failed. Distinct from "user
    is not admin" — the middleware treats this as a hard 403."""

    reason: str


# ---------------------------------------------------------------------------
# GetExtendedTcpTable via ctypes
# ---------------------------------------------------------------------------

# Constants from <iphlpapi.h> / <iptypes.h>
TCP_TABLE_OWNER_PID_ALL = 5

# AF_INET / AF_INET6 — same values across platforms but import for clarity.
_AF_INET = socket.AF_INET
_AF_INET6 = socket.AF_INET6


# Per the Windows headers, the v4 row is six DWORDs:
#   state, localAddr, localPort, remoteAddr, remotePort, owningPid.
# Ports are big-endian on the wire — high byte first inside the DWORD.
class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


# v6 row uses 16-byte addresses + scope ids. We don't need scope.
class _MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("ucLocalAddr", ctypes.c_ubyte * 16),
        ("dwLocalScopeId", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("ucRemoteAddr", ctypes.c_ubyte * 16),
        ("dwRemoteScopeId", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwState", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


_iphlpapi = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
_GetExtendedTcpTable = _iphlpapi.GetExtendedTcpTable
_GetExtendedTcpTable.argtypes = [
    ctypes.c_void_p,    # pTcpTable
    ctypes.POINTER(wintypes.DWORD),  # pdwSize
    wintypes.BOOL,      # bOrder
    wintypes.ULONG,     # ulAf  (AF_INET / AF_INET6)
    wintypes.DWORD,     # TableClass
    wintypes.DWORD,     # Reserved
]
_GetExtendedTcpTable.restype = wintypes.DWORD

# ERROR_INSUFFICIENT_BUFFER — pTcpTable too small; reallocate to the
# size the kernel just wrote into ``*pdwSize`` and retry.
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_SUCCESS = 0


def _decode_port(dw_port: int) -> int:
    """The TCP table reports ports big-endian inside a DWORD. Pull
    the two low bytes and byteswap into a normal integer."""
    return ((dw_port & 0xFF) << 8) | ((dw_port >> 8) & 0xFF)


def _decode_v4_addr(dw_addr: int) -> str:
    """Format a DWORD-encoded IPv4 (little-endian on Windows) as
    dotted-quad. ``dwLocalAddr`` has the first octet in the low byte."""
    return "{}.{}.{}.{}".format(
        dw_addr & 0xFF,
        (dw_addr >> 8) & 0xFF,
        (dw_addr >> 16) & 0xFF,
        (dw_addr >> 24) & 0xFF,
    )


def _normalize_addr(addr: str) -> str:
    """Normalize loopback aliases so comparisons match.

    The middleware can receive ``"127.0.0.1"``, ``"::1"``, or
    ``"::ffff:127.0.0.1"`` (IPv4-mapped IPv6) for the same connection
    depending on dual-stack settings. We keep the original family in
    the lookup but make sure mapped addresses get unwrapped.
    """
    if addr.startswith("::ffff:"):
        return addr[7:]  # unwrap to v4 form
    return addr


def _find_pid_v4(local_port: int, remote_addr: str, remote_port: int) -> Optional[int]:
    """Walk the IPv4 TCP table and return the owning PID for the
    connection whose (local_port, remote_addr, remote_port) match."""
    size = wintypes.DWORD(0)
    # First call: get the required size.
    _GetExtendedTcpTable(None, ctypes.byref(size), True, _AF_INET,
                         TCP_TABLE_OWNER_PID_ALL, 0)
    buf = (ctypes.c_byte * size.value)()
    err = _GetExtendedTcpTable(buf, ctypes.byref(size), True, _AF_INET,
                               TCP_TABLE_OWNER_PID_ALL, 0)
    if err != _ERROR_SUCCESS:
        return None
    # First DWORD is the entry count; rows follow immediately.
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(
        ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD),
        ctypes.POINTER(_MIB_TCPROW_OWNER_PID),
    )
    for i in range(count):
        row = rows[i]
        if (
            _decode_port(row.dwLocalPort) == local_port
            and _decode_port(row.dwRemotePort) == remote_port
            and _decode_v4_addr(row.dwRemoteAddr) == remote_addr
        ):
            return int(row.dwOwningPid)
    return None


def _decode_v6_addr(bytes_array) -> str:
    """Format a 16-byte IPv6 address as ``::1``-style."""
    return socket.inet_ntop(socket.AF_INET6, bytes(bytes_array))


def _find_pid_v6(local_port: int, remote_addr: str, remote_port: int) -> Optional[int]:
    """Walk the IPv6 TCP table. Same shape as the v4 helper."""
    size = wintypes.DWORD(0)
    _GetExtendedTcpTable(None, ctypes.byref(size), True, _AF_INET6,
                         TCP_TABLE_OWNER_PID_ALL, 0)
    buf = (ctypes.c_byte * size.value)()
    err = _GetExtendedTcpTable(buf, ctypes.byref(size), True, _AF_INET6,
                               TCP_TABLE_OWNER_PID_ALL, 0)
    if err != _ERROR_SUCCESS:
        return None
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(
        ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD),
        ctypes.POINTER(_MIB_TCP6ROW_OWNER_PID),
    )
    for i in range(count):
        row = rows[i]
        if (
            _decode_port(row.dwLocalPort) == local_port
            and _decode_port(row.dwRemotePort) == remote_port
            and _decode_v6_addr(row.ucRemoteAddr) == remote_addr
        ):
            return int(row.dwOwningPid)
    return None


def _find_pid(local_port: int, remote_addr: str, remote_port: int) -> Optional[int]:
    """Try v4 first if the peer looks IPv4, then v6 as a fallback.
    For mapped-IPv4 addresses we may need to check both tables."""
    addr = _normalize_addr(remote_addr)
    is_v4_form = ":" not in addr
    if is_v4_form:
        pid = _find_pid_v4(local_port, addr, remote_port)
        if pid is not None:
            return pid
        # Browsers sometimes connect via ::ffff:127.0.0.1 even when
        # the request looks v4 — try v6 as fallback.
        return _find_pid_v6(local_port, f"::ffff:{addr}", remote_port)
    pid = _find_pid_v6(local_port, addr, remote_port)
    if pid is not None:
        return pid
    return None


# ---------------------------------------------------------------------------
# Token / SID resolution
# ---------------------------------------------------------------------------


def _open_process_token(pid: int):
    """Open a query-only token for the given PID. Returns the pywin32
    handle, or None on failure (process exited, access denied, …).

    We use PROCESS_QUERY_LIMITED_INFORMATION (0x1000) because it's
    available even when the calling process is non-admin and the
    target process is an elevated peer — important for the case where
    a limited browser connects to ChAAMP."""
    try:
        proc = win32api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    except pywintypes.error:
        return None
    try:
        token = win32security.OpenProcessToken(proc, win32con.TOKEN_QUERY)
    except pywintypes.error:
        proc.Close()
        return None
    return token  # caller closes


def _token_user_sid(token) -> Optional[tuple[str, str]]:
    """Return ``(sid_string, "DOMAIN\\username")`` for the token user."""
    try:
        sid_obj, _attrs = win32security.GetTokenInformation(
            token, win32security.TokenUser,
        )
    except pywintypes.error:
        return None
    sid_str = win32security.ConvertSidToStringSid(sid_obj)
    try:
        name, domain, _type = win32security.LookupAccountSid(None, sid_obj)
        username = f"{domain}\\{name}" if domain else name
    except pywintypes.error:
        # SID didn't resolve (orphaned, deleted account, etc.). Keep
        # the SID — it still distinguishes the connection identity.
        username = sid_str
    return sid_str, username


def _is_member(token, group_sid_str: str) -> bool:
    """True iff the user behind ``token`` is a member of the group
    named by SID.

    UAC token filtering: on a default Windows install, an admin user's
    non-elevated process token has BUILTIN\\Administrators *filtered
    out* of its group list — even though the user IS in the group. A
    bare ``CheckTokenMembership`` would say False for an admin running
    a plain (non-elevated) browser. To fix that we fall back to the
    **linked token** (the elevated counterpart Windows keeps stashed
    on the filtered token) and retry the check against it.
    """
    try:
        sid = win32security.ConvertStringSidToSid(group_sid_str)
    except pywintypes.error:
        return False
    try:
        if bool(win32security.CheckTokenMembership(token, sid)):
            return True
    except pywintypes.error:
        # Fall through to the linked-token attempt.
        pass

    # Try the linked (elevated) token. GetTokenInformation raises if
    # there's no linked token (e.g., on a non-UAC system, or for a
    # genuine non-admin user) — in that case the original False
    # answer stands.
    try:
        linked = win32security.GetTokenInformation(
            token, win32security.TokenLinkedToken,
        )
    except pywintypes.error:
        return False
    try:
        return bool(win32security.CheckTokenMembership(linked, sid))
    except pywintypes.error:
        return False
    finally:
        # GetTokenInformation(TokenLinkedToken) returns a handle we own.
        try:
            linked.Close()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

# Per-source-port cache. A connection's 4-tuple is stable for its
# lifetime; the user/admin status of the OWNING PROCESS can in theory
# change (e.g., the user gets added to a group mid-session), so we
# expire entries on a short TTL rather than treating them as eternal.
CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cache: dict[tuple[str, int], tuple[float, SocketIdentity]] = {}


def _cache_get(key: tuple[str, int]) -> Optional[SocketIdentity]:
    with _cache_lock:
        v = _cache.get(key)
        if v is None:
            return None
        expires, ident = v
        if time.monotonic() > expires:
            _cache.pop(key, None)
            return None
        return ident


def _cache_put(key: tuple[str, int], ident: SocketIdentity) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, ident)


def cache_clear() -> None:
    """Wipe the identity cache. Tests call this between cases."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def identify_socket_owner(
    local_port: int,
    remote_addr: str,
    remote_port: int,
    *,
    admin_group_sid: str = "S-1-5-32-544",
) -> SocketIdentity | IdentifyError:
    """Identify the user owning the TCP connection described by the
    given 4-tuple, and check their membership in ``admin_group_sid``.

    Returns a :class:`SocketIdentity` on success or an
    :class:`IdentifyError` on any failure. The caller (the middleware)
    decides what to do — typically 403 on either an error or a
    ``is_admin=False`` result.
    """
    cache_key = (_normalize_addr(remote_addr), remote_port)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    pid = _find_pid(local_port, remote_addr, remote_port)
    if pid is None:
        return IdentifyError(
            reason="No TCP table entry for the connecting socket. The "
                   "connection may have closed before we looked it up.",
        )

    token = _open_process_token(pid)
    if token is None:
        return IdentifyError(
            reason=f"Couldn't open process {pid} to read its token "
                   "(access denied or process exited).",
        )
    try:
        ident_pair = _token_user_sid(token)
        if ident_pair is None:
            return IdentifyError(
                reason=f"Couldn't read token user for PID {pid}.",
            )
        sid_str, username = ident_pair
        is_admin = _is_member(token, admin_group_sid)
    finally:
        try:
            token.Close()
        except Exception:  # pragma: no cover — defensive
            pass

    ident = SocketIdentity(
        pid=pid,
        username=username,
        sid=sid_str,
        is_admin=is_admin,
    )
    _cache_put(cache_key, ident)
    return ident
