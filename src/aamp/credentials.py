"""Encrypted credential store with OS-native backend.

**Purpose.** Keep secrets out of plaintext config files and out of LLM context.
Callers ask for credentials by ``(account_id, field)`` — never look them up
by raw path or filename — and the store resolves them at the moment of use.

**This module owns ONLY secrets.** Non-secret config (host, username,
voice_id, etc.) stays in :mod:`aamp.config` and ``.aamp_credentials`` /
environment variables. The store is consulted only for the small set of
fields enumerated in :data:`KNOWN_SECRETS`.

**Backends:**

- :class:`KeyringCredentialStore` — uses the OS-native credential store via
  the `keyring` library (Windows Credential Manager on Windows, libsecret
  on Linux, Keychain on macOS). Writable. Default backend.
- :class:`EnvCredentialStore` — reads secrets out of process environment
  variables and ``.aamp_credentials`` (project root or ``~``). Read-only.
  Preserves the existing setup so users with a ``.aamp_credentials`` file
  Just Work during the transition.
- :class:`ChainedCredentialStore` — walks a list of stores on ``get``;
  writes go to the first writable store in the chain. This is what
  :func:`get_credential_store` returns by default: keyring first, env
  fallback. After ``aamp-migrate-credentials`` is run, the env fallback
  rarely fires.

**Canonical secret table.** Every secret used anywhere in the codebase
appears in :data:`KNOWN_SECRETS` below. Adding a new secret is a
three-step change:

1. Add a row to :data:`KNOWN_SECRETS`
2. Fetch it in the calling code via ``get_credential_store().get(account_id, field)``
3. Document it in ``docs/credential_handling.md``

That's it. No other file knows the secret name.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Canonical secret table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecretField:
    """A canonical secret-field declaration. Single source of truth."""
    account_id: str
    field: str
    env_var: str          # legacy environment-variable name (for migration + EnvCredentialStore)
    description: str
    is_csv_list: bool = False   # True for fields stored as a comma-separated string


#: Every secret used anywhere in the codebase. Add a row here when introducing
#: a new secret. Callers reference these by ``account_id`` + ``field``.
KNOWN_SECRETS: tuple[SecretField, ...] = (
    SecretField("aamp", "password", "AAMP_PASSWORD",
                "AAM Pro admin login password"),
    SecretField("aamp", "client_secret", "AAMP_CLIENT_SECRET",
                "Pre-registered OAuth confidential client secret (optional)"),
    SecretField("device", "default_password", "AAMP_DEVICE_DEFAULT_PASSWORD",
                "Fleet password set on freshly provisioned Axis devices"),
    SecretField("device", "password_candidates", "AAMP_DEVICE_PASSWORD_CANDIDATES",
                "Comma-separated additional passwords for legacy/heterogeneous fleets",
                is_csv_list=True),
    SecretField("elevenlabs", "api_key", "ELEVENLABS_API_KEY",
                "ElevenLabs voice-generation API key"),
)


def secret_for(account_id: str, field: str) -> Optional[SecretField]:
    """Look up the canonical SecretField for ``(account_id, field)``. Returns None if not known."""
    for s in KNOWN_SECRETS:
        if s.account_id == account_id and s.field == field:
            return s
    return None


# ---------------------------------------------------------------------------
# Store interface
# ---------------------------------------------------------------------------

class CredentialStore(ABC):
    """Abstract base for credential backends.

    Implementations are responsible for at-rest encryption, durability, and
    OS-level access controls. Callers should treat the store as opaque —
    look up by ``(account_id, field)``, never by underlying path/identifier.
    """

    @abstractmethod
    def get(self, account_id: str, field: str) -> Optional[str]:
        """Retrieve a credential value, or None if not stored."""

    @abstractmethod
    def set(self, account_id: str, field: str, value: str) -> None:
        """Store a credential value, overwriting any existing one."""

    @abstractmethod
    def delete(self, account_id: str, field: str) -> None:
        """Remove a credential. No-op if not present."""

    @abstractmethod
    def list_accounts(self) -> list[tuple[str, list[str]]]:
        """Return ``[(account_id, [field, ...]), ...]`` for everything stored.

        Values are NEVER returned — this is for listing what's stored, not
        what the values are.
        """

    @property
    def is_writable(self) -> bool:
        """True if the store accepts writes. EnvCredentialStore is read-only."""
        return True

    @property
    def name(self) -> str:
        """Short identifier for logging / error messages."""
        return type(self).__name__


# ---------------------------------------------------------------------------
# .aamp_credentials reader (used by EnvCredentialStore + migration)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CREDS_FILE_NAMES = (".aamp_credentials",)


def _read_creds_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE / # comments file. Empty dict if missing."""
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


def find_credentials_file() -> Optional[Path]:
    """Return the first ``.aamp_credentials`` found (project root, then ``~``)."""
    for candidate in (PROJECT_ROOT / CREDS_FILE_NAMES[0],
                       Path.home() / CREDS_FILE_NAMES[0]):
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# EnvCredentialStore — read-only fallback for legacy .aamp_credentials + env
# ---------------------------------------------------------------------------

class EnvCredentialStore(CredentialStore):
    """Read-only store backed by environment variables and ``.aamp_credentials``.

    Lookup order for each secret: env var (``secret.env_var``) → first
    found ``.aamp_credentials`` file (project root, then home).

    Used during migration so existing setups keep working. Writes raise
    ``NotImplementedError`` — use :class:`KeyringCredentialStore` for that.
    """

    def __init__(self, creds_file: Optional[Path] = None) -> None:
        self._file_creds: dict[str, str] = {}
        if creds_file is None:
            creds_file = find_credentials_file()
        if creds_file is not None and creds_file.exists():
            self._file_creds = _read_creds_file(creds_file)
        self._creds_file = creds_file

    @property
    def is_writable(self) -> bool:
        return False

    def get(self, account_id: str, field: str) -> Optional[str]:
        s = secret_for(account_id, field)
        if s is None:
            return None
        env_val = os.environ.get(s.env_var)
        if env_val:
            return env_val
        return self._file_creds.get(s.env_var) or None

    def set(self, account_id: str, field: str, value: str) -> None:
        raise NotImplementedError(
            f"{type(self).__name__} is read-only. Use the keyring backend "
            "(via aamp-set-credential) for writes."
        )

    def delete(self, account_id: str, field: str) -> None:
        raise NotImplementedError(
            f"{type(self).__name__} is read-only. Edit .aamp_credentials directly "
            "to remove legacy values, or use aamp-delete-credential to remove keyring entries."
        )

    def list_accounts(self) -> list[tuple[str, list[str]]]:
        present: dict[str, list[str]] = {}
        for s in KNOWN_SECRETS:
            if self.get(s.account_id, s.field) is not None:
                present.setdefault(s.account_id, []).append(s.field)
        return [(a, sorted(f)) for a, f in sorted(present.items())]


# ---------------------------------------------------------------------------
# KeyringCredentialStore — OS-native, writable, default backend
# ---------------------------------------------------------------------------

KEYRING_SERVICE_PREFIX = "aamp."
INDEX_FILE = Path.home() / ".aamp_credential_index.json"


class KeyringCredentialStore(CredentialStore):
    """OS-native credential store via the ``keyring`` library.

    Storage layout: each secret is stored under
    ``service="aamp.<account_id>", username="<field>"``. Values are
    encrypted by the OS keyring at rest (Windows Credential Manager,
    macOS Keychain, libsecret).

    Listing: ``keyring`` has no enumeration API on Windows. We maintain a
    metadata-only JSON index at ``~/.aamp_credential_index.json`` recording
    which (account_id, field) pairs have been written. The index never
    contains values.

    Health check at construction: writes a sentinel, reads it back,
    deletes it. If the backend can't persist, raises ``RuntimeError``
    with a clear message so callers don't silently degrade.
    """

    SENTINEL_ACCOUNT = "_aamp_sentinel"
    SENTINEL_FIELD = "_probe"

    def __init__(self, *, skip_health_check: bool = False) -> None:
        try:
            import keyring  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "keyring library not installed. Run: pip install keyring"
            ) from e
        self._keyring = keyring
        if not skip_health_check:
            self._health_check()

    def _health_check(self) -> None:
        """Smoke-test the backend. Raises RuntimeError on failure."""
        svc = f"{KEYRING_SERVICE_PREFIX}{self.SENTINEL_ACCOUNT}"
        try:
            self._keyring.set_password(svc, self.SENTINEL_FIELD, "ok")
            got = self._keyring.get_password(svc, self.SENTINEL_FIELD)
            self._keyring.delete_password(svc, self.SENTINEL_FIELD)
        except Exception as e:
            raise RuntimeError(
                f"Keyring backend health check failed: {type(e).__name__}: {e}. "
                "The OS credential store may not be available in this session "
                "(common on headless service accounts). Use AAMP_CREDENTIAL_BACKEND=env "
                "to fall back to .aamp_credentials, or fix the keyring backend."
            ) from e
        if got != "ok":
            raise RuntimeError(
                f"Keyring write succeeded but read returned {got!r}. "
                "The backend is unreliable; refusing to use it."
            )

    def _service(self, account_id: str) -> str:
        return f"{KEYRING_SERVICE_PREFIX}{account_id}"

    def get(self, account_id: str, field: str) -> Optional[str]:
        try:
            return self._keyring.get_password(self._service(account_id), field)
        except Exception:
            # keyring backends can throw on missing keys, locked stores, etc.
            # Treat any failure as "not present" so chained fallback can run.
            return None

    def set(self, account_id: str, field: str, value: str) -> None:
        self._keyring.set_password(self._service(account_id), field, value)
        self._index_add(account_id, field)

    def delete(self, account_id: str, field: str) -> None:
        try:
            self._keyring.delete_password(self._service(account_id), field)
        except Exception:
            pass  # already-deleted or never-present is a non-error
        self._index_remove(account_id, field)

    def list_accounts(self) -> list[tuple[str, list[str]]]:
        idx = self._load_index()
        return [(a, sorted(f)) for a, f in sorted(idx.items())]

    # -- index helpers ---------------------------------------------------

    def _load_index(self) -> dict[str, list[str]]:
        if not INDEX_FILE.exists():
            return {}
        try:
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        # Normalize values to lists
        return {k: sorted(v) for k, v in data.items() if isinstance(v, list)}

    def _save_index(self, idx: dict[str, list[str]]) -> None:
        try:
            INDEX_FILE.write_text(json.dumps(idx, indent=2), encoding="utf-8")
        except OSError:
            pass  # index is best-effort metadata — never block writes

    def _index_add(self, account_id: str, field: str) -> None:
        idx = self._load_index()
        fields = set(idx.get(account_id, []))
        fields.add(field)
        idx[account_id] = sorted(fields)
        self._save_index(idx)

    def _index_remove(self, account_id: str, field: str) -> None:
        idx = self._load_index()
        if account_id in idx:
            fields = [f for f in idx[account_id] if f != field]
            if fields:
                idx[account_id] = fields
            else:
                del idx[account_id]
            self._save_index(idx)


# ---------------------------------------------------------------------------
# ChainedCredentialStore — walks a list of stores on read; writes to first writable
# ---------------------------------------------------------------------------

class ChainedCredentialStore(CredentialStore):
    """Walks ``stores`` on ``get``; writes go to the first writable store.

    Use case: keyring (writable) + env (read-only fallback). Existing users
    with a ``.aamp_credentials`` file keep working; new credentials set via
    ``aamp-set-credential`` go to the keyring; the env fallback is exercised
    only until the user migrates.
    """

    def __init__(self, stores: Iterable[CredentialStore]) -> None:
        self._stores: list[CredentialStore] = list(stores)
        if not self._stores:
            raise ValueError("ChainedCredentialStore requires at least one store")

    @property
    def is_writable(self) -> bool:
        return any(s.is_writable for s in self._stores)

    def get(self, account_id: str, field: str) -> Optional[str]:
        for s in self._stores:
            val = s.get(account_id, field)
            if val is not None:
                return val
        return None

    def set(self, account_id: str, field: str, value: str) -> None:
        for s in self._stores:
            if s.is_writable:
                s.set(account_id, field, value)
                return
        raise RuntimeError("No writable store in chain")

    def delete(self, account_id: str, field: str) -> None:
        # Delete from every writable store (the value may live in more than one).
        for s in self._stores:
            if s.is_writable:
                s.delete(account_id, field)

    def list_accounts(self) -> list[tuple[str, list[str]]]:
        # Union of all stores' inventories.
        merged: dict[str, set[str]] = {}
        for s in self._stores:
            for account_id, fields in s.list_accounts():
                merged.setdefault(account_id, set()).update(fields)
        return [(a, sorted(f)) for a, f in sorted(merged.items())]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

#: Module-level singleton so repeated calls don't re-do the keyring health check.
_CACHED_STORE: Optional[CredentialStore] = None


def get_credential_store(*, refresh: bool = False, audit: bool = True) -> CredentialStore:
    """Return the configured credential store, wrapped with audit logging.

    Backend selection via ``AAMP_CREDENTIAL_BACKEND`` env var:
      - ``"keyring"`` — keyring only (raises if backend health check fails)
      - ``"env"`` — read-only env + ``.aamp_credentials``
      - ``"chained"`` (default) — keyring then env, writes to keyring

    When ``audit=True`` (default), the returned store is wrapped in
    :class:`aamp.audit.AuditingStore` so every credential access is
    recorded to ``~/.aamp_audit.log``. Pass ``audit=False`` for tests
    that want the raw backend.

    Pass ``refresh=True`` to bypass the cache.
    """
    global _CACHED_STORE
    if _CACHED_STORE is not None and not refresh:
        return _CACHED_STORE

    backend = (os.environ.get("AAMP_CREDENTIAL_BACKEND") or "chained").lower()
    raw: CredentialStore
    if backend == "env":
        raw = EnvCredentialStore()
    elif backend == "keyring":
        raw = KeyringCredentialStore()
    elif backend == "chained":
        # Try keyring first; degrade gracefully to env-only if the OS
        # backend isn't usable (e.g. CI environments, locked sessions).
        try:
            keyring_store: CredentialStore = KeyringCredentialStore()
            raw = ChainedCredentialStore([keyring_store, EnvCredentialStore()])
        except RuntimeError:
            raw = EnvCredentialStore()
    else:
        raise ValueError(
            f"Unknown AAMP_CREDENTIAL_BACKEND={backend!r}; "
            "expected one of: keyring, env, chained"
        )

    if audit:
        # Local import to avoid a circular: audit.py imports CredentialStore from here.
        from .audit import AuditingStore
        store: CredentialStore = AuditingStore(raw)
    else:
        store = raw

    _CACHED_STORE = store
    return store
