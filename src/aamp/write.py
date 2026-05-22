"""Write-side operations for AAM Pro — REST API edition.

This module replaces the original direct-PostgreSQL writes (preserved in
:mod:`aamp.write_db` for reference) with calls into :class:`aamp.api.AampApi`.
Each public function takes an ``AampApi`` instance instead of a psycopg
connection — that's the only signature change.

Going through the REST API gives us:
- Server-side validation (`@SchedulerExists`, `@ZoneExists`, etc.)
- Automatic materialization of `aam_prop` / `aam_prop_category` / `aam_prop_source` / `db_itf_scheduler_calendar` rows
- Convenience endpoints (``scheduleOn``, ``unscheduleOn``, ``createDayException``) that collapse what used to be multi-row ceremonies into one HTTP call
- A path that survives AAM Pro upgrades (assuming Axis preserves the SPA-facing endpoints across patches)

Stability tier markings from the DB-side module are obsolete — every
endpoint here was verified live against AAM Pro 5.1.34 in the captured
SPA traffic plus our own probe (see ``logs/api_probe_*.md``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from .api import AampApi
from .api_models import LibraryItem, Scheduler, Template, Zone


# ---------------------------------------------------------------------------
# Physical zones & destinations
# ---------------------------------------------------------------------------

def create_physical_zone(
    api: AampApi,
    *,
    site_id: int,  # accepted for backward-compat; ignored — API infers site
    name: str,
    parent_zone_id: Optional[int] = None,
) -> int:
    """Create a physical zone. Returns its new id."""
    z = api.create_physical_zone(name=name, parent_zone_id=parent_zone_id)
    return z.id


def create_destination(
    api: AampApi,
    *,
    site_id: int,  # accepted for backward-compat; ignored — API infers site
    name: str,
    physical_zone_ids: Iterable[int] = (),
) -> int:
    """Create a destination (content-routing zone) and bind its physical zones.

    Implementation: ``POST /zones?type=CONTENT`` creates the empty content zone;
    if ``physical_zone_ids`` is non-empty we follow up with a
    ``PATCH /zones/{id}?type=CONTENT`` to bind them. Captured shape is just
    ``{"id": <new_id>, "physicalZoneIds": [...]}``.
    """
    z = api.create_destination(name=name)
    pz = list(physical_zone_ids)
    if pz:
        api.set_destination_physical_zones(z.id, pz)
    return z.id


def set_destination_physical_zones(
    api: AampApi,
    destination_id: int,
    physical_zone_ids: Iterable[int],
) -> None:
    """Replace the set of physical zones bound to a destination."""
    api.set_destination_physical_zones(destination_id, list(physical_zone_ids))


def rename_destination(api: AampApi, destination_id: int, new_name: str) -> None:
    """Rename a destination."""
    api.rename_destination(destination_id, new_name)


def delete_destination(api: AampApi, destination_id: int) -> None:
    api.delete_zone(destination_id)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def create_template(
    api: AampApi,
    *,
    site_id: int,  # backward-compat; ignored
    name: str,
    category: str,  # 'music' | 'announcement' | 'paging'
    source_ids: Iterable[int] = (),  # backward-compat; ignored — populate via create_template_set
) -> int:
    """Create an empty template. Add content via :func:`add_template_content`."""
    t = api.create_template(name=name, category=category)
    return t.id


def delete_template(api: AampApi, template_id: int) -> None:
    api.delete_template(template_id)


def add_template_content(
    api: AampApi,
    *,
    template_id: int,
    files: list[dict],  # list of LibraryItem-shape dicts (id, libraryId, path, ...)
    scheduler_name: str,
    specific_times: list[str | tuple[int, int]],
    autostart: bool = True,
    queueable: bool = True,
) -> int:
    """Populate a template with content + a within-day scheduler.

    ``files`` should be ``LibraryItem``-shaped dicts as returned by
    :meth:`AampApi.list_library_items`. ``specific_times`` are "HH:MM" strings
    or (h, m) tuples — these define the time-of-day pattern that the
    application interval (``schedule_template_on_destination``) repeats over.

    Returns the new ``templateSet`` id.
    """
    items = [LibraryItem.model_validate(f) for f in files]
    scheduler_block = {
        "name": scheduler_name,
        "specificTimes": [
            {"startTime": (t if isinstance(t, str) else f"{t[0]:02d}:{t[1]:02d}"), "endTime": None}
            for t in specific_times
        ],
        "relativeTimes": [],
        "timeSchedulingType": "SPECIFIC_TIME",
        "autostart": "true" if autostart else "false",  # captured POST used string here
        "queueable": queueable,
        "customText": None,
        "visualProfileEnabled": "DEFAULT",
        "visualProfileId": None,
    }
    ts = api.create_template_set(
        template_id=template_id,
        schedulers=[scheduler_block],
        single_files=items,
        reschedule=False,
        keep_exceptions=True,
    )
    return ts.id


# ---------------------------------------------------------------------------
# Template <-> destination binding (applying a template on a schedule)
# ---------------------------------------------------------------------------

def schedule_template_on_destination(
    api: AampApi,
    *,
    template_id: int,
    destination_id: int,
    days_of_week: Iterable[str],
    start_date: date,
    end_date: Optional[date] = None,
    week_every: int = 1,
    color_id: int = 1,
) -> None:
    """Apply a template to a destination with a recurrence interval.

    Replaces the entire ``db_itf_schedulers`` + ``aam_sched_event`` +
    ``aam_tmpl_bind`` ceremony from the DB-side write layer with one
    server-side call.
    """
    api.schedule_template_on_zone(
        template_id=template_id,
        zone_id=destination_id,
        days_of_week=list(days_of_week),
        start_on=start_date,
        end_on=end_date,
        week_every=week_every,
        color_id=color_id,
    )


def unschedule_template_on_destination(
    api: AampApi,
    *,
    template_id: int,
    destination_id: int,
    interval: dict,
) -> None:
    """Remove a previously-applied template binding. ``interval`` matches the
    binding's recurrence-interval block as exposed in
    ``Template.used_in_zones[].interval`` — copy it directly from the read side."""
    api.unschedule_template_on_zone(
        template_id=template_id, zone_id=destination_id, interval=interval
    )


def create_day_exception(
    api: AampApi,
    *,
    template_id: int,
    destination_id: int,
    exception_date: date,
) -> None:
    """Cancel a template application for a single calendar day on one destination."""
    api.create_day_exception(
        template_id=template_id,
        zone_id=destination_id,
        exception_date=exception_date,
    )


# ---------------------------------------------------------------------------
# Free-standing (non-template) scheduled events
# ---------------------------------------------------------------------------

def create_event(
    api: AampApi,
    *,
    name: str,
    destination_id: int,
    source_id: int,  # backward-compat — caller should now provide ``sources`` dicts
    days_of_week: Iterable[str],
    times: Iterable[tuple[int, int]],
    start_date: date,
    end_date: Optional[date] = None,
    enabled: bool = True,
    category: str = "ANNOUNCEMENT",
    sources: Optional[list[dict]] = None,
) -> int:
    """Create a non-template recurring weekly event.

    For backward compatibility with the DB-side ``create_event``, ``source_id``
    is accepted but ignored if ``sources`` is provided. Going forward, callers
    should pass a fully-formed ``sources`` list:

        sources=[{"sourceId": 6, "priorityGroup": "LOW", "libraryItem": {...}}]
    """
    if sources is None:
        # Best-effort fallback: look up the library item via the source's listing.
        # The captured POST /schedulers body uses ``{"sourceId": null, "libraryItem": {...}}``
        # for newly-instantiated sources — meaning the server creates a per-destination
        # dev_source/playlist on the fly. We mirror that pattern.
        # If the caller provided an existing source_id, use a minimal sources entry.
        sources = [{"sourceId": source_id, "priorityGroup": "LOW"}]

    scheduler = api.create_scheduler(
        name=name,
        category=category,
        zone_id=destination_id,
        sources=sources,
        days_of_week=list(days_of_week),
        specific_times=list(times),
        start_on=start_date,
        end_on=end_date,
        repeat_type="WEEK",
    )
    return scheduler.id


# ---------------------------------------------------------------------------
# Library file management + playlist construction
# ---------------------------------------------------------------------------

LIBRARY_ID_FOR_CATEGORY = {
    "music": 1,           # default music library id on this AAM Pro install
    "announcement": 3,    # default announcement library id
    "paging": 3,          # paging uses the announcement library
}


def upload_audio_file(
    api: AampApi,
    *,
    file_path: str,
    category: str = "announcement",   # 'music' | 'announcement' | 'paging'
    library_id: Optional[int] = None,
    target_filename: Optional[str] = None,
    target_directory: Optional[str] = None,
) -> dict:
    """Upload one local audio file to an AAM Pro library.

    Args:
        file_path: absolute path on the local filesystem.
        category: picks the default library id (music=1, announcement=3) unless
            ``library_id`` is explicitly given.
        library_id: explicit library id (overrides ``category``).
        target_filename: rename on upload (e.g. ``bells/school_bell.mp3``).
            Forward slashes create sub-paths inside the library.
        target_directory: ensure this subdirectory exists in the library before
            uploading. If set and target_filename has no path, the file is
            uploaded under ``<target_directory>/<basename>``.

    Returns:
        A small dict with ``library_id`` and ``uploaded_name`` for downstream
        identification. (The server returns 204 with no body; the caller can
        :meth:`AampApi.search_library` to find the new ``libraryItemId``.)
    """
    from pathlib import Path
    p = Path(file_path)
    if library_id is None:
        library_id = LIBRARY_ID_FOR_CATEGORY.get(category.lower(), 3)
    name = target_filename or p.name
    if target_directory:
        try:
            api.create_library_directory(library_id, target_directory)
        except Exception:
            pass   # OK if it already exists
    api.upload_file_to_library(library_id, p, target_filename=name, lib_path=target_directory)
    full_path = f"{target_directory}/{name}" if target_directory else name
    return {"library_id": library_id, "uploaded_name": full_path}


def bulk_upload_directory(
    api: AampApi,
    *,
    local_dir: str,
    category: str = "announcement",
    library_id: Optional[int] = None,
    library_subdir: Optional[str] = None,
    recursive: bool = False,
    extensions: tuple[str, ...] = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"),
) -> list[dict]:
    """Upload every audio file in a local directory to one AAM Pro library.

    Returns a list of one entry per file (success or failure).
    """
    from pathlib import Path
    d = Path(local_dir)
    if not d.is_dir():
        raise NotADirectoryError(f"not a directory: {d}")
    if library_id is None:
        library_id = LIBRARY_ID_FOR_CATEGORY.get(category.lower(), 3)
    # Ensure subdir exists once if requested.
    if library_subdir:
        try:
            api.create_library_directory(library_id, library_subdir)
        except Exception:
            pass
    pattern = "**/*" if recursive else "*"
    out: list[dict] = []
    for f in sorted(d.glob(pattern)):
        if not f.is_file() or f.suffix.lower() not in extensions:
            continue
        target_name = f.name  # flat — no slashes
        try:
            api.upload_file_to_library(library_id, f, target_filename=target_name, lib_path=library_subdir)
            full_path = f"{library_subdir}/{target_name}" if library_subdir else target_name
            out.append({"file": str(f), "library_id": library_id, "uploaded_name": full_path, "status": "ok"})
        except Exception as e:
            out.append({"file": str(f), "library_id": library_id, "uploaded_name": target_name,
                         "status": "fail", "error": str(e)})
    return out


def library_item_to_source_entry(
    api: AampApi,
    *,
    library_item_id: int,
    library_id: int = 3,
    priority_group: str = "LOW",
) -> dict:
    """Look up a library file and return the source-entry dict the scheduler API
    expects when you want to play that file as a one-off (no pre-created source).

    AAM Pro schedulers' ``sources`` field accepts two forms:
      - ``{"sourceId": <existing source id>, "libraryItem": null}`` — when you've
        already pre-created a Source row (e.g. a music PLAYLIST source).
      - ``{"sourceId": null, "libraryItem": <full library item dict>}`` — when
        you want to play a single library file directly. The server creates a
        transient source per scheduler.

    For uploaded announcement files (voice, bells, etc.), the second form is
    what bell schedules use empirically. This helper returns that shape.
    """
    items = api.list_library_items(library_id, path="/")
    # The basic listing only returns root-level items; recurse via search for
    # files in subdirectories.
    target = next((it for it in items if it.id == library_item_id), None)
    if target is None:
        for it in api.search_library(library_id, pattern=""):
            if it.id == library_item_id:
                target = it
                break
    if target is None:
        raise LookupError(
            f"library item id={library_item_id} not found in library #{library_id}"
        )
    return {
        "sourceId": None,
        "libraryItem": target.to_dict(),    # camelCase JSON, ready for the API
        "priorityGroup": priority_group,
    }


def create_playlist(
    api: AampApi,
    *,
    name: str,
    category: str = "music",
    library_item_ids: Iterable[int] = (),
    repeat: bool = True,
    shuffle: bool = False,
) -> int:
    """Create a PLAYLIST source and (optionally) populate it with library items.

    Returns the new source id. After this you can reference the playlist via
    its source id in :func:`create_music_schedule` (for music) or as a source
    in `create_event` (for announcements).
    """
    ids = list(library_item_ids)
    src = api.create_playlist_source(name=name, category=category, repeat=repeat, shuffle=shuffle)
    source_id = int(src["id"])
    if ids:
        api.add_playlist_items(source_id, ids)
    return source_id


def create_music_schedule(
    api: AampApi,
    *,
    name: str,
    destination_id: int,
    source_id: int,
    daily_start: str,                 # "HH:MM" — start of the daily play window
    daily_end: str = "23:59",         # "HH:MM" — end of the window; default = all day
    start_date: date,
    end_date: Optional[date] = None,  # None = no end (indefinite)
    day_every: int = 1,               # 1 = every day, 2 = every other day, etc.
    enabled: bool = True,
) -> int:
    """Create a music play schedule on a destination.

    Differences from :func:`create_event` (bells / announcements):

      - ``category="MUSIC"`` (not ANNOUNCEMENT)
      - ``repeatType="DAY"`` (daily recurrence, no day-of-week filter)
      - ``specificTimes`` is a single play **window** ``[daily_start, daily_end]``
        rather than a list of instantaneous triggers
      - ``queueable=False`` — music shouldn't queue behind paging
      - ``sources`` references an existing audio source by id (with ``libraryItem=null``)
        — typically a NET_SOURCE (web stream) or playlist that already exists on the site

    For "indefinite" music that plays the same window every day forever, pass
    ``end_date=None``. For continuous all-day playback, leave the default
    ``daily_end="23:59"`` (or pass ``"24:00"`` to test the SPA's max value).

    Returns the new scheduler id.
    """
    sources = [{"sourceId": source_id, "libraryItem": None, "priorityGroup": "LOW"}]
    scheduler = api.create_scheduler(
        name=name,
        category="MUSIC",
        zone_id=destination_id,
        sources=sources,
        specific_times=[(daily_start, daily_end)],
        start_on=start_date,
        end_on=end_date,
        repeat_type="DAY",
        day_every=day_every,
        autostart=True,
        queueable=False,        # music doesn't queue
        daily_recurrences_type="DAYS",
    )
    return scheduler.id


def apply_template(
    api: AampApi,
    *,
    template_id: int,
    destination_id: int,
    name: str,  # backward-compat — the API endpoint doesn't take a per-binding name
    days_of_week: Iterable[str],
    times: Iterable[tuple[int, int]],  # backward-compat — times live on the template's templateSets
    start_date: date,
    end_date: Optional[date] = None,
    enabled: bool = True,
) -> None:
    """Apply a template to a destination on a recurring schedule.

    Note: ``times`` is now bound to the template (via ``add_template_content``)
    rather than to the binding — the captured ``scheduleOn`` body has no
    time-of-day fields, only the recurrence interval. We accept ``times``
    for backward compatibility and ignore it; the template's own scheduler
    block defines when it fires within the day. ``name`` is similarly
    advisory (only the interval is sent to the server).
    """
    api.schedule_template_on_zone(
        template_id=template_id,
        zone_id=destination_id,
        days_of_week=list(days_of_week),
        start_on=start_date,
        end_on=end_date,
    )


# ---------------------------------------------------------------------------
# Schedulers (direct manipulation)
# ---------------------------------------------------------------------------

def delete_event(api: AampApi, scheduler_id: int) -> None:
    """Delete a scheduler and all its associated events/calendar entries."""
    api.delete_scheduler(scheduler_id)


# ---------------------------------------------------------------------------
# Per-occurrence overrides
# ---------------------------------------------------------------------------

def delete_occurrence(
    api: AampApi,
    *,
    template_id: Optional[int] = None,
    destination_id: Optional[int] = None,
    scheduler_id: Optional[int] = None,
    occurrence_date: Optional[date] = None,
    start_time: Optional[datetime] = None,
) -> None:
    """Cancel one occurrence.

    Two ways to call:
    - ``(template_id, destination_id, occurrence_date)`` — uses ``createDayException``
      to cancel the template binding on a specific date.
    - ``(scheduler_id, start_time)`` — modifies the event directly via ``update_event``
      with the deletion flag. (Not yet fully supported by the API client; raise.)
    """
    if template_id is not None and destination_id is not None and occurrence_date is not None:
        api.create_day_exception(
            template_id=template_id,
            zone_id=destination_id,
            exception_date=occurrence_date,
        )
        return
    raise NotImplementedError(
        "Direct scheduler-occurrence deletion via /events/{id} isn't yet wrapped. "
        "Use (template_id, destination_id, occurrence_date) for template-driven cancellations."
    )


def move_occurrence(
    api: AampApi,
    *,
    event_id: int,
    new_start_time: datetime,
    name: Optional[str] = None,
    new_end_time: Optional[datetime] = None,
) -> None:
    """Shift a single occurrence to a different time via ``PATCH /events/{eventId}``.

    ``event_id`` is the id of the materialized occurrence (from
    :meth:`AampApi.list_events`). Different shape from the DB-side function
    which took ``(scheduler_id, original_start_time, new_start_time)``."""
    api.update_event(
        event_id=event_id,
        name=name,
        from_dt=new_start_time,
        to_dt=new_end_time,
    )


# ---------------------------------------------------------------------------
# Exception groups (named holiday calendars)
# ---------------------------------------------------------------------------

def create_exception_group(
    api: AampApi,
    *,
    name: str,
    dates: Iterable[date] = (),
    yearly_dates: Iterable[tuple[int, int]] = (),
) -> int:
    """Create a named exception group.

    Endpoint not yet captured — likely ``POST /webapi/v1/exceptionGroups`` per
    the discovered surface. Raise until verified live.
    """
    raise NotImplementedError(
        "POST /webapi/v1/exceptionGroups body shape not yet captured. "
        "Create one via the UI and re-run the observer to capture the body."
    )


def attach_exception_group(api: AampApi, scheduler_id: int, exception_group_id: Optional[int]) -> None:
    """Bind an exception group to a scheduler.

    Endpoint not yet captured. Probably ``PUT /webapi/v1/schedulers/{id}`` with
    an updated ``exceptionGroupId`` field, or a dedicated ``/attach`` route.
    """
    raise NotImplementedError(
        "Exception-group attach endpoint not yet captured."
    )
