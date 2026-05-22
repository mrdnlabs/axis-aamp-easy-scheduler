"""OAuth2 / OIDC client for AAM Pro's bundled AXIS IAM On-prem (Ory Hydra 8.1.1).

Talks to the AamPro 443 proxy at ``https://localhost/oauth/v1/*``. This routes
through the reverse proxy back to the IAM at port 10032 — same Hydra
instance under the hood, but using the 443 path means **session cookies
set during /authorize/handle land on the 443 origin**, where /webapi/v1/*
also lives. Empirically, /webapi/v1/* POST/PATCH/PUT calls reject Bearer
tokens with ``401 Invalid access token`` when those session cookies are
missing — GETs are lenient and accept Bearer alone, but writes need both.

If the 443 proxy is flaky for /oauth/v1/clients (we've seen sporadic 503s),
we fall back to the direct IAM at port 10032 for that single step only —
client registration doesn't need to set cookies on 443.

Flow (matches the SPA's captured behavior):

    1. POST /v1/clients         — register a public PKCE client (or reuse a pre-registered one)
    2. GET  /v1/authorize       — fetch the login page, parse data-auth-session-id from the root div
    3. POST /v1/authorize/handle — submit username + password (form)
    4. POST /v1/token           — exchange auth code for access + refresh tokens

The auth code is delivered as the ``code`` query parameter on the 303 redirect's
Location header — we explicitly disable redirect-following so we can read it.

Tokens auto-refresh when within 30s of expiry. Token-handling rules:
- Never log the password, access token, or refresh token.
- Storage is in-memory only; nothing touches disk in this module.
- On refresh failure we fall back to a full re-login.

Public surface:
    AampAuth(config).access_token()  → str  (always a fresh valid token)
    AampAuth(config).http_headers()  → dict  (Authorization + JSON content-type)
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .config import AampConfig


REDIRECT_URI = "https://localhost"  # matches what the SPA registers; must match across all four calls


class AuthError(RuntimeError):
    """Raised for any failure in the OAuth flow."""


@dataclass
class _Tokens:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # epoch seconds

    def is_valid(self, slack: float = 30.0) -> bool:
        return bool(self.access_token) and time.time() < (self.expires_at - slack)


# ---- PKCE helpers ----------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) pair per RFC 7636 S256."""
    verifier = secrets.token_urlsafe(32)  # ~43 chars from the unreserved set
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


_AUTH_SESSION_RE = re.compile(
    r'data-auth-session-id=["\']([0-9a-f-]{36})["\']',
    re.IGNORECASE,
)
_INCORRECT_CREDS_RE = re.compile(
    r'data-incorrect-credentials=["\']true["\']',
    re.IGNORECASE,
)


def _extract_auth_session_id(html: str) -> str:
    """Pull the auth-session-id from the SPA login page's root div data attribute.

    The IAM login page is an SPA shell — there's no form, just a ``<div id="root">``
    with data attributes carrying client_id, redirect_uri, auth-session-id, and the
    server_name. JavaScript binds them to a real form that POSTs to /v1/authorize/handle.
    """
    if _INCORRECT_CREDS_RE.search(html):
        raise AuthError(
            "Login page reports data-incorrect-credentials=true. "
            "Verify AAMP_USER / AAMP_PASSWORD in your environment or .aamp_credentials file."
        )
    m = _AUTH_SESSION_RE.search(html)
    if not m:
        raise AuthError(
            "Could not locate data-auth-session-id in the login page HTML. "
            "The IAM may have changed its template — re-capture with the observer "
            "and inspect the page structure."
        )
    return m.group(1)


# ---- Auth client -----------------------------------------------------------

class AampAuth:
    """Manages OAuth2 tokens for talking to AAM Pro's /webapi/v1/* endpoints.

    Usage:
        auth = AampAuth(config)
        token = auth.access_token()             # blocking; runs full login on first call
        headers = auth.http_headers()           # convenience for httpx clients
    """

    def __init__(self, config: AampConfig, http: Optional[httpx.Client] = None) -> None:
        """Args:
            config: connection settings.
            http: optional shared ``httpx.Client``. If provided, OAuth flow uses it
                and session cookies persist into subsequent /webapi/v1/* calls
                made on the same client. **Highly recommended** for write
                operations — without shared cookies, writes fail with 401.
        """
        self._config = config
        self._client_id: Optional[str] = config.client_id  # may be pre-registered
        self._tokens = _Tokens()
        self._owns_http = http is None
        # 443 proxy is the primary path for OAuth — see module docstring.
        self._http = http or httpx.Client(
            base_url=config.host,
            verify=config.verify_tls,
            follow_redirects=False,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        # Fallback IAM client for /clients if the 443 proxy 503s.
        self._iam_http = httpx.Client(
            base_url=config.iam_host,
            verify=config.verify_tls,
            follow_redirects=False,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    # -- public ----------------------------------------------------------

    def access_token(self) -> str:
        """Return a valid access token, logging in or refreshing as needed."""
        if self._tokens.is_valid():
            return self._tokens.access_token
        if self._tokens.refresh_token:
            try:
                self._refresh()
                return self._tokens.access_token
            except AuthError:
                # Fall through to a full re-login.
                self._tokens = _Tokens()
        self._full_login()
        return self._tokens.access_token

    def http_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def close(self) -> None:
        if self._owns_http:
            try:
                self._http.close()
            except Exception:
                pass
        try:
            self._iam_http.close()
        except Exception:
            pass

    def __enter__(self) -> "AampAuth":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- flow steps ------------------------------------------------------

    def _full_login(self) -> None:
        if not self._client_id:
            self._register_public_client()
        code, verifier = self._authorize_with_password_grant()
        self._exchange_code(code, verifier)

    def _register_public_client(self) -> None:
        """Dynamic client registration matching the SPA's call.

        Tries the 443 proxy first (path /oauth/v1/clients); if it 503s,
        falls back to the IAM direct path (port 10032, /v1/clients).
        """
        body = {
            "redirect_uris": [REDIRECT_URI],
            "response_types": ["code"],
            "grant_types": ["authorization_code", "refresh_token"],
            "application_type": "web",
            "client_name": "Aamp Easy Scheduler",  # spaces ok; hyphens rejected
            "token_endpoint_auth_method": "none",
        }
        r = self._http.post("/oauth/v1/clients", json=body)
        if r.status_code in (502, 503, 504):
            # 443 proxy flapped — fall through to direct IAM.
            r = self._iam_http.post("/v1/clients", json=body)
        if r.status_code != 201:
            raise AuthError(f"client registration failed: {r.status_code} {r.text[:300]}")
        client_id = r.json().get("client_id")
        if not client_id:
            raise AuthError("client registration returned no client_id")
        self._client_id = client_id

    def _authorize_with_password_grant(self) -> tuple[str, str]:
        """Walk steps 2 and 3 of the flow and return (auth_code, pkce_verifier)."""
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(12)

        # Step 2: GET /authorize → 200 HTML login page (sets a cookie session).
        params = {
            "client_id": self._client_id,
            "redirect_uri": REDIRECT_URI,
            "nonce": "not-used-right-now",
            "scope": "openid offline",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        r = self._http.get("/oauth/v1/authorize", params=params)
        if r.status_code != 200:
            raise AuthError(f"authorize step failed: {r.status_code} {r.text[:300]}")
        auth_session_id = _extract_auth_session_id(r.text)

        # Step 3: POST /authorize/handle with credentials.
        form = {
            "serverName": self._config.server_name,
            "username": self._config.username,
            "password": self._config.password,
            "redirect_uri": REDIRECT_URI,
            "client_id": self._client_id or "",
            "auth_session_id": auth_session_id,
        }
        r2 = self._http.post(
            "/oauth/v1/authorize/handle",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r2.status_code not in (302, 303):
            # On bad credentials the IAM typically returns 200 with an error in the HTML
            # rather than a redirect. Don't leak the password in errors.
            snippet = r2.text[:300].replace(self._config.password, "***")
            raise AuthError(
                f"login failed: {r2.status_code} (no redirect). "
                f"Check AAMP_USER/AAMP_PASSWORD/AAMP_SERVER_NAME. "
                f"Response excerpt: {snippet}"
            )
        location = r2.headers.get("location") or r2.headers.get("Location")
        if not location:
            raise AuthError("login redirect missing Location header")
        qs = parse_qs(urlparse(location).query)
        if "code" not in qs:
            # Maybe an error response.
            err = qs.get("error", ["unknown"])[0]
            raise AuthError(f"login redirect carried error: {err} (no code in {location})")
        return qs["code"][0], verifier

    def _exchange_code(self, code: str, verifier: str) -> None:
        form = {
            "client_id": self._client_id or "",
            "code": code,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        }
        r = self._http.post(
            "/oauth/v1/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            raise AuthError(f"token exchange failed: {r.status_code} {r.text[:300]}")
        self._store_token_response(r.json())

    def _refresh(self) -> None:
        if not self._client_id or not self._tokens.refresh_token:
            raise AuthError("no client_id or refresh_token; cannot refresh")
        form = {
            "client_id": self._client_id,
            "refresh_token": self._tokens.refresh_token,
            "grant_type": "refresh_token",
        }
        r = self._http.post(
            "/oauth/v1/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            raise AuthError(f"refresh failed: {r.status_code} {r.text[:200]}")
        self._store_token_response(r.json())

    def _store_token_response(self, payload: dict) -> None:
        access = payload.get("access_token")
        if not access:
            raise AuthError("token response missing access_token")
        expires_in = int(payload.get("expires_in", 0))
        self._tokens = _Tokens(
            access_token=access,
            refresh_token=payload.get("refresh_token", self._tokens.refresh_token),
            expires_at=time.time() + max(60, expires_in),  # never trust 0
        )
