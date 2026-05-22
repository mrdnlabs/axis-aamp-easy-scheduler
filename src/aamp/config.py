"""Credential and host configuration for the AAM Pro API client.

Order of resolution (first match wins):
1. Explicit kwargs to ``load_config()``
2. Environment variables: ``AAMP_HOST``, ``AAMP_SERVER_NAME``, ``AAMP_USER``, ``AAMP_PASSWORD``
3. ``.aamp_credentials`` file in the project root (KEY=VALUE per line, # comments allowed)
4. ``.aamp_credentials`` file in the user's home directory

Additionally exposes **device** credentials for the per-device VAPIX client
used by the onboarding flow:
- ``AAMP_DEVICE_DEFAULT_USER`` — default admin username on Axis devices (typically ``root``).
- ``AAMP_DEVICE_DEFAULT_PASSWORD`` — password used for newly provisioned devices, AND the first candidate tried for already-provisioned devices.
- ``AAMP_DEVICE_PASSWORD_CANDIDATES`` — comma-separated list of additional passwords to try if the default doesn't authenticate. Used when onboarding a heterogeneous fleet.

The credentials file is in the project's ``.gitignore`` — do not commit it.
The password is never logged or included in error messages.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CREDS_FILE_NAMES = [".aamp_credentials"]


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


def _read_creds_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


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
    """Resolve AAM Pro connection config from kwargs, env, and creds files."""
    # Layer credentials sources — kwargs override env which overrides files.
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

    # Device credentials — parse optional comma-separated candidate list.
    device_cands_raw = pick("DEVICE_PASSWORD_CANDIDATES", None, "")
    device_candidates = [c.strip() for c in device_cands_raw.split(",") if c.strip()]

    cfg = AampConfig(
        host=pick("HOST", host, "https://localhost"),
        iam_host=pick("IAM_HOST", None, "https://localhost:10032"),
        server_name=pick("SERVER_NAME", server_name, "") or socket.gethostname(),
        username=pick("USER", username),
        _password=pick("PASSWORD", password),
        client_id=pick("CLIENT_ID", client_id, "") or None,
        _client_secret=pick("CLIENT_SECRET", client_secret, "") or None,
        verify_tls=(verify_tls if verify_tls is not None
                    else pick("VERIFY_TLS", None, "false").lower() in ("1", "true", "yes")),
        device_default_user=pick("DEVICE_DEFAULT_USER", None, "root"),
        _device_default_password=pick("DEVICE_DEFAULT_PASSWORD", None, ""),
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
            "AAMP_PASSWORD is not set. Configure via environment variable "
            "or .aamp_credentials file (chmod 600 / restrict permissions)."
        )
    return cfg
