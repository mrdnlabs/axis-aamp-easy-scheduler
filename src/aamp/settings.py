"""User-tunable runtime settings for ChAAMP.

A small key→value store backed by ``~/.aamp_settings.json``. Used for
**non-secret** configuration the user might want to tune — history trim
length, default discovery timeouts, feature flags, etc. Secrets stay in
the credential store (:mod:`aamp.credentials`); operational config not
worth a CLI flag lives here.

Why a JSON file and not the credential store? Two reasons:

1. These values aren't secret — they shouldn't take up keyring slots.
2. They're user-tunable from the web UI; the store needs to be readable
   without a TTY/password.

The schema is small + flat. The default value for every setting lives
in :data:`DEFAULTS`. Adding a new setting is a 3-step change:

1. Add a row to :data:`DEFAULTS`.
2. Read it in the calling code via ``get_setting("key")``.
3. Document it in ``docs/credential_handling.md`` (or a future
   ``docs/settings.md``).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SettingDef:
    """Canonical declaration of one tunable setting."""
    key: str
    default: Any
    description: str
    category: str = "general"


#: Every setting the project recognizes. Adding a new tunable knob is a
#: one-line addition here plus a ``get_setting`` call where it's read.
DEFAULTS: tuple[SettingDef, ...] = (
    SettingDef(
        key="max_history_turns",
        default=50,
        description=(
            "Maximum number of prior message turns sent to the LLM on each "
            "request. Older turns are dropped (oldest first). 0 = unbounded "
            "(send everything; recommended off for production)."
        ),
        category="chat",
    ),
    SettingDef(
        key="default_discovery_timeout_seconds",
        default=5.0,
        description=(
            "How long the mDNS discovery method waits for responses by default. "
            "Bump up for slow networks or VLANs that need extra time to propagate."
        ),
        category="discovery",
    ),
    SettingDef(
        key="capture_token_ttl_seconds",
        default=600,
        description=(
            "Lifetime of a credential-capture session token in seconds. After "
            "this, the modal must mint a fresh token. Default 600 (10 min)."
        ),
        category="security",
    ),
    SettingDef(
        key="capture_rate_limit_per_minute",
        default=20,
        description=(
            "Maximum capture-token mints per source per minute. Caps a confused "
            "client from hammering the endpoint. Default 20."
        ),
        category="security",
    ),
)


def _default_for(key: str) -> Optional[Any]:
    for d in DEFAULTS:
        if d.key == key:
            return d.default
    return None


def def_for(key: str) -> Optional[SettingDef]:
    for d in DEFAULTS:
        if d.key == key:
            return d
    return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

SETTINGS_PATH = Path.home() / ".aamp_settings.json"
_LOCK = threading.Lock()


def _load_raw() -> dict[str, Any]:
    """Read the on-disk dict. Missing or malformed → empty."""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2, sort_keys=True),
                                  encoding="utf-8")
    except OSError:
        # Settings are non-critical — failures are logged elsewhere if needed.
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_setting(key: str) -> Any:
    """Get a setting value. Returns the stored value, falling back to the
    declared default. Returns ``None`` if the key is unknown."""
    if def_for(key) is None:
        return None
    with _LOCK:
        raw = _load_raw()
    if key in raw:
        return raw[key]
    return _default_for(key)


def set_setting(key: str, value: Any) -> None:
    """Persist a setting value. Raises ``KeyError`` if the key isn't known.

    Validates against the declared default's type — same type, or
    something coercible. Strings auto-convert to int/float/bool where
    the default is one of those (handy when called from MCP where every
    arg is a string).
    """
    d = def_for(key)
    if d is None:
        raise KeyError(f"Unknown setting: {key!r}. Known keys: {[s.key for s in DEFAULTS]}")
    coerced = _coerce(value, d.default)
    with _LOCK:
        raw = _load_raw()
        raw[key] = coerced
        _save_raw(raw)


def delete_setting(key: str) -> None:
    """Reset a setting to its default by removing it from the on-disk dict."""
    with _LOCK:
        raw = _load_raw()
        if key in raw:
            del raw[key]
            _save_raw(raw)


def all_settings() -> list[tuple[SettingDef, Any]]:
    """Return ``[(definition, current_value), ...]`` for every known setting."""
    with _LOCK:
        raw = _load_raw()
    return [(d, raw.get(d.key, d.default)) for d in DEFAULTS]


def _coerce(value: Any, default: Any) -> Any:
    """Coerce ``value`` to the type of ``default`` when possible."""
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        if isinstance(value, str):
            return int(value.strip())
        return int(value)
    if isinstance(default, float):
        if isinstance(value, str):
            return float(value.strip())
        return float(value)
    return value
