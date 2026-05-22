"""Per-device VAPIX client for Axis network audio devices.

Talks to a single device's HTTP endpoints (typically port 80 or 443) using
HTTP Digest authentication. Modeled after :class:`aamp.api.AampApi` for
familiarity but with different auth (Digest, not Bearer) and a different
error envelope (Axis returns either JSON-RPC or XML, depending on endpoint).

Read-only surface (Phase 1):
    basic_info()             — GET /axis-cgi/basicdeviceinfo.cgi
    system_ready()           — POST /axis-cgi/systemready.cgi
    needs_initial_setup()    — convenience over system_ready
    is_reachable()           — quick health probe

The write surface (auth setup, ACAP install, param.cgi) is added in later
phases.

Auth model (verified per Axis docs, OS 11.6 split):
- Before OS 11.6: ``root`` user pre-exists without a password; we set one
  via POST /axis-cgi/pwdgrp.cgi on first contact.
- OS 11.6+: no user exists at all; same pwdgrp.cgi endpoint creates root.
- Once provisioned, the device challenges with HTTP Digest on every CGI.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional, Tuple

import httpx


class VapixError(RuntimeError):
    """Raised on a non-2xx response from a device VAPIX endpoint."""

    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        super().__init__(f"{method} {path} -> {status}: {body[:300]}")
        self.status = status
        self.method = method
        self.path = path
        self.body = body


class AuthState(str, Enum):
    """Result of an authentication attempt against a device."""
    NEEDS_INITIAL_SETUP = "needs_initial_setup"  # device has no root user / no password yet
    OK = "ok"                                    # we authenticated successfully
    UNKNOWN_PASSWORD = "unknown_password"        # device is provisioned but none of our candidates matched


# ---------------------------------------------------------------------------
# AxisDevice — main client
# ---------------------------------------------------------------------------

class AxisDevice:
    """One Axis device. Holds an httpx.Client configured for digest auth.

    Typical usage::

        with AxisDevice(ip="192.0.2.10", user="root", password="...") as dev:
            print(dev.basic_info())
            if dev.needs_initial_setup():
                ...  # phase 2 will fill this in

    Read-only methods do NOT require credentials — they target endpoints
    that respond unauthenticated. Once we add the write surface in later
    phases, an ``httpx.DigestAuth(user, password)`` will be attached.
    """

    def __init__(
        self,
        ip: str,
        *,
        user: Optional[str] = None,
        password: Optional[str] = None,
        scheme: str = "http",
        port: Optional[int] = None,
        timeout: float = 8.0,
        verify_tls: bool = False,
    ) -> None:
        self.ip = ip
        self._user = user
        self._password = password
        self.scheme = scheme
        self.port = port
        self._timeout = timeout
        self._verify = verify_tls

        # Single httpx.Client per device — important for HTTP Digest nonce
        # reuse. Bare client (no auth) for unauthenticated endpoints;
        # `_auth_client` is created lazily once we have credentials.
        port_part = f":{port}" if port else ""
        self._base_url = f"{scheme}://{ip}{port_part}"
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=4.0),
            verify=verify_tls,
        )
        self._auth: Optional[httpx.DigestAuth] = None
        if user and password:
            self._auth = httpx.DigestAuth(username=user, password=password)

    # -- lifecycle ------------------------------------------------------

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def __enter__(self) -> "AxisDevice":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low-level helpers ---------------------------------------------

    def _post_json_rpc(
        self,
        path: str,
        *,
        method: str,
        params: Optional[dict[str, Any]] = None,
        api_version: str = "1.0",
        auth: bool = False,
    ) -> dict[str, Any]:
        """Send an Axis JSON-RPC call. Body shape::

            {"apiVersion": ..., "method": ..., "params": ...}

        Responses look like::

            {"apiVersion": ..., "method": ..., "data": {...}}     # success
            {"apiVersion": ..., "method": ..., "error": {...}}    # failure (still HTTP 200)
        """
        body = {"apiVersion": api_version, "method": method}
        if params is not None:
            body["params"] = params
        kwargs: dict[str, Any] = {"json": body}
        if auth and self._auth is not None:
            kwargs["auth"] = self._auth
        try:
            r = self._client.post(path, **kwargs)
        except httpx.RequestError as e:
            raise VapixError(0, "POST", path, f"connection error: {e}") from e
        if r.status_code >= 400:
            raise VapixError(r.status_code, "POST", path, r.text or "")
        try:
            return r.json()
        except json.JSONDecodeError:
            raise VapixError(r.status_code, "POST", path,
                              f"non-JSON response: {r.text[:200]!r}")

    def _get(self, path: str, *, params: Optional[dict[str, Any]] = None,
              auth: bool = False) -> httpx.Response:
        kwargs: dict[str, Any] = {}
        if params:
            kwargs["params"] = params
        if auth and self._auth is not None:
            kwargs["auth"] = self._auth
        try:
            return self._client.get(path, **kwargs)
        except httpx.RequestError as e:
            raise VapixError(0, "GET", path, f"connection error: {e}") from e

    # -- read-only API -------------------------------------------------

    def is_reachable(self) -> bool:
        """Quick TCP probe — does the device's HTTP port answer at all?"""
        try:
            r = self._client.get("/", timeout=3.0)
            return r.status_code < 600   # any HTTP response means "alive"
        except httpx.HTTPError:
            return False

    def basic_info(self) -> dict[str, Any]:
        """Fetch model, firmware, serial, etc. from ``/axis-cgi/basicdeviceinfo.cgi``.

        On older Axis firmware this endpoint responds unauthenticated. On
        modern firmware (we confirmed this on AXIS OS 12+) it requires
        Digest auth. We auto-elevate: try unauthenticated first; if the
        device returns 401 OR the response is missing ``data.propertyList``
        and we have credentials, retry with auth.
        """
        props: dict[str, Any] = {}
        resp: dict[str, Any] = {}
        try:
            resp = self._post_json_rpc("/axis-cgi/basicdeviceinfo.cgi",
                                        method="getAllProperties")
            props = (resp.get("data") or {}).get("propertyList") or {}
        except VapixError as e:
            # 401 in particular is expected on modern firmware. Re-try with
            # auth if we have it; otherwise bubble up.
            if e.status != 401 or self._auth is None:
                raise
        # Auto-elevate when (a) we got a 401 above, or (b) the device
        # answered 200 but with an empty propertyList (some firmware does this).
        if not props and self._auth is not None:
            resp = self._post_json_rpc("/axis-cgi/basicdeviceinfo.cgi",
                                        method="getAllProperties", auth=True)
            props = (resp.get("data") or {}).get("propertyList") or {}
        if "error" in resp:
            raise VapixError(200, "POST", "/axis-cgi/basicdeviceinfo.cgi",
                              json.dumps(resp["error"]))
        return {
            "model": props.get("ProdShortName") or props.get("ProdNbr"),
            "model_nbr": props.get("ProdNbr"),
            "model_full": props.get("ProdFullName"),
            "model_type": props.get("ProdType"),
            "brand": props.get("Brand"),
            "serial": props.get("SerialNumber"),
            "firmware_version": props.get("Version"),
            "build_date": props.get("BuildDate"),
            "hardware_id": props.get("HardwareID"),
            "architecture": props.get("Architecture"),
            # Pass the full property bag through for callers who need it.
            "_raw": props,
        }

    def system_ready(self, *, timeout: int = 2) -> dict[str, Any]:
        """Call ``/axis-cgi/systemready.cgi`` (JSON-RPC).

        Returns the ``data`` dict, which on a healthy device looks like
        ``{"systemready": "yes", "needsetup": "no", "preview": "no", "uptime": "..."}``
        Behavior depends on firmware version — pre-OS-11.6 vs post.
        """
        resp = self._post_json_rpc("/axis-cgi/systemready.cgi",
                                    method="systemready",
                                    params={"timeout": timeout})
        if "error" in resp:
            raise VapixError(200, "POST", "/axis-cgi/systemready.cgi",
                              json.dumps(resp["error"]))
        return resp.get("data") or {}

    def needs_initial_setup(self) -> bool:
        """Authoritative check: does this device need a root password created?

        Uses ``systemready.cgi`` — never infer from a 401, because a 401 just
        means "wrong password", not "no user exists". Source-of-truth per
        AXIS OS 11.6 changelog.
        """
        try:
            data = self.system_ready()
        except VapixError:
            # If we can't even reach systemready, we don't know. Surface as
            # False so the caller doesn't accidentally create a root on a
            # device that's unreachable for unrelated reasons.
            return False
        # AXIS uses "yes"/"no" strings.
        needs = str(data.get("needsetup", "")).lower()
        return needs in ("yes", "true", "1")

    # -- authentication & initial setup --------------------------------

    def _set_credentials(self, user: str, password: str) -> None:
        """Attach (or swap) HTTP Digest credentials to this device client.

        Used internally by ``try_authenticate`` once we discover which
        candidate password works, and by ``create_root`` once we've just
        set a fresh password on a factory-reset device.
        """
        self._user = user
        self._password = password
        self._auth = httpx.DigestAuth(username=user, password=password)

    def try_authenticate(
        self,
        candidates: Optional[list[str]] = None,
        *,
        user: Optional[str] = None,
    ) -> Tuple[AuthState, Optional[str]]:
        """Figure out the auth state of this device.

        Strategy (per the onboarding plan):
          1. If ``needs_initial_setup()`` returns True -> the device has no
             root user / no password yet. Return ``NEEDS_INITIAL_SETUP``;
             onboarding will call ``create_root(default_password)`` next.
          2. Otherwise, walk the ``candidates`` list (defaults first, then
             legacy fleet passwords), trying each against the authenticated
             ``systemready.cgi`` endpoint. The first one that returns 200
             wins; we attach those creds to ``self._auth`` and return
             ``(OK, password)``.
          3. If all candidates 401, return ``(UNKNOWN_PASSWORD, None)``.

        We deliberately use ``systemready.cgi`` (which we know works on
        every supported firmware) rather than ``basicdeviceinfo.cgi``
        (which sometimes responds 200 unauthenticated, masking auth
        failures). The plan says: never infer "needs setup" from a 401.
        """
        effective_user = user or self._user or "root"
        # First, authoritative initial-setup probe — done unauthenticated.
        try:
            if self.needs_initial_setup():
                return AuthState.NEEDS_INITIAL_SETUP, None
        except VapixError:
            # If systemready is unreachable we cannot make a determination.
            # Fall through to the candidate walk; if those all 401 we'll
            # surface UNKNOWN_PASSWORD rather than a misleading sentinel.
            pass

        cand_list = list(candidates or [])
        if not cand_list:
            return AuthState.UNKNOWN_PASSWORD, None

        for pw in cand_list:
            auth = httpx.DigestAuth(username=effective_user, password=pw)
            try:
                r = self._client.post(
                    "/axis-cgi/systemready.cgi",
                    json={"apiVersion": "1.0", "method": "systemready",
                          "params": {"timeout": 2}},
                    auth=auth,
                )
            except httpx.RequestError:
                # Network blip — treat as miss but keep walking; a real
                # outage would have failed needs_initial_setup() too.
                continue
            if r.status_code == 401:
                continue
            if r.status_code == 200:
                # Some firmware returns 200 even with bad creds when the
                # endpoint is exposed; sanity-check the JSON envelope.
                try:
                    body = r.json()
                except json.JSONDecodeError:
                    continue
                if "error" in body:
                    continue
                self._set_credentials(effective_user, pw)
                return AuthState.OK, pw
            # Any other status (5xx, etc.) — treat as miss but keep walking.
        return AuthState.UNKNOWN_PASSWORD, None

    def create_root(self, password: str, *, user: str = "root") -> None:
        """Create the device's root admin via ``/axis-cgi/pwdgrp.cgi``.

        Per the AXIS OS 11.6 changelog, this same endpoint works for
        both flavours of "uninitialized" device:
          - Pre-11.6: ``root`` exists with no password; this sets one.
          - 11.6+:    no user exists at all; this creates ``root``.

        After this call the device starts requiring HTTP Digest on every
        CGI, so we attach the new creds to ``self._auth`` immediately for
        the rest of the onboarding flow.

        Raises ``VapixError`` if the device rejects the request — most
        commonly because (a) the device wasn't actually in needs-setup
        state, or (b) the password fails complexity rules.
        """
        if not password:
            raise ValueError("create_root requires a non-empty password")

        # pwdgrp.cgi takes form-style query params:
        #   action=add&user=root&pwd=...&grp=root&sgrp=admin:operator:viewer:ptz
        # The "sgrp" list controls which Axis "secondary groups" the user
        # belongs to; we grant the full admin set so the same account can
        # run the rest of the onboarding flow (ACAP install, param.cgi).
        params = {
            "action": "add",
            "user": user,
            "pwd": password,
            "grp": "root",
            "sgrp": "admin:operator:viewer:ptz",
        }
        try:
            # First contact is intentionally unauthenticated — that's the
            # whole point of the needs-setup window.
            # VERIFIED 2026-05-21 on C1110-E fw 12.9: pwdgrp.cgi requires
            # GET, not POST. POST returns 401 because the query-string
            # arguments aren't parsed. The Axis docs traditionally show GET
            # — POST was my erroneous guess from the original implementation.
            r = self._client.get("/axis-cgi/pwdgrp.cgi", params=params)
        except httpx.RequestError as e:
            raise VapixError(0, "GET", "/axis-cgi/pwdgrp.cgi",
                              f"connection error: {e}") from e

        # AXIS returns 200 with a tiny text/html body on success.
        # Success body: "Created account <user>." (often wrapped in <html>)
        # Failure body: "Error: ..." or "<html>...Unauthorized..." (etc.)
        body = (r.text or "").strip()
        if r.status_code >= 400:
            raise VapixError(r.status_code, "GET", "/axis-cgi/pwdgrp.cgi", body)
        body_low = body.lower()
        # The Axis HTML wraps the message; we check for the success token
        # OR the absence of an error indicator.
        if "created account" in body_low:
            pass  # success
        elif "error" in body_low or "unauthorized" in body_low:
            raise VapixError(200, "GET", "/axis-cgi/pwdgrp.cgi", body)

        # Attach the new creds so the next call in the pipeline doesn't
        # have to know we just provisioned the device.
        self._set_credentials(user, password)

    # -- ACAP applications --------------------------------------------

    def list_applications(self) -> list[dict[str, Any]]:
        """List installed ACAPs via ``/axis-cgi/applications/list.cgi``.

        Returns one dict per installed application with the keys Axis
        exposes in the XML response (``Name``, ``NiceName``, ``Vendor``,
        ``Version``, ``Status``, ``License``, ``ApplicationID``, ...).
        ``Status`` is one of "Running" / "Stopped" / "Idle".

        Requires authentication — devices reject this CGI unauthenticated.
        """
        r = self._get("/axis-cgi/applications/list.cgi", auth=True)
        if r.status_code >= 400:
            raise VapixError(r.status_code, "GET",
                              "/axis-cgi/applications/list.cgi", r.text or "")
        # Body is XML like:
        #   <reply result="ok">
        #     <application Name="aampro" NiceName="AXIS Audio Manager Pro"
        #                  Vendor="Axis" Version="5.1.34" Status="Running"
        #                  License="None" ApplicationID="..." />
        #     <application ... />
        #   </reply>
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            raise VapixError(r.status_code, "GET",
                              "/axis-cgi/applications/list.cgi",
                              f"unparseable XML: {e}: {r.text[:200]!r}") from e
        result = root.attrib.get("result", "").lower()
        if result and result != "ok":
            raise VapixError(r.status_code, "GET",
                              "/axis-cgi/applications/list.cgi",
                              f"reply result={result!r}: {r.text[:300]}")
        return [dict(app.attrib) for app in root.findall("application")]

    def has_application(self, name: str) -> Optional[dict[str, Any]]:
        """Return the application dict if installed, else ``None``.

        Matches case-insensitively against ``Name`` and ``NiceName`` so
        callers don't have to know which one Axis exposes.
        """
        target = name.strip().lower()
        for app in self.list_applications():
            if app.get("Name", "").lower() == target:
                return app
            if app.get("NiceName", "").lower() == target:
                return app
        return None

    def upload_acap(self, eap_path: Path | str) -> str:
        """Upload an ``.eap`` to ``/axis-cgi/applications/upload.cgi``.

        Multipart-form field name MUST be ``packfil`` (per Axis docs) —
        this is the well-known gotcha; other Axis CGIs use ``file``.
        Returns the raw text body on success ("OK" on most firmware).

        Raises ``VapixError`` on HTTP error or if the body indicates a
        failure (e.g. wrong architecture, malformed ACAP, out of space).
        """
        path = Path(eap_path)
        if not path.exists():
            raise FileNotFoundError(f"ACAP file not found: {path}")
        if self._auth is None:
            raise VapixError(0, "POST", "/axis-cgi/applications/upload.cgi",
                              "upload_acap requires authentication; "
                              "call try_authenticate() or create_root() first")

        # Big files + digest auth: bump timeout. ACAPs are ~5-15 MB and
        # the device unpacks them synchronously before returning.
        with path.open("rb") as fh:
            files = {"packfil": (path.name, fh, "application/octet-stream")}
            try:
                r = self._client.post(
                    "/axis-cgi/applications/upload.cgi",
                    files=files,
                    auth=self._auth,
                    timeout=httpx.Timeout(120.0, connect=4.0),
                )
            except httpx.RequestError as e:
                raise VapixError(0, "POST",
                                  "/axis-cgi/applications/upload.cgi",
                                  f"connection error: {e}") from e

        body = (r.text or "").strip()
        if r.status_code >= 400:
            raise VapixError(r.status_code, "POST",
                              "/axis-cgi/applications/upload.cgi", body)
        # Axis returns 200 with body "OK" on success, or 200 with a body
        # starting "Error: N" on application-level failures.
        # Known error codes (from Axis docs + empirical):
        #   Error: 1  — invalid package format
        #   Error: 4  — already installed (sometimes)
        #   Error: 5  — wrong CPU architecture (the .eap doesn't match the device)
        #   Error: 6  — out of space / no flash
        if body.lower().startswith("error"):
            hint = ""
            if "5" in body:
                hint = (" — wrong CPU architecture for this device. "
                        "Verify the .eap matches device arch (basicdeviceinfo "
                        "Architecture field is authoritative)")
            elif "1" in body:
                hint = " — invalid .eap package format"
            elif "6" in body:
                hint = " — device out of space"
            raise VapixError(r.status_code, "POST",
                              "/axis-cgi/applications/upload.cgi",
                              body + hint)
        return body or "OK"

    def _control_application(self, action: str, name: str) -> str:
        """POST ``/axis-cgi/applications/control.cgi?action=...&package=...``."""
        if self._auth is None:
            raise VapixError(0, "POST", "/axis-cgi/applications/control.cgi",
                              "control_application requires authentication")
        try:
            r = self._client.post(
                "/axis-cgi/applications/control.cgi",
                params={"action": action, "package": name},
                auth=self._auth,
            )
        except httpx.RequestError as e:
            raise VapixError(0, "POST",
                              "/axis-cgi/applications/control.cgi",
                              f"connection error: {e}") from e
        body = (r.text or "").strip()
        if r.status_code >= 400:
            raise VapixError(r.status_code, "POST",
                              "/axis-cgi/applications/control.cgi", body)
        if body.lower().startswith("error"):
            raise VapixError(r.status_code, "POST",
                              "/axis-cgi/applications/control.cgi", body)
        return body or "OK"

    def start_application(self, name: str) -> str:
        """Start an installed ACAP by package name (Axis ``Name`` attribute)."""
        return self._control_application("start", name)

    def stop_application(self, name: str) -> str:
        """Stop a running ACAP. Idempotent — already-stopped is a no-op."""
        return self._control_application("stop", name)

    def restart_application(self, name: str) -> str:
        """Stop-then-start. Used after pushing a new config that needs a reload."""
        try:
            self.stop_application(name)
        except VapixError:
            # If the app wasn't running, stop returns an error on some
            # firmware — swallow and try start anyway.
            pass
        return self.start_application(name)

    # -- param.cgi (read/write device parameters) ---------------------

    def param_list(self, group: Optional[str] = None) -> dict[str, str]:
        """List device parameters via ``/axis-cgi/param.cgi?action=list``.

        If ``group`` is given (e.g. ``"AudioManagerPro"``), only parameters
        under that root are returned. Response is a flat ``key=value`` text
        body that we parse into a dict.

        Requires authentication.
        """
        if self._auth is None:
            raise VapixError(0, "GET", "/axis-cgi/param.cgi",
                              "param_list requires authentication")
        params: dict[str, Any] = {"action": "list"}
        if group:
            params["group"] = group
        r = self._get("/axis-cgi/param.cgi", params=params, auth=True)
        if r.status_code >= 400:
            raise VapixError(r.status_code, "GET", "/axis-cgi/param.cgi",
                              r.text or "")
        body = r.text or ""
        if body.lstrip().lower().startswith("# error"):
            raise VapixError(r.status_code, "GET", "/axis-cgi/param.cgi", body)
        out: dict[str, str] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    def param_set(self, updates: dict[str, str]) -> str:
        """Write one or more device parameters via ``/axis-cgi/param.cgi?action=update``.

        ``updates`` keys are full parameter paths (e.g.
        ``root.AudioManagerPro.PrimaryServerIpAddress``). The CGI returns
        "OK" on success or a body starting with ``# Error`` on failure.

        VERIFIED 2026-05-21 on C1110-E fw 12.9: ``param.cgi`` requires GET,
        not POST. POSTing returned ``'action must be specified'`` because
        the firmware doesn't parse query-string args on POST. GET works for
        both list and update.

        Requires authentication.
        """
        if self._auth is None:
            raise VapixError(0, "GET", "/axis-cgi/param.cgi",
                              "param_set requires authentication")
        if not updates:
            return "OK"
        params: dict[str, Any] = {"action": "update"}
        params.update(updates)
        try:
            r = self._client.get("/axis-cgi/param.cgi", params=params,
                                  auth=self._auth)
        except httpx.RequestError as e:
            raise VapixError(0, "GET", "/axis-cgi/param.cgi",
                              f"connection error: {e}") from e
        body = (r.text or "").strip()
        if r.status_code >= 400:
            raise VapixError(r.status_code, "GET", "/axis-cgi/param.cgi", body)
        if body.lower().startswith(("# error", "error")):
            raise VapixError(r.status_code, "GET", "/axis-cgi/param.cgi", body)
        return body or "OK"

    # -- system control ----------------------------------------------------

    def reboot(self) -> str:
        """Soft-reboot the device via ``/axis-cgi/restart.cgi``.

        Returns once the device has acknowledged the request — the actual
        restart happens asynchronously and the device is unreachable for
        roughly 45-90 seconds afterward depending on model.
        """
        if self._auth is None:
            raise VapixError(0, "POST", "/axis-cgi/restart.cgi",
                              "reboot requires authentication")
        try:
            r = self._client.post("/axis-cgi/restart.cgi", auth=self._auth)
        except httpx.RequestError as e:
            raise VapixError(0, "POST", "/axis-cgi/restart.cgi",
                              f"connection error: {e}") from e
        body = (r.text or "").strip()
        if r.status_code >= 400:
            raise VapixError(r.status_code, "POST", "/axis-cgi/restart.cgi",
                              body)
        return body or "OK"

    def factory_default(self, *, hard: bool = True) -> str:
        """Reset the device to factory defaults via ``/axis-cgi/factorydefault.cgi``.

        Wipes all settings INCLUDING the admin password and any installed
        ACAPs. The device reboots and comes back in the "needs initial
        setup" state — your next call must be ``create_root`` to provision
        it again.

        Args:
            hard: if True (default), a hard factory reset that also wipes
                network configuration. If False, a softer reset that keeps
                IP / DNS / hostname settings (less likely to lose the device
                if DHCP misbehaves, but doesn't reset everything).

        Returns the device's response body (usually short). Caller is
        expected to wait ~45-90 seconds before contacting the device again.
        """
        if self._auth is None:
            raise VapixError(0, "GET", "/axis-cgi/factorydefault.cgi",
                              "factory_default requires authentication")
        path = "/axis-cgi/hardfactorydefault.cgi" if hard else "/axis-cgi/factorydefault.cgi"
        try:
            r = self._client.get(path, auth=self._auth)
        except httpx.RequestError as e:
            # The device commonly closes the connection mid-response while
            # rebooting — treat a connection-close after sending the
            # request as success.
            return f"connection closed mid-response (likely already rebooting): {e}"
        body = (r.text or "").strip()
        if r.status_code >= 400:
            raise VapixError(r.status_code, "GET", path, body)
        return body or "OK"

    # -- snapshot helper -----------------------------------------------

    def inspect(self) -> dict[str, Any]:
        """One-call summary of a device's read-only state.

        Combines ``is_reachable`` + ``basic_info`` + ``system_ready``.
        Designed to be the response of the ``inspect_axis_device`` MCP tool.
        """
        out: dict[str, Any] = {"ip": self.ip, "reachable": False}
        if not self.is_reachable():
            return out
        out["reachable"] = True
        try:
            out["basic_info"] = self.basic_info()
        except VapixError as e:
            out["basic_info_error"] = str(e)
        try:
            out["system_ready"] = self.system_ready()
            out["needs_initial_setup"] = bool(
                str(out["system_ready"].get("needsetup", "")).lower()
                in ("yes", "true", "1")
            )
        except VapixError as e:
            out["system_ready_error"] = str(e)
        return out
