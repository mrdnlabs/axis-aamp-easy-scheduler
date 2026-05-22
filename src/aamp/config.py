"""Connection configuration for the AAM Pro API client.

**Non-secret fields** (host, server name, username, etc.) resolve via:
1. Explicit kwargs to ``load_config()``
2. Environment variables: ``AAMP_HOST``, ``AAMP_SERVER_NAME``, ``AAMP_USER``, ...
3. ``.aamp_credentials`` file in the project root (KEY=VALUE per line, # comments allowed)
4. ``.aamp_credentials`` file in the user's home directory

**Secret fields** (password, client_secret, device_default_password, device_password_candidates)
resolve via the credential store (see :mod:`aamp.credentials`). Default
backend is OS-native keyring with ``.aamp_credentials`` as legacy fallback.
This keeps secrets out of plaintext config files once they're migrated.

The legacy ``.aamp_credentials`` file is in the project's ``.gitignore`` —
do not commit it. Passwords are never logged or included in error messages.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .credentials import (
    CREDS_FILE_NAMES,
    PROJECT_ROOT,
    _read_creds_file,
    get_credential_store,
)


@dataclass
class AampConfig:
    """Connection settings for the AAM Pro API."""
    host: str = "https://localhost"               # where /webapi/v1/* lives (443 proxy)
    iam_host: str = "https://localhost:10032"     # IAM direct (more reliable than 443 proxy for OAuth)
    server_name: str = ""  # populated to socket.gethostname() if empty
    username: str = ""
    # Password is held separately to keep it out of stringified config.
    _password: str = field(default="", repr=False)
    verify_tls: bool = False
    # Optional pre-registered confidential client. If both are set we skip dynamic
    # client registration.
    client_id: Optional[str] = None
    _client_secret: Optional[str] = field(default=None, repr=False)
    # Per-device VAPIX credentials (optional — only needed for device onboarding).
    device_default_user: str = "root"
    _device_default_password: str = field(default="", repr=False)
    _device_password_candidates: List[str] = field(default_factory=list, repr=False)
    # Hostname / IP that audio devices should use to reach the AAM Pro server.
    # Empty = auto-detect per-device by inferring which local interface routes
    # to each device (correct for multi-homed servers). Set this explicitly
    # when (a) AAM Pro is behind NAT and devices must use a public hostname,
    # (b) you want devices to use an FQDN instead of an IP, or (c) the
    # per-device inference picks the wrong interface for some other reason.
    device_facing_host: str = ""

    @property
    def password(self) -> str:
        return self._password

    @property
    def client_secret(self) -> Optional[str]:
        return self._client_secret

    @property
    def device_default_password(self) -> str:
        return self._device_default_password

    @property
    def device_password_candidates(self) -> List[str]:
        """All passwords to try for device auth, default first, then extras (deduped)."""
        out: list[str] = []
        if self._device_default_password:
            out.append(self._device_default_password)
        for cand in self._device_password_candidates:
            if cand and cand not in out:
                out.append(cand)
        return out

    def __repr__(self) -> str:  # safe stringification — never echo password
        n_cands = len(self._device_password_candidates)
        return (
            f"AampConfig(host={self.host!r}, server_name={self.server_name!r}, "
            f"username={self.username!r}, password=***, "
            f"client_id={self.client_id!r}, client_secret={'***' if self._client_secret else None}, "
            f"device_default_user={self.device_default_user!r}, "
            f"device_default_password={'***' if self._device_default_password else None}, "
            f"device_password_candidates=[{n_cands} extras])"
        )


def load_config(
    *,
    host: Optional[str] = None,
    server_name: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    verify_tls: Optional[bool] = None,
    require_password: bool = True,
) -> AampConfig:
    """Resolve AAM Pro connection config.

    Non-secret fields resolve from kwargs → env → ``.aamp_credentials``.
    Secret fields (password, client_secret, device_default_password,
    device_password_candidates) resolve from the credential store. Explicit
    kwargs always take precedence — useful for tests.
    """
    # Layer NON-secret sources — kwargs override env which overrides files.
    file_creds: dict[str, str] = {}
    for candidate in (PROJECT_ROOT / CREDS_FILE_NAMES[0], Path.home() / CREDS_FILE_NAMES[0]):
        if candidate.exists():
            file_creds = _read_creds_file(candidate)
            break

    def pick(name: str, kw: Optional[str], default: str = "") -> str:
        if kw is not None:
            return kw
        env_val = os.environ.get(f"AAMP_{name.upper()}")
        if env_val:
            return env_val
        return file_creds.get(f"AAMP_{name.upper()}", default)

    # Secrets via the credential store. Explicit kwargs win when provided.
    store = get_credential_store()
    secret_password = password if password is not None else (
        store.get("aamp", "password") or "")
    secret_client_secret = client_secret if client_secret is not None else (
        store.get("aamp", "client_secret") or None)
    secret_device_default_password = store.get("device", "default_password") or ""
    secret_device_candidates_raw = store.get("device", "password_candidates") or ""
    device_candidates = [c.strip() for c in secret_device_candidates_raw.split(",") if c.strip()]

    cfg = AampConfig(
        host=pick("HOST", host, "https://localhost"),
        iam_host=pick("IAM_HOST", None, "https://localhost:10032"),
        server_name=pick("SERVER_NAME", server_name, "") or socket.gethostname(),
        username=pick("USER", username),
        _password=secret_password,
        client_id=pick("CLIENT_ID", client_id, "") or None,
        _client_secret=secret_client_secret,
        verify_tls=(verify_tls if verify_tls is not None
                    else pick("VERIFY_TLS", None, "false").lower() in ("1", "true", "yes")),
        device_default_user=pick("DEVICE_DEFAULT_USER", None, "root"),
        _device_default_password=secret_device_default_password,
        _device_password_candidates=device_candidates,
        device_facing_host=pick("DEVICE_FACING_HOST", None, ""),
    )

    if not cfg.username:
        raise RuntimeError(
            "AAMP_USER is not set. Configure via environment variable "
            "(e.g., $env:AAMP_USER='demoadmin') or .aamp_credentials file."
        )
    if require_password and not cfg.password:
        raise RuntimeError(
            "AAM Pro admin password is not configured. To set it without "
            "exposing it in chat, open a TERMINAL (not chat) and run:\n"
            "    aamp-set-credential aamp/password\n"
            "Existing setups using AAMP_PASSWORD in .aamp_credentials still "
            "work; run `aamp-migrate-credentials` to move the value into the "
            "OS keyring."
        )
    return cfg
