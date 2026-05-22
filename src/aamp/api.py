"""High-level REST API client for AAM Pro's ``/webapi/v1/*`` surface.

Wraps :class:`aamp.auth.AampAuth` for bearer-token management and offers
typed read + write methods that return :mod:`aamp.api_models` Pydantic
objects. Stable to swap into ``aamp.write`` to replace direct PostgreSQL
inserts — the function signatures intentionally mirror those.

Usage:

    from aamp.api import AampApi
    from aamp.config import load_config

    api = AampApi.from_config(load_config())
    for d in api.list_destinations():
        print(d.id, d.name, d.physical_zone_ids)

The client keeps no persistent state of its own beyond the auth token cache.
Each call is independent. Errors raise :class:`ApiError` with the HTTP
status code and response body excerpt; the auth layer raises
:class:`aamp.auth.AuthError` for credential failures.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx

from .api_models import (
    Color,
    Event,
    LibraryItem,
    LocalDateTime,
    OpeningHours,
    Scheduler,
    Site,
    Source,
    SourceSummary,
    Template,
    TemplateSet,
    VisualProfile,
    Zone,
)
from .auth import AampAuth
from .config import AampConfig


WEBAPI = "/webapi/v1"
DEFAULT_PAGE_SIZE = 2_147_483_647  # SPA uses int max; API treats as "give me everything"


class ApiError(RuntimeError):
    """Raised when an /webapi/v1/* call returns a non-2xx response."""
    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        super().__init__(f"{method} {path} -> {status}: {body[:300]}")
        self.status = status
        self.method = method
        self.path = path
        self.body = body


# ---------------------------------------------------------------------------
# Day-of-week helpers
# ---------------------------------------------------------------------------

DAY_FLAGS = ("onMon", "onTue", "onWed", "onThu", "onFri", "onSat", "onSun", "onHol")
DAY_KEY_BY_NAME = {
    "mon": "onMon", "tue": "onTue", "wed": "onWed", "thu": "onThu",
    "fri": "onFri", "sat": "onSat", "sun": "onSun", "hol": "onHol",
    "monday": "onMon", "tuesday": "onTue", "wednesday": "onWed",
    "thursday": "onThu", "friday": "onFri", "saturday": "onSat",
    "sunday": "onSun", "holiday": "onHol",
}


def days_of_week_to_flags(days: Iterable[str]) -> dict[str, bool]:
    """Map ``['Mon', 'Wed']`` to ``{onMon: True, onTue: False, ...}``."""
    out = {k: False for k in DAY_FLAGS}
    for d in days:
        key = DAY_KEY_BY_NAME.get(d.strip().lower())
        if not key:
            raise ValueError(f"Unknown day name: {d!r}")
        out[key] = True
    return out


def _iso_date(d: date | str | None) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def _hhmm(t: tuple[int, int] | str) -> str:
    if isinstance(t, str):
        return t
    h, m = t
    return f"{h:02d}:{m:02d}"


def _normalize_time_entry(t: Any) -> dict[str, Optional[str]]:
    """Coerce various input shapes to ``{"startTime": "HH:MM", "endTime": "HH:MM"|None}``.

    Accepted inputs:
      - ``(h, m)``                 → start only, no end (instantaneous trigger; bell-style)
      - ``"HH:MM"``                → same as above
      - ``(start_str, end_str)``   → 2-tuple of strings, a play window (music-style)
      - ``{"startTime": ..., "endTime": ...}``  → passed through
    """
    if isinstance(t, dict):
        return {"startTime": t.get("startTime") or t.get("start_time"),
                "endTime": t.get("endTime") or t.get("end_time")}
    if isinstance(t, str):
        return {"startTime": t, "endTime": None}
    if isinstance(t, (tuple, list)):
        if len(t) >= 2 and all(isinstance(x, str) for x in t[:2]):
            # ("HH:MM", "HH:MM") — explicit window
            return {"startTime": t[0], "endTime": t[1]}
        if len(t) == 2 and all(isinstance(x, int) for x in t):
            # (h, m) — instantaneous
            return {"startTime": _hhmm(t), "endTime": None}
    raise ValueError(f"Cannot interpret time entry: {t!r}")


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class AampApi:
    """Typed wrapper around ``/webapi/v1/*``."""

    def __init__(self, config: AampConfig, auth: Optional[AampAuth] = None,
                 http: Optional[httpx.Client] = None) -> None:
        self._config = config
        # Single shared httpx.Client across auth + API calls so the session
        # cookies set during the OAuth login flow on /oauth/v1/* persist into
        # subsequent /webapi/v1/* writes (Spring Boot's auth filter requires
        # them in addition to the Bearer token).
        self._http = http or httpx.Client(
            base_url=config.host,
            verify=config.verify_tls,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        self._auth = auth or AampAuth(config, http=self._http)

    @classmethod
    def from_config(cls, config: AampConfig) -> "AampApi":
        """Construct sharing one httpx.Client between auth and API."""
        return cls(config)

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
        try:
            self._auth.close()
        except Exception:
            pass

    def __enter__(self) -> "AampApi":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low-level dispatch ----------------------------------------------

    # AAM Pro's Spring Boot backend uses double-submit-cookie CSRF protection:
    # server sets a ``csrf-token`` cookie during login; clients must echo it
    # back as an ``X-CSRF-TOKEN`` header on every unsafe-method request.
    UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def _headers_for(self, method: str) -> dict[str, str]:
        h = dict(self._auth.http_headers())
        if method.upper() in self.UNSAFE_METHODS:
            token = self._http.cookies.get("csrf-token")
            if token:
                h["X-CSRF-TOKEN"] = token
        return h

    def _request(self, method: str, path: str, *, params: Optional[dict] = None,
                 json: Any = None) -> httpx.Response:
        full_path = path if path.startswith("/") else f"/{path}"
        r = self._http.request(method, full_path, headers=self._headers_for(method),
                               params=params, json=json)
        if r.status_code == 401:
            # Token expired between cache check and use; force refresh once.
            self._auth._tokens.expires_at = 0
            r = self._http.request(method, full_path, headers=self._headers_for(method),
                                   params=params, json=json)
        if r.status_code >= 400:
            raise ApiError(r.status_code, method, full_path, r.text or "")
        return r

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params).json()

    def _post(self, path: str, json: Any = None, params: Optional[dict] = None) -> Any:
        r = self._request("POST", path, json=json, params=params)
        if not r.text:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def _put(self, path: str, json: Any = None) -> Any:
        r = self._request("PUT", path, json=json)
        if not r.text:
            return None
        return r.json()

    def _patch(self, path: str, json: Any = None, params: Optional[dict] = None) -> Any:
        # AAM Pro's PATCH endpoints require ``application/merge-patch+json``
        # (RFC 7396), not the generic ``application/json``. We override the
        # Content-Type header just for this call.
        full_path = path if path.startswith("/") else f"/{path}"
        headers = self._headers_for("PATCH")
        headers["Content-Type"] = "application/merge-patch+json"
        r = self._http.request("PATCH", full_path, headers=headers, json=json, params=params)
        if r.status_code == 401:
            self._auth._tokens.expires_at = 0
            headers = self._headers_for("PATCH")
            headers["Content-Type"] = "application/merge-patch+json"
            r = self._http.request("PATCH", full_path, headers=headers, json=json, params=params)
        if r.status_code >= 400:
            raise ApiError(r.status_code, "PATCH", full_path, r.text or "")
        if not r.text:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def _delete(self, path: str) -> None:
        self._request("DELETE", path)

    def _post_multipart(
        self,
        path: str,
        *,
        files: Optional[dict[str, tuple]] = None,
        fields: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        """Send a multipart POST with the bearer + CSRF headers stripped of
        Content-Type (so httpx can set the multipart boundary).

        ``files``: ``{field_name: (filename, bytes, content_type)}`` for file fields.
        ``fields``: ``{field_name: text_value}`` for plain text fields.

        Note: httpx sends text-only fields as additional multipart parts when
        passed via ``data={}`` alongside ``files={}``. For text-only multiparts
        (e.g. ``createDirectory`` with just ``libPath``) we still pass a
        ``files`` dict using ``(None, value)`` so httpx forces multipart encoding.
        """
        full_path = path if path.startswith("/") else f"/{path}"
        headers = {k: v for k, v in self._headers_for("POST").items() if k.lower() != "content-type"}
        kwargs: dict[str, Any] = {}
        if files:
            kwargs["files"] = files
        if fields:
            kwargs["data"] = fields
        r = self._http.request("POST", full_path, headers=headers, **kwargs)
        if r.status_code == 401:
            self._auth._tokens.expires_at = 0
            headers = {k: v for k, v in self._headers_for("POST").items() if k.lower() != "content-type"}
            r = self._http.request("POST", full_path, headers=headers, **kwargs)
        if r.status_code >= 400:
            raise ApiError(r.status_code, "POST", full_path, r.text or "")
        return r

    @staticmethod
    def _data_envelope(payload: Any) -> Any:
        """Some endpoints return ``{"data": ...}``; unwrap if present."""
        if isinstance(payload, dict) and set(payload.keys()) >= {"data"} and len(payload) <= 2:
            return payload["data"]
        return payload

    # ====================================================================
    # READ
    # ====================================================================

    def list_sites(self) -> list[Site]:
        data = self._data_envelope(self._get(f"{WEBAPI}/sites"))
        return [Site.model_validate(s) for s in data or []]

    def get_account(self) -> dict[str, Any]:
        return self._get(f"{WEBAPI}/account")

    def list_zones(self, kind: Optional[str] = None, size: int = DEFAULT_PAGE_SIZE) -> list[Zone]:
        params: dict[str, Any] = {"size": size}
        if kind:
            params["type"] = kind
        data = self._data_envelope(self._get(f"{WEBAPI}/zones", params=params))
        return [Zone.model_validate(z) for z in data or []]

    def list_destinations(self, size: int = DEFAULT_PAGE_SIZE) -> list[Zone]:
        return self.list_zones("CONTENT", size=size)

    def list_physical_zones(self, size: int = DEFAULT_PAGE_SIZE) -> list[Zone]:
        return self.list_zones("PHYSICAL", size=size)

    def get_zone(self, zone_id: int, kind: Optional[str] = None) -> Zone:
        params = {"type": kind} if kind else None
        data = self._data_envelope(self._get(f"{WEBAPI}/zones/{zone_id}", params=params))
        return Zone.model_validate(data)

    def list_zone_sources(self, zone_id: int, size: int = DEFAULT_PAGE_SIZE) -> list[dict[str, Any]]:
        """Return the source rows assigned to a destination. Returns raw dicts
        because the shape is heavily denormalized (includes a nested scheduler list)."""
        data = self._data_envelope(self._get(f"{WEBAPI}/zones/{zone_id}/sources", params={"size": size}))
        return data or []

    def list_templates(self) -> list[Template]:
        raw = self._get(f"{WEBAPI}/templates")
        # Most "list" endpoints wrap in {"data": [...]}, but /templates returns a bare list.
        if isinstance(raw, dict) and "data" in raw:
            raw = raw["data"]
        return [Template.model_validate(t) for t in raw or []]

    def get_template(self, template_id: int) -> Template:
        raw = self._get(f"{WEBAPI}/templates/{template_id}")
        return Template.model_validate(raw)

    def list_sources(self, *, source_type: Optional[str] = None, category: Optional[str] = None,
                     size: int = DEFAULT_PAGE_SIZE) -> list[Source]:
        params: dict[str, Any] = {"size": size}
        if source_type:
            params["sourceType"] = source_type
        if category:
            params["category"] = category
        data = self._data_envelope(self._get(f"{WEBAPI}/sources", params=params))
        return [Source.model_validate(s) for s in data or []]

    def get_scheduler(self, scheduler_id: int) -> Scheduler:
        raw = self._data_envelope(self._get(f"{WEBAPI}/schedulers/{scheduler_id}"))
        return Scheduler.model_validate(raw)

    def list_events(self, *, zone_id: int, from_dt: datetime, to_dt: datetime) -> list[Event]:
        params = {
            "zoneId": zone_id,
            "from": from_dt.strftime("%Y-%m-%dT%H:%M"),
            "to": to_dt.strftime("%Y-%m-%dT%H:%M"),
        }
        data = self._data_envelope(self._get(f"{WEBAPI}/events", params=params))
        return [Event.model_validate(e) for e in data or []]

    def get_agenda(self, on_date: date | str | None = None) -> list[dict[str, Any]]:
        params = {"date": _iso_date(on_date) or date.today().isoformat()}
        raw = self._get(f"{WEBAPI}/agenda", params=params)
        return raw if isinstance(raw, list) else (raw.get("data") or [])

    def get_opening_hours(self) -> OpeningHours:
        raw = self._data_envelope(self._get(f"{WEBAPI}/openingHours/site"))
        return OpeningHours.model_validate(raw)

    def list_libraries(self) -> list[dict[str, Any]]:
        raw = self._data_envelope(self._get(f"{WEBAPI}/libraries"))
        return raw or []

    def list_library_items(self, library_id: int, *, path: str = "/",
                            size: int = DEFAULT_PAGE_SIZE) -> list[LibraryItem]:
        raw = self._get(f"{WEBAPI}/libraries/{library_id}/items", params={"path": path, "size": size})
        data = (raw or {}).get("data", [])
        return [LibraryItem.model_validate(i) for i in data]

    # -- library writes (verified via SPA traffic capture 2026-05-21 v4) --------

    # Convention: library id 1 = music, library id 3 = announcement (this install).
    # Use ``list_libraries()`` to confirm on a different install.
    DEFAULT_MUSIC_LIBRARY_ID = 1
    DEFAULT_ANNOUNCEMENT_LIBRARY_ID = 3

    def upload_file_to_library(
        self,
        library_id: int,
        file_path: str | Path,
        *,
        target_filename: Optional[str] = None,
        lib_path: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> None:
        """``POST /libraries/{id}/uploadFiles`` — upload one audio file.

        Multipart form-data with:
          - ``files`` field (note: plural — server rejects ``file`` with 400)
            carrying the file bytes + a flat filename (no slashes).
          - ``libPath`` field (optional) naming an existing subdirectory.

        Use ``create_library_directory`` first if the target subdirectory
        doesn't exist. The server returns 204 on success and 422 with a
        structured error envelope on failure (e.g., ``MEDIA_ERROR`` for an
        unsupported format).
        """
        local_path = Path(file_path)
        if not local_path.exists():
            raise FileNotFoundError(f"file not found: {local_path}")
        if mime_type is None:
            import mimetypes
            mime_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        # The server rejects "/" in the filename — directory placement is
        # specified via the separate ``libPath`` form field.
        filename = target_filename or local_path.name
        if "/" in filename or "\\" in filename:
            raise ValueError(
                f"target_filename cannot contain path separators ({filename!r}); "
                f"use lib_path= for the subdirectory and a flat filename."
            )
        with local_path.open("rb") as f:
            files: dict[str, Any] = {"files": (filename, f.read(), mime_type)}
            if lib_path:
                files["libPath"] = (None, lib_path)
        self._post_multipart(f"{WEBAPI}/libraries/{library_id}/uploadFiles", files=files)

    def create_library_directory(self, library_id: int, lib_path: str) -> None:
        """``POST /libraries/{id}/createDirectory`` — create a subdirectory inside a library.

        Multipart form with one text field ``libPath``. Pass forward-slashes for nested
        directories (e.g. ``"bells/elementary"``).
        """
        files = {"libPath": (None, lib_path)}
        self._post_multipart(f"{WEBAPI}/libraries/{library_id}/createDirectory", files=files)

    # -- sources / playlists ----------------------------------------------

    def create_playlist_source(
        self,
        *,
        name: str,
        category: str = "MUSIC",
        repeat: bool = True,
        shuffle: bool = False,
    ) -> dict[str, Any]:
        """``POST /sources`` — create an empty PLAYLIST source.

        Returns the new source's full JSON (so the caller has the id to add items).
        Use :meth:`add_playlist_items` to populate it.
        """
        body: dict[str, Any] = {
            "name": name,
            "sourceType": "PLAYLIST",
            "category": category.upper(),
            "playlist": {"repeat": repeat, "shuffle": shuffle},
        }
        raw = self._data_envelope(self._post(f"{WEBAPI}/sources", json=body))
        return raw

    def add_playlist_items(
        self,
        source_id: int,
        library_item_ids: list[int],
    ) -> list[dict[str, Any]]:
        """``POST /sources/{id}/playlistBatchItems`` — append library files to a PLAYLIST source.

        Returns the new ``playlistItems`` records (each has a server-assigned ``id``
        plus ``libraryItemId``).
        """
        body = {"playlistItems": [{"libraryItemId": lid} for lid in library_item_ids]}
        raw = self._data_envelope(self._post(f"{WEBAPI}/sources/{source_id}/playlistBatchItems", json=body))
        return (raw or {}).get("playlistItems", [])

    def list_colors(self) -> list[Color]:
        data = self._data_envelope(self._get(f"{WEBAPI}/colors"))
        return [Color.model_validate(c) for c in data or []]

    def list_visual_profiles(self) -> list[VisualProfile]:
        raw = self._get(f"{WEBAPI}/visualProfiles")
        if isinstance(raw, dict) and "data" in raw:
            raw = raw["data"]
        return [VisualProfile.model_validate(v) for v in raw or []]

    def get_local_date_time(self) -> LocalDateTime:
        raw = self._get(f"{WEBAPI}/globalSettings/localDateTime")
        return LocalDateTime.model_validate(raw)

    def get_site_name(self) -> str:
        raw = self._data_envelope(self._get(f"{WEBAPI}/globalSettings/siteName"))
        return raw.get("siteName", "")

    # ====================================================================
    # WRITE
    # ====================================================================

    # -- destinations ----------------------------------------------------

    def create_destination(self, name: str) -> Zone:
        """``POST /zones?type=CONTENT`` — create a content-routing zone."""
        raw = self._data_envelope(self._post(f"{WEBAPI}/zones", json={"name": name},
                                              params={"type": "CONTENT"}))
        return Zone.model_validate(raw)

    def create_physical_zone(self, name: str, parent_zone_id: Optional[int] = None) -> Zone:
        """``POST /zones?type=PHYSICAL`` — create a physical zone, optionally under a parent."""
        body: dict[str, Any] = {"name": name}
        if parent_zone_id is not None:
            # Captured shape uncertain; try common patterns. Server tolerates extra fields.
            body["parentZoneId"] = parent_zone_id
        raw = self._data_envelope(self._post(f"{WEBAPI}/zones", json=body,
                                              params={"type": "PHYSICAL"}))
        return Zone.model_validate(raw)

    def delete_zone(self, zone_id: int) -> None:
        """``DELETE /zones/{id}`` — works for both physical zones and destinations.

        The server prevents deletion if the zone is referenced by active schedulers
        or template bindings; an ``ApiError`` with a 4xx status surfaces that."""
        self._delete(f"{WEBAPI}/zones/{zone_id}")

    def set_destination_physical_zones(self, destination_id: int, physical_zone_ids: list[int]) -> None:
        """``PATCH /zones/{id}?type=CONTENT`` — bind a destination's member physical zones.

        Body shape: ``{"id": <destination_id>, "physicalZoneIds": [...]}``.
        Returns 204 No Content. This **replaces** the current binding — pass all
        physical zones you want, not just additions. The ``?type=CONTENT`` query
        param is required (server returns 400 without it).
        """
        body = {"id": destination_id, "physicalZoneIds": list(physical_zone_ids)}
        self._patch(f"{WEBAPI}/zones/{destination_id}", json=body, params={"type": "CONTENT"})

    def rename_destination(self, destination_id: int, name: str) -> None:
        """``PATCH /zones/{id}?type=CONTENT`` — rename a destination.

        Empirically, the SPA sends only the fields it changed; merge-patch+json
        means unspecified fields are left alone.
        """
        body = {"id": destination_id, "name": name}
        self._patch(f"{WEBAPI}/zones/{destination_id}", json=body, params={"type": "CONTENT"})

    def search_library(
        self,
        library_id: int,
        *,
        pattern: str = "",
        library_path: str = "/",
        ignore_case: bool = True,
        max_depth: int = 10,
    ) -> list[LibraryItem]:
        """``POST /libraries/{id}/search`` — search a music/announcement library.

        Note: response ``duration`` is **seconds** here (e.g. 2.003), whereas the
        ``GET /events`` response gives durations in **milliseconds** (2003.0).
        Watch for this when comparing payloads across endpoints.
        """
        body = {
            "libraryPath": library_path,
            "pattern": pattern,
            "ignoreCase": ignore_case,
            "maxDepth": max_depth,
        }
        raw = self._post(f"{WEBAPI}/libraries/{library_id}/search", json=body)
        data = (raw or {}).get("data", [])
        return [LibraryItem.model_validate(i) for i in data]

    # -- templates -------------------------------------------------------

    def create_template(self, name: str, category: str) -> Template:
        """``POST /templates`` — create an empty template of the given category."""
        cat = category.upper()
        raw = self._post(f"{WEBAPI}/templates", json={"name": name, "type": cat})
        return Template.model_validate(raw)

    def delete_template(self, template_id: int) -> None:
        self._delete(f"{WEBAPI}/templates/{template_id}")

    def create_template_set(
        self,
        template_id: int,
        *,
        schedulers: list[dict[str, Any]] | None = None,
        sources: list[dict[str, Any]] | None = None,
        single_files: list[LibraryItem | dict[str, Any]] | None = None,
        reschedule: bool = False,
        keep_exceptions: bool = True,
    ) -> TemplateSet:
        """``POST /templateSets`` — populate a template with content + a within-day scheduler."""
        body: dict[str, Any] = {
            "templateId": str(template_id),
            "schedulers": schedulers or [],
            "sources": sources,
            "singleFiles": [
                f.to_dict() if isinstance(f, LibraryItem) else f
                for f in (single_files or [])
            ],
        }
        raw = self._post(
            f"{WEBAPI}/templateSets",
            json=body,
            params={"reschedule": str(reschedule).lower(),
                    "keepExceptions": str(keep_exceptions).lower()},
        )
        return TemplateSet.model_validate(raw)

    # -- template <-> destination binding -------------------------------

    def schedule_template_on_zone(
        self,
        template_id: int,
        zone_id: int,
        *,
        days_of_week: list[str],
        start_on: date | str,
        end_on: date | str | None = None,
        end_on_type: Optional[str] = None,
        repeat_type: str = "WEEK",
        week_every: int = 1,
        color_id: int = 1,
        daily_recurrences_type: str = "DAYS",
        max_occurencies: Optional[int] = None,
    ) -> None:
        """``POST /templates/{tmplId}/scheduleOn/{zoneId}`` — apply a template to a destination
        with a recurrence interval. This replaces our DB-side multi-row template-bind ceremony."""
        if end_on_type is None:
            end_on_type = "END_BY_DATE" if end_on else "NO_END"
        body: dict[str, Any] = {
            "colorId": color_id,
            "dailyRecurrencesType": daily_recurrences_type,
            "startOn": _iso_date(start_on),
            "endOn": _iso_date(end_on),
            "endOnType": end_on_type,
            "repeatType": repeat_type,
            "weekEvery": week_every,
            "maxOccurencies": max_occurencies,
            "dayEvery": None,
            "dayInMonth": None,
            "dayInWeek": None,
            "month": None,
            "monthEvery": None,
            "monthlyRecurrenceType": None,
            "monthlyWeekInMonth": None,
            "yearlyRecurrenceType": None,
            "yearlyWeekInMonth": None,
            "yearEvery": None,
            **days_of_week_to_flags(days_of_week),
        }
        self._post(f"{WEBAPI}/templates/{template_id}/scheduleOn/{zone_id}", json=body)

    def unschedule_template_on_zone(
        self,
        template_id: int,
        zone_id: int,
        *,
        interval: Optional[dict[str, Any]] = None,
    ) -> None:
        """``POST /templates/{tmplId}/unscheduleOn/{zoneId}`` — remove a template binding.

        Captured SPA traffic 2026-05-21 sends body ``null`` and the server returns
        204 No Content. The earlier captured POST (in the larger traffic log) sent
        an interval block but the latest capture suggests null also works. We pass
        through whatever the caller provides; default is null.
        """
        self._post(f"{WEBAPI}/templates/{template_id}/unscheduleOn/{zone_id}", json=interval)

    def create_day_exception(
        self,
        template_id: int,
        zone_id: int,
        exception_date: date | str,
    ) -> None:
        """``POST /templates/{tmplId}/createDayException/{zoneId}?exceptionDate=YYYY-MM-DD`` —
        cancel a template application on one specific day."""
        self._post(
            f"{WEBAPI}/templates/{template_id}/createDayException/{zone_id}",
            json=None,
            params={"exceptionDate": _iso_date(exception_date)},
        )

    # -- schedulers (free-standing, non-template) -----------------------

    def create_scheduler(
        self,
        *,
        name: str,
        category: str,
        zone_id: int,
        sources: list[dict[str, Any]],
        days_of_week: list[str] | None = None,
        specific_times: list[Any] | None = None,
        relative_times: list[dict[str, Any]] | None = None,
        start_on: date | str,
        end_on: date | str | None = None,
        repeat_type: str = "WEEK",
        end_on_type: Optional[str] = None,
        autostart: bool = True,
        queueable: bool = True,
        color_id: int = 1,
        time_scheduling_type: str = "SPECIFIC_TIME",
        daily_recurrences_type: str = "DAYS",
        day_every: Optional[int] = None,
        week_every: Optional[int] = None,
        visual_profile_enabled: str = "DEFAULT",
        visual_profile_id: Optional[int] = None,
        custom_text: Optional[str] = None,
    ) -> Scheduler:
        """``POST /schedulers`` — create a non-template scheduled event.

        Handles three recurrence patterns observed in captured SPA traffic:

          - **WEEK** (default): bell-style. ``days_of_week`` sets onMon/onTue/...,
            and ``week_every`` defaults to 1. ``specific_times`` are usually
            instantaneous triggers (``endTime: null``).
          - **DAY**: music-style continuous play. ``day_every`` defaults to 1.
            ``specific_times`` are play *windows* — ``("09:00", "17:00")``.
          - **NONE**: one-off event on ``start_on``.

        ``specific_times`` accepts any of: ``(h, m)``, ``"HH:MM"``, ``(start, end)``
        string tuples, or ``{"startTime": ..., "endTime": ...}`` dicts. See
        :func:`_normalize_time_entry`.
        """
        if end_on_type is None:
            end_on_type = "END_BY_DATE" if end_on else "NO_END"
        flags = days_of_week_to_flags(days_of_week or [])
        normalized_times = [_normalize_time_entry(t) for t in (specific_times or [])]

        # Default recurrence-specific multipliers if the caller didn't pass any.
        if day_every is None and repeat_type == "DAY":
            day_every = 1
        if week_every is None and repeat_type == "WEEK":
            week_every = 1

        body: dict[str, Any] = {
            "autostart": autostart,
            "queueable": queueable,
            "specificTimes": normalized_times,
            "relativeTimes": relative_times or [],
            "timeSchedulingType": time_scheduling_type,
            "endOn": _iso_date(end_on),
            "endOnType": end_on_type,
            "maxOccurencies": None,
            "dayEvery": day_every,
            "dayInMonth": None,
            "dayInWeek": None,
            "weekEvery": week_every,
            "monthlyRecurrenceType": None,
            "monthEvery": None,
            "monthlyWeekInMonth": None,
            "yearlyRecurrenceType": None,
            "yearlyWeekInMonth": None,
            "yearEvery": None,
            "month": None,
            "colorId": color_id,
            "dailyRecurrencesType": daily_recurrences_type,
            "name": name,
            "startOn": _iso_date(start_on),
            "category": category.upper(),
            "repeatType": repeat_type,
            "customText": custom_text,
            "visualProfileEnabled": visual_profile_enabled,
            "visualProfileId": visual_profile_id,
            "zoneId": zone_id,
            "sources": sources,
            **flags,
        }
        raw = self._data_envelope(self._post(f"{WEBAPI}/schedulers", json=body))
        return Scheduler.model_validate(raw)

    def update_scheduler(self, scheduler_id: int, body: dict[str, Any]) -> None:
        """``PUT /schedulers/{id}`` — full replace. Caller is responsible for passing
        a complete body (read the current scheduler first, mutate, then send)."""
        self._put(f"{WEBAPI}/schedulers/{scheduler_id}", json=body)

    def delete_scheduler(self, scheduler_id: int) -> None:
        """``DELETE /schedulers/{id}`` — remove a scheduler and its events/calendar rows."""
        self._delete(f"{WEBAPI}/schedulers/{scheduler_id}")

    # -- events (materialized single occurrences) -----------------------

    def update_event(self, event_id: int, *, name: Optional[str] = None,
                     from_dt: Optional[str | datetime] = None,
                     to_dt: Optional[str | datetime] = None,
                     color_id: int = 1) -> None:
        """``PATCH /events/{eventId}`` — move/rename a single materialized occurrence.

        Used for one-off shifts ("move next Wednesday's 4pm bell to 3:30pm")."""
        def _iso(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v.strftime("%Y-%m-%dT%H:%M")
            return v
        body: dict[str, Any] = {"colorId": color_id}
        if name is not None:
            body["name"] = name
        body["from"] = _iso(from_dt)
        body["to"] = _iso(to_dt)
        self._patch(f"{WEBAPI}/events/{event_id}", json=body)
