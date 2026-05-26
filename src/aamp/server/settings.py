"""Settings HTTP surface.

Wraps :mod:`aamp.settings` in a small REST API the web client can use
to power the Settings panel. We intentionally do NOT call the MCP
``list_settings`` / ``set_setting`` tools here — those return markdown
designed for the chat surface, and parsing markdown back into structured
fields is silly when we own the underlying module. Calling
``aamp.settings`` directly gives us typed JSON for free.

Endpoints:

  ``GET  /api/settings``         — list every known setting + current value
  ``GET  /api/settings/{key}``   — read one (mostly useful for re-checking)
  ``PUT  /api/settings/{key}``   — write one. Body: ``{"value": <whatever>}``.
                                   Pass null / empty to reset to default.

Settings are non-secret (see :mod:`aamp.settings` for the rationale).
This router is safe to expose on the same loopback the rest of the
sidecar uses.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .. import settings as _settings


router = APIRouter(prefix="/settings", tags=["settings"])


class SettingView(BaseModel):
    """Wire-shape for one setting row. Matches what the Settings panel
    needs to render an editable form: the key, its current value, the
    default to fall back to, the type the UI should render, plus the
    category + description for grouping and helper-text."""

    key: str
    value: Any
    default: Any
    type: str
    category: str
    description: str


class SettingUpdate(BaseModel):
    """Body of a PUT. ``None`` resets the setting to its default."""

    value: Optional[Any] = None


def _type_name(value: Any) -> str:
    """Best-effort type label for the UI's form-field decision. We
    return primitive-ish names rather than the Python class so the JS
    side has something portable to switch on."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return "json"  # lists, dicts, etc. — render as a free-form textarea


def _view_for(def_: _settings.SettingDef, value: Any) -> SettingView:
    return SettingView(
        key=def_.key,
        value=value,
        default=def_.default,
        # Type is driven by the DEFAULT, not the current value — that
        # way "0" doesn't suddenly downgrade an int field to ambiguous
        # if someone stored a string in keyring by accident.
        type=_type_name(def_.default),
        category=def_.category,
        description=def_.description,
    )


@router.get("", response_model=list[SettingView])
def http_list() -> list[SettingView]:
    """Every recognized setting. Order matches the ``DEFAULTS`` tuple
    so the UI gets a stable layout."""
    return [_view_for(d, v) for d, v in _settings.all_settings()]


@router.get("/{key}", response_model=SettingView)
def http_get(key: str) -> SettingView:
    def_ = _settings.def_for(key)
    if def_ is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown setting key: {key!r}",
        )
    return _view_for(def_, _settings.get_setting(key))


@router.put("/{key}", response_model=SettingView)
def http_put(key: str, body: SettingUpdate) -> SettingView:
    def_ = _settings.def_for(key)
    if def_ is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown setting key: {key!r}",
        )
    try:
        if body.value is None:
            _settings.delete_setting(key)
        else:
            _settings.set_setting(key, body.value)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _view_for(def_, _settings.get_setting(key))
