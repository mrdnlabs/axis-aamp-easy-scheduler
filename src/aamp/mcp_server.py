"""MCP server exposing AAM Pro read, intent, and write tools.

Stdio transport — run as ``aamp-mcp`` (after ``pip install -e .``) or
``python -m aamp.mcp_server``. Connect from Claude Desktop, Claude Code,
or any MCP-compatible client by pointing at the executable.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable, Optional

from mcp.server.fastmcp import FastMCP

from . import discovery as _discovery
from . import onboard as _onboard
from . import intent as _intent
from . import plan as _plan
from . import read as _read
from . import voice as _voice
from . import write as _write
from .api import AampApi
from .config import load_config
from .db import connect
from .describe import describe_destination, describe_site_schedule
from .device import AxisDevice

mcp = FastMCP("aamp-easy-scheduler")

# -------------------------------------------------------------------------
# Lazy API singleton — running the OAuth flow on every tool call would burn
# ~1s and create a new IAM client each time. One AampApi survives across
# tool calls; it auto-refreshes its token internally when expired.
# -------------------------------------------------------------------------
_api: AampApi | None = None


def _get_api() -> AampApi:
    global _api
    if _api is None:
        _api = AampApi.from_config(load_config())
    return _api


def _dump(items: Any) -> str:
    """Serialize Pydantic models (single or list) to compact JSON for tool returns."""
    if isinstance(items, list):
        payload = [i.model_dump(mode="json") if hasattr(i, "model_dump") else i for i in items]
    elif hasattr(items, "model_dump"):
        payload = items.model_dump(mode="json")
    else:
        payload = items
    return json.dumps(payload, indent=2, default=str)


def _parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _parse_times(times: Iterable[Any]) -> list[tuple[int, int]]:
    """Accept times as 'HH:MM' strings, [h,m] pairs, or {'hour':h,'minute':m} dicts."""
    out: list[tuple[int, int]] = []
    for t in times:
        if isinstance(t, str):
            h_s, m_s = t.split(":", 1)
            out.append((int(h_s), int(m_s)))
        elif isinstance(t, dict):
            out.append((int(t["hour"]), int(t["minute"])))
        elif isinstance(t, (list, tuple)) and len(t) >= 2:
            out.append((int(t[0]), int(t[1])))
        else:
            raise ValueError(f"Cannot parse time: {t!r}")
    return out


# ---------------------------------------------------------------------------
# READ TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
def get_local_date_time() -> str:
    """Current local date and time on the chat server. Use to ground relative dates ("next Wednesday", "two weeks from now")."""
    now = datetime.now().astimezone()
    return json.dumps({
        "iso": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
        "human": now.strftime("%A, %B %d, %Y at %I:%M %p %Z").replace("  ", " "),
    }, indent=2)


@mcp.tool()
def list_sites() -> str:
    """List all AXIS Audio Manager Pro sites configured on this server."""
    with connect() as conn:
        return _dump(_read.list_sites(conn))


@mcp.tool()
def list_physical_zones(site_id: int | None = None) -> str:
    """List physical zones (rooms/areas where speakers live)."""
    with connect() as conn:
        return _dump(_read.list_physical_zones(conn, site_id))


@mcp.tool()
def list_destinations(site_id: int | None = None) -> str:
    """List destinations (content-routing zones). Each contains physical zones."""
    with connect() as conn:
        return _dump(_read.list_destinations(conn, site_id))


@mcp.tool()
def list_sources(site_id: int | None = None) -> str:
    """List audio sources (tone files, streams, web sources, paging inputs)."""
    with connect() as conn:
        return _dump(_read.list_sources(conn))


@mcp.tool()
def list_templates(site_id: int | None = None) -> str:
    """List templates (reusable content rules applied to destinations on a schedule)."""
    with connect() as conn:
        return _dump(_read.list_templates(conn, site_id))


@mcp.tool()
def list_schedule_events(destination_id: int | None = None) -> str:
    """List scheduled audio events (bells, announcements, music). Each event includes
    its recurrence, time-of-day list, bound template (if any), and any per-occurrence
    overrides (cancelled or moved single occurrences)."""
    with connect() as conn:
        return _dump(_read.list_schedule_events(conn, destination_id))


@mcp.tool()
def list_opening_hours() -> str:
    """List opening-hours definitions (used as anchors for relative-time events)."""
    with connect() as conn:
        return _dump(_read.list_opening_hours(conn))


@mcp.tool()
def list_exception_groups() -> str:
    """List exception groups (named sets of dates — e.g., 'district holidays' — that cancel schedules)."""
    with connect() as conn:
        return _dump(_read.list_exception_groups(conn))


@mcp.tool()
def describe_site(site_id: int | None = None) -> str:
    """Render the entire site's current configuration as readable markdown."""
    with connect() as conn:
        return describe_site_schedule(conn, site_id)


@mcp.tool()
def describe_one_destination(destination_id: int) -> str:
    """Render one destination's full configuration as markdown."""
    with connect() as conn:
        destinations = _read.list_destinations(conn)
        target = next((d for d in destinations if d.id == destination_id), None)
        if target is None:
            return f"_(no destination with id={destination_id})_\n"
        physical = _read.list_physical_zones(conn, target.site_id)
        events = _read.list_schedule_events(conn, destination_id)
        templates = {t.id: t for t in _read.list_templates(conn, target.site_id)}
        sources = {s.id: s for s in _read.list_sources(conn)}
        return describe_destination(
            target,
            physical_zones_by_id={z.id: z for z in physical},
            events=events,
            templates_by_id=templates,
            sources_by_id=sources,
        )


# ---------------------------------------------------------------------------
# INTENT TOOLS — user's intended schedule (free-form markdown)
# ---------------------------------------------------------------------------

@mcp.tool()
def read_intent_doc(site_id: int = 1) -> str:
    """Read the per-site intent document (markdown) describing the user's *intended* schedule.

    The intent doc is your record of WHY a schedule looks the way it does —
    day-pattern names, application rules, free-form notes. Pair it with
    ``describe_site`` to see the *actual* DB state.
    """
    text = _intent.read_intent(site_id)
    if text is None:
        return f"_(no intent doc yet for site {site_id}; call bootstrap_intent to create one)_"
    return text


@mcp.tool()
def write_intent_doc(site_id: int, content: str) -> str:
    """Overwrite the full intent doc for a site. Use ``patch_intent_section`` if you only
    need to update one section — it's safer."""
    p = _intent.write_intent(site_id, content)
    return f"Wrote {len(content)} bytes to {p}"


@mcp.tool()
def patch_intent_section(site_id: int, section_title: str, new_body: str) -> str:
    """Replace the body of one ``## <section_title>`` section of the intent doc.

    Common sections in the bootstrap template:
    ``Description``, ``Day schedules``, ``Application``, ``One-off events``, ``Notes``.
    """
    try:
        p = _intent.patch_intent_section(site_id, section_title, new_body)
        return f"Patched section '## {section_title}' in {p}"
    except (FileNotFoundError, KeyError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def bootstrap_intent(site_id: int = 1, overwrite: bool = False) -> str:
    """Create an empty intent-doc skeleton for a site, ready for conversational filling.

    If the file already exists, returns its path unchanged unless ``overwrite=True``.
    """
    with connect() as conn:
        p = _intent.bootstrap_intent(conn, site_id, overwrite=overwrite)
    return f"Intent doc at: {p}"


# ---------------------------------------------------------------------------
# WRITE TOOLS — stable (well-tested row shapes)
# ---------------------------------------------------------------------------

@mcp.tool()
def create_physical_zone(site_id: int, name: str, parent_zone_id: int | None = None) -> str:
    """Create a physical zone (a room or area). Optionally nest under a parent zone."""
    new_id = _write.create_physical_zone(
        _get_api(), site_id=site_id, name=name, parent_zone_id=parent_zone_id
    )
    parent_msg = f" under parent #{parent_zone_id}" if parent_zone_id else ""
    return f"Created physical zone '{name}' (id={new_id}){parent_msg}."


@mcp.tool()
def create_destination(site_id: int, name: str, physical_zone_ids: list[int] | None = None) -> str:
    """Create a destination (content-routing zone).

    Note: physical-zone binding is not yet implemented via API — the SPA does
    it via a separate PATCH that we haven't yet captured. For now the zone is
    created without member zones; bind them manually via the UI, or supply
    them later when we wire up the PATCH endpoint.
    """
    pz = list(physical_zone_ids or [])
    new_id = _write.create_destination(_get_api(), site_id=site_id, name=name, physical_zone_ids=pz)
    msg = f"Created destination '{name}' (id={new_id})"
    if pz:
        msg += f" (physical_zone_ids {pz} not yet applied — binding endpoint pending capture)"
    return msg + "."


@mcp.tool()
def create_template(site_id: int, name: str, category: str) -> str:
    """Create an empty template. Add content via ``add_template_content``.

    Args:
        category: one of 'music', 'announcement', 'paging'.
    """
    new_id = _write.create_template(
        _get_api(), site_id=site_id, name=name, category=category
    )
    return f"Created {category} template '{name}' (id={new_id})."


@mcp.tool()
def add_template_content(
    template_id: int,
    scheduler_name: str,
    specific_times: list[str],
    files: list[dict],
) -> str:
    """Populate a template with content + a within-day scheduler block.

    Args:
        scheduler_name: identifies the within-day rule (e.g. "morning_bells").
        specific_times: list of "HH:MM" strings — when each bell fires within a day.
        files: list of LibraryItem dicts (use list_library_items to fetch shapes).
    """
    ts_id = _write.add_template_content(
        _get_api(),
        template_id=template_id,
        files=files,
        scheduler_name=scheduler_name,
        specific_times=specific_times,
    )
    return f"Added content to template #{template_id}: scheduler '{scheduler_name}' (id={ts_id}), {len(specific_times)} firing time(s)."


@mcp.tool()
def delete_template(template_id: int) -> str:
    """Delete a template."""
    _write.delete_template(_get_api(), template_id)
    return f"Deleted template #{template_id}."


@mcp.tool()
def delete_destination(destination_id: int) -> str:
    """Delete a destination. The server returns an error if it's still referenced."""
    try:
        _write.delete_destination(_get_api(), destination_id)
    except Exception as e:
        return f"ERROR: {e}"
    return f"Deleted destination #{destination_id}."


@mcp.tool()
def schedule_template(
    template_id: int,
    destination_id: int,
    days_of_week: list[str],
    start_date: str,
    end_date: str | None = None,
    week_every: int = 1,
) -> str:
    """Apply a template to a destination on a recurring schedule.

    This is the killer single-call endpoint that replaces a multi-row DB ceremony.

    Args:
        days_of_week: e.g. ['Tue', 'Thu'] or ['Monday', 'Friday'].
        start_date: ISO date ('YYYY-MM-DD'). Required.
        end_date: ISO date for the end of the binding, or null for no end.
        week_every: 1 = weekly, 2 = every other week, etc.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else None
    _write.schedule_template_on_destination(
        _get_api(),
        template_id=template_id,
        destination_id=destination_id,
        days_of_week=days_of_week,
        start_date=start,
        end_date=end,
        week_every=week_every,
    )
    days = ", ".join(days_of_week)
    return f"Scheduled template #{template_id} on destination #{destination_id}: {days}, {start} to {end or 'no end'}."


@mcp.tool()
def unschedule_template(template_id: int, destination_id: int, interval: dict) -> str:
    """Remove a previously-applied template binding.

    ``interval`` must match the binding's recurrence-interval block (copy it
    from ``get_template`` → ``usedInZones[].interval``)."""
    _write.unschedule_template_on_destination(
        _get_api(),
        template_id=template_id,
        destination_id=destination_id,
        interval=interval,
    )
    return f"Unscheduled template #{template_id} from destination #{destination_id}."


@mcp.tool()
def cancel_one_occurrence(
    template_id: int,
    destination_id: int,
    exception_date: str,
) -> str:
    """Cancel a template application for a single calendar day on one destination.

    Args:
        exception_date: ISO date string, e.g. '2026-12-23'.
    """
    d = date.fromisoformat(exception_date)
    _write.create_day_exception(
        _get_api(),
        template_id=template_id,
        destination_id=destination_id,
        exception_date=d,
    )
    return f"Cancelled template #{template_id} on destination #{destination_id} for {d.isoformat()}."


@mcp.tool()
def move_one_occurrence(
    event_id: int,
    new_start_time: str,
    name: str | None = None,
    new_end_time: str | None = None,
) -> str:
    """Move a single materialized occurrence to a different time.

    Args:
        event_id: id of the event from ``list_schedule_events`` / ``GET /events`` (NOT the scheduler id).
        new_start_time: ISO datetime, e.g. '2026-11-15T14:00'.
        name: optional new name.
        new_end_time: optional new end datetime.
    """
    new_dt = _parse_datetime(new_start_time)
    end_dt = _parse_datetime(new_end_time) if new_end_time else None
    _write.move_occurrence(
        _get_api(),
        event_id=event_id,
        new_start_time=new_dt,
        new_end_time=end_dt,
        name=name,
    )
    return f"Moved event #{event_id} to {new_dt:%Y-%m-%d %H:%M}."


@mcp.tool()
def delete_event(scheduler_id: int) -> str:
    """Delete a scheduler and all its events/calendar rows."""
    _write.delete_event(_get_api(), scheduler_id)
    return f"Deleted scheduler #{scheduler_id}."


# ---------------------------------------------------------------------------
# WRITE TOOLS — experimental (verify against a live AAM Pro before trusting at scale)
# ---------------------------------------------------------------------------

@mcp.tool()
def upload_audio_file(
    file_path: str,
    category: str = "announcement",
    library_subdir: str | None = None,
    target_filename: str | None = None,
) -> str:
    """Upload a local audio file (MP3 / WAV / FLAC / OGG) to an AAM Pro library.

    Args:
        file_path: absolute path to the local file on this server's filesystem.
        category: 'music' or 'announcement' — picks the library (1=music, 3=announcement).
        library_subdir: optional subdirectory inside the library; created if needed.
            Use a flat name (e.g. "bells") — no slashes in the filename itself.
        target_filename: optional rename on upload (e.g. "school_bell_classic.mp3").

    Returns:
        Where the file now lives inside the library.
    """
    info = _write.upload_audio_file(
        _get_api(),
        file_path=file_path,
        category=category,
        target_filename=target_filename,
        target_directory=library_subdir,
    )
    return f"Uploaded to library #{info['library_id']} at: {info['uploaded_name']}"


@mcp.tool()
def bulk_upload_directory(
    local_dir: str,
    category: str = "announcement",
    library_subdir: str | None = None,
    recursive: bool = False,
) -> str:
    """Upload every audio file in a local directory to an AAM Pro library.

    Args:
        local_dir: absolute path on this server (e.g. C:\\20260520_AampEasyScheduler\\assets\\bells).
        category: 'music' or 'announcement' — picks the library.
        library_subdir: optional subdirectory inside the library; created if needed.
        recursive: whether to descend into subdirectories of ``local_dir``.

    Returns:
        Summary of successes and failures.
    """
    results = _write.bulk_upload_directory(
        _get_api(),
        local_dir=local_dir,
        category=category,
        library_subdir=library_subdir,
        recursive=recursive,
    )
    ok = sum(1 for r in results if r["status"] == "ok")
    fail = sum(1 for r in results if r["status"] == "fail")
    lines = [f"Uploaded {ok}/{len(results)} files." + (f" {fail} failed." if fail else "")]
    for r in results:
        if r["status"] == "ok":
            lines.append(f"  OK   {r['uploaded_name']}")
        else:
            lines.append(f"  FAIL {r['uploaded_name']}  -- {r.get('error', '')[:120]}")
    return "\n".join(lines)


@mcp.tool()
def create_library_directory(category: str, lib_path: str) -> str:
    """Create a subdirectory inside a library (music or announcement).

    Args:
        category: 'music' or 'announcement'.
        lib_path: directory name to create (e.g. 'bells', 'announcements/safety').
    """
    library_id = _write.LIBRARY_ID_FOR_CATEGORY.get(category.lower(), 3)
    try:
        _get_api().create_library_directory(library_id, lib_path)
        return f"Created directory '{lib_path}' in library #{library_id}."
    except Exception as e:
        return f"ERROR creating '{lib_path}': {e}"


@mcp.tool()
def create_playlist(
    name: str,
    category: str = "music",
    library_item_ids: list[int] | None = None,
    repeat: bool = True,
    shuffle: bool = False,
) -> str:
    """Create a playlist source from existing library files.

    Use ``search_library`` or the result of ``upload_audio_file`` to discover
    the ``library_item_ids`` to include.

    Args:
        name: playlist name (e.g. "Lounge background mix").
        category: 'music' or 'announcement' (announcements rarely use playlists).
        library_item_ids: list of library item ids to add.
        repeat: loop the playlist when the last item finishes.
        shuffle: randomize order on each playthrough.
    """
    ids = list(library_item_ids or [])
    source_id = _write.create_playlist(
        _get_api(),
        name=name,
        category=category,
        library_item_ids=ids,
        repeat=repeat,
        shuffle=shuffle,
    )
    return (
        f"Created {category} playlist '{name}' (source #{source_id}) "
        f"with {len(ids)} item(s). Reference it via source_id={source_id}."
    )


@mcp.tool()
def create_music_event(
    name: str,
    destination_id: int,
    source_id: int,
    daily_start: str,
    start_date: str,
    daily_end: str = "23:59",
    end_date: str | None = None,
    day_every: int = 1,
) -> str:
    """Create a recurring music play schedule on a destination.

    Music plays in a daily *window* (start..end), not instantaneous bells.
    For an all-day "background music" event, leave daily_end as default
    ("23:59"). For an indefinite schedule, pass end_date=null.

    Args:
        name: human label for the schedule (e.g. "lounge background music").
        destination_id: zone id of the destination.
        source_id: id of an existing audio source (use list_sources to find;
            typically a NET_SOURCE for web streams).
        daily_start: "HH:MM" — when music starts each day.
        daily_end: "HH:MM" — when music stops each day. Default "23:59" = all day.
        start_date: ISO date when this schedule starts taking effect.
        end_date: ISO date when this schedule stops. null = indefinite.
        day_every: 1 = every day, 2 = every other day, etc.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else None
    sched_id = _write.create_music_schedule(
        _get_api(),
        name=name,
        destination_id=destination_id,
        source_id=source_id,
        daily_start=daily_start,
        daily_end=daily_end,
        start_date=start,
        end_date=end,
        day_every=day_every,
    )
    end_phrase = f"until {end}" if end else "(no end)"
    every_phrase = "every day" if day_every == 1 else f"every {day_every} days"
    return (
        f"Created music event '{name}' (scheduler #{sched_id}): "
        f"{every_phrase} from {daily_start} to {daily_end}, "
        f"starting {start} {end_phrase}."
    )


@mcp.tool()
def create_event(
    name: str,
    destination_id: int,
    sources: list[dict],
    days_of_week: list[str],
    times: list[str],
    start_date: str,
    end_date: str | None = None,
    category: str = "ANNOUNCEMENT",
    enabled: bool = True,
) -> str:
    """Create a recurring non-template scheduled event on a destination.

    Args:
        sources: list of source descriptors. Each dict shape:
            {"sourceId": <int or null>, "libraryItem": <LibraryItem dict>, "priorityGroup": "LOW"}
            For ANNOUNCEMENT category the server requires exactly one source.
        days_of_week: e.g. ['Mon', 'Wed', 'Fri'].
        times: list of 'HH:MM' strings (one per firing time per day).
        start_date / end_date: ISO date strings; null end_date means forever.
        category: 'ANNOUNCEMENT', 'MUSIC', or 'PAGING'.
    """
    times_parsed = _parse_times(times)
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is None:
        return "ERROR: start_date is required"
    sched_id = _write.create_event(
        _get_api(),
        name=name,
        destination_id=destination_id,
        source_id=0,  # ignored when 'sources' is provided
        days_of_week=days_of_week,
        times=times_parsed,
        start_date=start,
        end_date=end,
        enabled=enabled,
        category=category,
        sources=sources,
    )
    days = ", ".join(days_of_week)
    return (
        f"Created event '{name}' (scheduler #{sched_id}): "
        f"weekly on {days} at {', '.join(times)}, "
        f"from {start} {'until ' + str(end) if end else '(no end)'}."
    )


# ---------------------------------------------------------------------------
# PLAN / CHANGE-SET TOOL — atomic multi-operation execution with preview
# ---------------------------------------------------------------------------

@mcp.tool()
def generate_voice_announcement(
    text: str,
    slug: str | None = None,
    voice: str | None = None,
    upload: bool = True,
    category: str = "announcement",
) -> str:
    """Use ElevenLabs to generate spoken audio from text and (optionally) upload to AAM Pro.

    Args:
        text: what the voice should say. Keep it short and clear — schools
            play announcements many times a day.
        slug: optional filesystem-friendly stem for the output file
            (e.g. 'fire_drill', 'lunch_dismissal'). Derived from text if omitted.
        voice: voice name ("Rachel" default, also "Adam", "Bella", "Antoni") or
            a raw ElevenLabs voice id.
        upload: if True (default), also upload the result to the AAM Pro library.
        category: 'announcement' (default) or 'music' — picks the library.

    Returns:
        Path to the saved MP3 + library upload info.
    """
    try:
        if upload:
            info = _voice.generate_and_upload(
                text,
                api=_get_api(),
                voice=voice,
                slug=slug,
                category=category,
            )
            lid = info.get("library_item_id")
            item_msg = (
                f" (library item id {lid})" if lid else " (uploaded; id not auto-discovered)"
            )
            return (
                f"Generated voice for: {text!r}\n"
                f"  voice:    {info['voice']}\n"
                f"  local:    {info['local_path']}\n"
                f"  uploaded: library #{info['library_id']} -> {info['target_path']}{item_msg}\n"
                f"  slug:     {info['slug']}"
            )
        else:
            path = _voice.generate_audio(text, voice=voice, slug=slug)
            return (
                f"Generated voice for: {text!r}\n"
                f"  voice:    {voice or 'Rachel'}\n"
                f"  local:    {path}\n"
                f"  (not uploaded; pass upload=True to push to AAM Pro)"
            )
    except RuntimeError as e:
        return f"ERROR: {e}"


@mcp.tool()
def execute_change_set(operations: list[dict], dry_run: bool = True) -> str:
    """Execute multiple write operations against the AAM Pro API in sequence.

    This is the recommended way to apply any multi-step change (e.g., "create a
    destination, create a template, apply it on a recurring schedule").

    Each operation is a dict of ``{"action": "<name>", "args": {...}}``. Known actions:

      - create_physical_zone(site_id, name, parent_zone_id?)
      - create_destination(site_id, name, physical_zone_ids[])
      - create_template(site_id, name, category)
      - add_template_content(template_id, scheduler_name, specific_times[], files[])
      - delete_template(template_id)
      - delete_destination(destination_id)
      - schedule_template(template_id, destination_id, days_of_week[], start_date, end_date?, week_every?)
      - unschedule_template(template_id, destination_id, interval)
      - create_day_exception(template_id, destination_id, exception_date)
      - create_event(name, destination_id, source_id, days_of_week[], times[],
                     start_date, end_date?, category?, sources?)
      - delete_event(scheduler_id)
      - move_occurrence(event_id, new_start_time, name?, new_end_time?)

    Args:
        operations: list of ``{"action", "args"}`` dicts. Steps run in order.
        dry_run: if True (default), returns a textual preview without making
            any API calls. **Important:** unlike the previous DB-backed version,
            the REST API has no transactional rollback — if a step fails
            during apply (dry_run=False), prior successful steps are already
            committed.

    Returns:
        Multi-line summary ending with COMMITTED / FAILED / PREVIEWED status.
    """
    try:
        return _plan.execute_plan(operations, api=_get_api(), dry_run=dry_run)
    except _plan.PlanError as e:
        return (
            f"PLAN FAILED at step {e.step_index} ({e.action}): {e.original}\n"
            f"Earlier successful steps have already been committed (no rollback)."
        )
    except ValueError as e:
        return f"INVALID PLAN: {e}"


# ---------------------------------------------------------------------------
# AXIS DEVICE ONBOARDING (Phase 1 — discover + inspect, no writes)
# ---------------------------------------------------------------------------

@mcp.tool()
def discover_axis_devices(
    timeout: float = 5.0,
    prefer_mdns: bool = True,
    mdns_only: bool = False,
    include_legacy: bool = False,
) -> str:
    """Discover Axis network audio devices on the local LAN.

    Runs three productive methods in parallel by default: mDNS (browses
    every ``_axis-*`` service plus the mDNS meta-service), HTTP subnet
    sweep (probes ``/axis-cgi/basicdeviceinfo.cgi`` on every IP and
    harvests the MAC from the ``AXIS_<MAC>`` Digest realm), and ARP-cache
    sweep filtered by the 4 IEEE-registered Axis OUIs.

    Args:
        timeout: seconds to wait for mDNS responses (default 5).
        prefer_mdns: legacy parameter retained for backward compatibility;
            no longer changes behavior. All methods run in parallel.
        mdns_only: if True, skip the slower http-sweep/arp methods and
            return only mDNS results (~6s vs ~50s). Use when you trust
            multicast on the LAN and don't need MAC harvesting.
        include_legacy: also run SSDP + WS-Discovery. Both are off-by-default
            on AXIS OS 12+ and contributed nothing on the test LAN; enable
            only for fleets containing pre-OS-12 firmware.

    Returns:
        One device per line, with IP / MAC / model / serial / firmware where
        available, plus the discovery source(s) that found it.
    """
    devices = _discovery.discover_all(
        prefer_mdns=prefer_mdns,
        mdns_timeout=timeout,
        mdns_only=mdns_only,
        include_legacy=include_legacy,
    )
    if not devices:
        return ("No Axis devices found. If you expected to see some:\n"
                "  - mDNS doesn't cross subnets; verify devices are on the same LAN.\n"
                "  - Some firewalls block UDP/5353; try prefer_mdns=False to use ARP only.\n"
                "  - ARP only sees devices that have communicated recently; ping the\n"
                "    suspected device IP first to populate the ARP cache, then retry.")
    # Group by classification for a cleaner summary. The chat-side caller
    # almost always cares about audio devices specifically — other Axis
    # products (cameras, intercoms, etc.) are typically noise during AAM Pro
    # device onboarding.
    by_class: dict[str, list] = {}
    for d in devices:
        by_class.setdefault(d.device_class, []).append(d)
    classes_order = ("audio", "audio?", "aam-pro-server", "non-audio", "unknown")
    counts = " | ".join(
        f"{c}={len(by_class.get(c, []))}" for c in classes_order
        if by_class.get(c)
    )
    lines = [f"Found {len(devices)} Axis device(s):  {counts}"]
    for label in classes_order:
        members = by_class.get(label, [])
        if not members:
            continue
        lines.append("")
        lines.append(f"## {label} ({len(members)})")
        for d in members:
            bits = [d.ip]
            if d.model:
                bits.append(d.model)
            if d.audio_subtype:
                bits.append(f"[{d.audio_subtype}]")
            if d.serial:
                bits.append(f"sn={d.serial}")
            if d.firmware_version:
                bits.append(f"fw={d.firmware_version}")
            if d.mac:
                bits.append(d.mac)
            bits.append(f"({d.source})")
            lines.append("  " + "  ".join(bits))
    return "\n".join(lines)


@mcp.tool()
def test_axis_discovery_methods(
    mdns_timeout: float = 5.0,
    ssdp_timeout: float = 3.0,
    wsd_timeout: float = 4.0,
    http_sweep_timeout: float = 1.0,
    http_sweep_subnets: Optional[list[str]] = None,
) -> str:
    """Run every supported discovery method in parallel; show per-method results.

    Diagnostic tool — use this when ``discover_axis_devices`` misses
    devices you know exist. Returns a markdown table with how many devices
    each method found, wall-clock timing, and any errors. Also shows the
    merged device list with all method tags so you can see which protocols
    contributed to each hit.

    Methods tested:
      - mdns: Bonjour / multi-service mDNS browse
      - ssdp: M-SEARCH multicast on 239.255.255.250:1900 (off-by-default on AXIS OS 12+)
      - ws-discovery: SOAP-over-UDP Probe on 239.255.255.250:3702 (off-by-default on AXIS OS 12.1+)
      - http-sweep: direct HTTP probe of every IP in the local /24
      - arp: parses 'arp -a' and filters by Axis OUI

    Args:
        mdns_timeout: how long to listen for mDNS responses (default 5s).
        ssdp_timeout: SSDP listen window (default 3s).
        wsd_timeout: WS-Discovery listen window (default 4s).
        http_sweep_timeout: per-IP HTTP probe timeout (default 1s).
        http_sweep_subnets: list of CIDRs to sweep (e.g. ["10.0.0.0/24"]).
            Defaults to auto-detected local /24s.
    """
    bd = _discovery.discover_breakdown(
        mdns_timeout=mdns_timeout,
        ssdp_timeout=ssdp_timeout,
        wsd_timeout=wsd_timeout,
        http_sweep_timeout=http_sweep_timeout,
        http_sweep_subnets=http_sweep_subnets,
    )
    lines = ["## Discovery method breakdown", "",
             "| method | devices | seconds | error |",
             "|---|---:|---:|---|"]
    for name in ("mdns", "ssdp", "ws-discovery", "http-sweep", "arp"):
        devs = bd.by_method.get(name, [])
        t = bd.timings.get(name, 0)
        err = bd.errors.get(name, "")
        lines.append(f"| {name} | {len(devs)} | {t:.2f} | {err or '-'} |")
    lines.append("")
    lines.append(f"### Merged: {len(bd.merged)} unique IP(s)")
    if not bd.merged:
        lines.append("")
        lines.append("(no devices found by any method)")
    else:
        lines.append("")
        for d in sorted(bd.merged, key=lambda x: x.ip):
            bits = [f"`{d.ip}`"]
            if d.mac:
                bits.append(f"mac=`{d.mac}`")
            if d.model:
                bits.append(f"model=`{d.model}`")
            if d.serial:
                bits.append(f"sn=`{d.serial}`")
            if d.firmware_version:
                bits.append(f"fw=`{d.firmware_version}`")
            bits.append(f"sources=`{d.source}`")
            lines.append("- " + " ".join(bits))
    return "\n".join(lines)


@mcp.tool()
def inspect_axis_device(ip: str) -> str:
    """Probe a single Axis device for its model, firmware, and setup state.

    Read-only — no credentials needed; uses VAPIX endpoints that respond
    unauthenticated (``basicdeviceinfo.cgi``, ``systemready.cgi``).

    Use this after ``discover_axis_devices`` to learn more about a specific
    device, OR with a known IP when discovery is unavailable.

    Args:
        ip: the device's IP address (e.g. '192.0.2.10').

    Returns:
        Markdown-formatted summary including model, firmware, serial, and
        whether the device still needs initial password setup.
    """
    with AxisDevice(ip=ip) as dev:
        info = dev.inspect()
    if not info.get("reachable"):
        return f"Device {ip} is not reachable on HTTP. Check IP, network connectivity, and the device's power state."
    lines = [f"## Axis device at {ip}", ""]
    bi = info.get("basic_info") or {}
    if bi:
        lines.append(f"- **Model:** {bi.get('model_full') or bi.get('model') or '(unknown)'}")
        if bi.get("model_nbr") and bi.get("model_nbr") != bi.get("model"):
            lines.append(f"  - Model number: {bi.get('model_nbr')}")
        if bi.get("serial"):
            lines.append(f"- **Serial:** {bi['serial']}")
        if bi.get("firmware_version"):
            lines.append(f"- **Firmware:** {bi['firmware_version']}")
        if bi.get("architecture"):
            lines.append(f"- **Architecture:** {bi['architecture']}")
        if bi.get("build_date"):
            lines.append(f"- **Build date:** {bi['build_date']}")
    elif info.get("basic_info_error"):
        lines.append(f"- _Could not read basic device info: {info['basic_info_error']}_")
    sr = info.get("system_ready") or {}
    if sr:
        ready = sr.get("systemready") == "yes"
        needs = info.get("needs_initial_setup", False)
        lines.append(f"- **System ready:** {'yes' if ready else 'no'}")
        if needs:
            lines.append("- **Needs initial setup:** YES — root user / password must be created before further config.")
        else:
            lines.append("- Already provisioned — root user exists.")
    elif info.get("system_ready_error"):
        lines.append(f"- _Could not read system-ready state: {info['system_ready_error']}_")
    return "\n".join(lines)


def _format_onboarding_result(r: "_onboard.OnboardingResult") -> list[str]:
    """Render one OnboardingResult as a markdown bullet list."""
    head = f"### {r.ip}"
    bits = []
    if r.model:
        bits.append(f"model={r.model}")
    if r.serial:
        bits.append(f"sn={r.serial}")
    if r.dry_run:
        bits.append("DRY RUN")
    if bits:
        head += "  (" + ", ".join(bits) + ")"
    icon = {"ok": "OK", "failed": "FAIL", "partial": "PARTIAL"}.get(r.overall, "?")
    lines = [head, f"- **overall:** {icon}"]
    for s in r.steps:
        step_icon = {"ok": "[x]", "skipped": "[-]", "failed": "[!]",
                     "pending": "[ ]"}.get(s.status, "[?]")
        line = f"- {step_icon} **{s.name}** — {s.detail or s.status}"
        if s.error:
            line += f"\n    error: {s.error}"
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Settings — user-tunable runtime config (~/.aamp_settings.json)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_settings() -> str:
    """List every tunable runtime setting with its current value + description.

    Settings are non-secret operational config — history-trim length,
    discovery timeouts, capture rate limit, etc. Stored at
    ``~/.aamp_settings.json``. Reset a setting to its default by passing
    an empty string or ``"default"`` to ``set_setting``.

    Returns:
        Markdown table grouped by category.
    """
    from . import settings as _settings
    rows = _settings.all_settings()
    # Group by category for readability
    by_cat: dict[str, list] = {}
    for d, v in rows:
        by_cat.setdefault(d.category, []).append((d, v))
    out: list[str] = []
    for cat in sorted(by_cat):
        out.append(f"## {cat.title()}")
        out.append("")
        out.append("| Key | Value | Default | Description |")
        out.append("|---|---|---|---|")
        for d, v in by_cat[cat]:
            out.append(
                f"| `{d.key}` | `{v!r}` | `{d.default!r}` | {d.description} |"
            )
        out.append("")
    return "\n".join(out).rstrip()


@mcp.tool()
def get_setting(key: str) -> str:
    """Read one setting value. Returns the current effective value
    (which may be the on-disk override or the declared default)."""
    from . import settings as _settings
    d = _settings.def_for(key)
    if d is None:
        return (
            f"Unknown setting: {key!r}. Known settings: "
            f"{', '.join(s.key for s in _settings.DEFAULTS)}"
        )
    v = _settings.get_setting(key)
    return f"{key} = {v!r}  (default: {d.default!r})"


@mcp.tool()
def set_setting(key: str, value: str) -> str:
    """Update a runtime setting. Persists to ``~/.aamp_settings.json``.

    Args:
        key: One of the canonical keys from :func:`list_settings`.
        value: New value. Coerced to the declared type — strings like
            ``"50"`` for an int setting, ``"true"`` for a bool. Passing
            ``""`` or ``"default"`` resets the setting to its declared
            default (removes the override).

    Returns:
        Confirmation string with the new effective value.
    """
    from . import settings as _settings
    d = _settings.def_for(key)
    if d is None:
        return (
            f"Unknown setting: {key!r}. Known: "
            f"{', '.join(s.key for s in _settings.DEFAULTS)}"
        )
    if value == "" or value.lower() == "default":
        _settings.delete_setting(key)
        return f"Reset {key} to default: {d.default!r}"
    try:
        _settings.set_setting(key, value)
    except (KeyError, ValueError) as e:
        return f"Failed: {e}"
    return f"Set {key} = {_settings.get_setting(key)!r}  (default: {d.default!r})"


# ---------------------------------------------------------------------------
# Artifact-pill emission — surfaces the right-side pane from the chat
# ---------------------------------------------------------------------------

@mcp.tool()
def emit_artifact_pill(
    artifact: str,
    key: str,
    title: str,
    subtitle: str = "",
    data_json: str = "",
) -> str:
    """Render an ArtifactPill in the chat that opens the right-side pane.

    Call this when the conversation has produced a visualization that
    deserves more real estate than an inline tool-call card — a day-
    template timeline, a live onboarding pipeline, a discovery sweep
    breakdown, etc.

    Args:
        artifact: One of ``"day_template"``, ``"onboarding"``,
            ``"discovery"``. Determines which component the pane uses.
        key: Stable identifier for this artifact instance (e.g. a
            device IP, a template name). Re-emitting with the same
            ``(artifact, key)`` UPDATES the existing artifact instead
            of creating a new one — useful for live-updating views like
            a streaming onboarding pipeline.
        title: Pill title (e.g. ``"Late-start Wednesday timeline"``).
        subtitle: Optional small grey text under the title.
        data_json: JSON-encoded artifact payload. Must match the schema
            for ``artifact`` (see ``web/lib/types.ts`` for the
            ``DayTemplateArtifact`` / ``OnboardingArtifact`` /
            ``DiscoveryArtifact`` shapes).

    Returns:
        A short confirmation. The chat backend recognizes this tool's
        return and emits the corresponding ``artifact_pill`` SSE part
        — the LLM doesn't need to do anything else.
    """
    valid = ("day_template", "onboarding", "discovery")
    if artifact not in valid:
        return f"Unknown artifact kind: {artifact!r}. Expected one of: {valid}"
    # Validate JSON if provided
    if data_json:
        try:
            import json as _json
            _json.loads(data_json)
        except _json.JSONDecodeError as e:
            return f"Invalid data_json: {e}"
    return f"Emitted {artifact} artifact pill (key={key!r}, title={title!r})"


# ---------------------------------------------------------------------------
# Staging — apply-confirm-commit workflow for schedule changes
# ---------------------------------------------------------------------------

@mcp.tool()
def stage_schedule_change(
    title: str,
    effective: str,
    operations: list[dict[str, Any]],
    summary: str = "",
) -> str:
    """Stage a set of schedule changes for the user to review BEFORE applying.

    Use this for ANY mutation of AAM Pro state that the user has described
    in chat. The user sees a per-change diff (rendered as a ScheduleDiffCard
    in the web UI) and either confirms with ``apply`` or drops with
    ``discard``. ``apply`` invokes ``apply_staged_changes(staging_id)`` to
    commit; ``discard`` invokes ``discard_staged_changes(staging_id)``.

    Args:
        title: Short label for the diff card header (e.g.
            ``"Late-start Wednesdays"``).
        effective: Plain-language effective-date range
            (e.g. ``"May 27 to June 11"``).
        operations: List of operation objects. Each operation is a dict
            whose ``kind`` field selects the schema. Supported kinds:

            - ``{"kind": "create_event", "template_id": ..., "destination_id": ...,
                "label": ..., "start_time": "<ISO>", "detail": ...,
                "destination_name": ...}``
            - ``{"kind": "delete_event", "scheduler_id": ..., "label": ...,
                "detail": ...}``
            - ``{"kind": "schedule_template", "template_id": ...,
                "destination_id": ..., "days_of_week": [...],
                "start_date": "...", "end_date": "...", "label": ...,
                "detail": ..., "destination_name": ...}``
            - ``{"kind": "cancel_one_occurrence", "template_id": ...,
                "destination_id": ..., "exception_date": "YYYY-MM-DD",
                "label": ..., "detail": ...}``
        summary: Optional one-line summary used by the ApplyConfirmCard.

    Returns:
        JSON describing the staged change: ``{staging_id, title,
        effective, changes: [...]}``. The chat-side UI renders this as a
        ScheduleDiffCard. Pass the ``staging_id`` to
        ``apply_staged_changes`` when the user confirms.
    """
    import json as _json
    from pydantic import TypeAdapter, ValidationError
    from . import staging as _staging
    try:
        ops = TypeAdapter(list[_staging.Operation]).validate_python(operations)
    except ValidationError as e:
        return f"Failed to validate operations: {e}"
    try:
        cs = _staging.stage(title=title, effective=effective,
                             operations=ops, summary=summary)
    except ValueError as e:
        return f"Cannot stage: {e}"
    return _json.dumps(cs.to_diff_card(), indent=2)


@mcp.tool()
def apply_staged_changes(staging_id: str) -> str:
    """Commit a previously-staged change set to AAM Pro.

    Pops the staging set from the registry, runs each operation through
    the existing write tools, and returns a per-operation success/failure
    summary. Single-use: re-running with the same ``staging_id`` returns
    a "not found" error.

    Args:
        staging_id: The ``staging_id`` returned by ``stage_schedule_change``.

    Returns:
        Markdown summary of which operations succeeded and which failed.
        If any operation fails, subsequent operations still run — the
        report makes failures actionable rather than abandoning a batch.
    """
    from . import staging as _staging
    cs = _staging.pop(staging_id)
    if cs is None:
        return f"No staged change with id {staging_id!r} (expired or already applied/discarded)."
    return _apply_changeset(cs)


@mcp.tool()
def discard_staged_changes(staging_id: str) -> str:
    """Drop a staged change set without applying it.

    Args:
        staging_id: The ``staging_id`` to discard.

    Returns:
        Confirmation string.
    """
    from . import staging as _staging
    cs = _staging.pop(staging_id)
    if cs is None:
        return f"No staged change with id {staging_id!r} (expired or already applied/discarded)."
    return (
        f"Discarded staged change {staging_id!r}: {cs.title} ({len(cs.operations)} operation(s)). "
        f"Nothing was written to AAM Pro."
    )


def _apply_changeset(cs) -> str:
    """Dispatch every operation in ``cs`` through the existing write tools.

    Each operation calls the same function the LLM would have called
    directly. Failures are caught per-operation so the rest of the batch
    still runs; the result string lists each outcome.
    """
    from . import staging as _staging
    lines = [f"# Applied {len(cs.operations)} change(s) — {cs.title}", ""]
    failures = 0
    for i, op in enumerate(cs.operations, 1):
        try:
            if isinstance(op, _staging.CreateEventOp):
                # The existing create_event tool takes string args; pass
                # through. We deliberately don't try to be clever about
                # signature mapping — each branch is explicit so a typo
                # surfaces as a typing error here, not a runtime one in
                # AAM Pro.
                detail = create_event(  # type: ignore[name-defined]
                    template_id=op.template_id,
                    destination_id=op.destination_id,
                    start_time=op.start_time,
                )
            elif isinstance(op, _staging.DeleteEventOp):
                detail = delete_event(scheduler_id=op.scheduler_id)  # type: ignore[name-defined]
            elif isinstance(op, _staging.ScheduleTemplateOp):
                detail = schedule_template(  # type: ignore[name-defined]
                    template_id=op.template_id,
                    destination_id=op.destination_id,
                    days_of_week=op.days_of_week,
                    start_date=op.start_date,
                    end_date=op.end_date,
                )
            elif isinstance(op, _staging.CancelOccurrenceOp):
                detail = cancel_one_occurrence(  # type: ignore[name-defined]
                    template_id=op.template_id,
                    destination_id=op.destination_id,
                    exception_date=op.exception_date,
                )
            else:
                detail = f"unknown operation kind: {op!r}"
            lines.append(f"- ✓ **{op.label}** — {detail}")
        except Exception as e:
            failures += 1
            lines.append(f"- ✗ **{op.label}** — failed: {type(e).__name__}: {e}")
    lines.append("")
    if failures:
        lines.append(f"**{failures} of {len(cs.operations)} operation(s) failed.** Other operations succeeded.")
    else:
        lines.append("All operations applied successfully.")
    return "\n".join(lines)


@mcp.tool()
def list_credentials() -> str:
    """List every credential currently stored — VALUES NEVER RETURNED.

    Surfaces metadata only: account_id/field, description (from the
    canonical secret table), and whether each slot is populated. The
    web client's Credentials view uses this to render the masked table.

    Returns:
        Markdown table with one row per known credential slot. The
        "stored" column shows ``True`` / ``False``; the value column
        is always ``********`` and there is no way to retrieve the
        actual value through this tool or any other MCP tool.

    Implementation guarantee: the returned string contains no secret
    values. The credential store's audit log records every access.
    """
    from .credentials import KNOWN_SECRETS, get_credential_store
    store = get_credential_store()
    lines = ["| Account / Field | Description | Stored | Value |",
             "|---|---|---|---|"]
    for s in KNOWN_SECRETS:
        present = store.get(s.account_id, s.field) is not None
        lines.append(
            f"| `{s.account_id}/{s.field}` | {s.description} | "
            f"{'yes' if present else 'no'} | `********` |"
        )
    return "\n".join(lines)


@mcp.tool()
def audit_log(limit: int = 50, op: Optional[str] = None,
              principal: Optional[str] = None) -> str:
    """Read the credential-access audit log.

    Returns the most recent entries from ``~/.aamp_audit.log`` as a
    markdown table. Filterable by op (get / set / delete / list /
    capture_start / capture_submit) and by principal.

    Args:
        limit: maximum number of rows to return (default 50).
        op: optional filter — e.g. ``"capture_submit"`` to see only
            successful credential captures.
        principal: optional filter — e.g. ``"process"`` or ``"llm"``.

    Returns:
        Markdown table with timestamp, op, account/field, principal,
        decision, and reason. No credential values are ever included.
    """
    import json
    from pathlib import Path
    log_path = Path.home() / ".aamp_audit.log"
    if not log_path.exists():
        return "No audit log entries yet. (`~/.aamp_audit.log` does not exist.)"
    rows: list[dict[str, str]] = []
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if op and e.get("op") != op:
                continue
            if principal and e.get("principal") != principal:
                continue
            rows.append(e)
    except OSError as exc:
        return f"Could not read audit log: {exc}"
    if not rows:
        filt = []
        if op:
            filt.append(f"op={op!r}")
        if principal:
            filt.append(f"principal={principal!r}")
        return f"No audit-log entries matching filters: {', '.join(filt) or '(none)'}."
    rows = rows[-limit:]
    lines = ["| Timestamp | Op | Account/Field | Principal | Decision | Reason |",
             "|---|---|---|---|---|---|"]
    for e in rows:
        acct = f"{e.get('account_id','')}/{e.get('field','')}".rstrip("/")
        lines.append(
            f"| `{e.get('ts','')}` | `{e.get('op','')}` | `{acct}` | "
            f"{e.get('principal','')} | {e.get('decision','')} | "
            f"{e.get('reason','') or '—'} |"
        )
    return "\n".join(lines)


@mcp.tool()
def request_credential_capture(account_id: str, field: str) -> str:
    """Mint a one-time URL for the user to enter a credential value SECURELY.

    Use this when a tool returns a "credentials not configured" error and
    the user has a web UI open. The returned JSON includes a session
    token + URL that the web client's SecureCaptureModal opens. The user
    types the value into a form on that URL; the value goes directly to
    the OS keyring; the assistant never sees it.

    For CLI-only users, fall back to ``prepare_credential_capture`` which
    returns the literal ``aamp-set-credential`` command instead.

    Args:
        account_id: the canonical account id (e.g. ``"device"``).
        field: the canonical field name (e.g. ``"default_password"``).
            See ``KNOWN_SECRETS`` in ``src/aamp/credentials.py`` for the
            full table.

    Returns:
        A JSON object with ``token``, ``url``, ``description``, and
        ``expires_in_seconds``. Relay the URL to the user verbatim
        and DO NOT ask them to type the password in chat. Sample::

            {
              "token": "Mk9-bxJoExqd...",
              "url": "/api/credential-capture/Mk9-bxJoExqd...",
              "description": "Fleet password set on freshly...",
              "expires_in_seconds": 600
            }
    """
    import json
    from .server.capture import start_capture
    try:
        rec = start_capture(account_id, field)
    except ValueError as e:
        # Unknown slot — tell the LLM the canonical alternatives.
        return prepare_credential_capture(account_id, field)
    except Exception as e:
        return f"Failed to start capture: {type(e).__name__}: {e}"
    return json.dumps({
        "token": rec.token,
        "url": f"/api/credential-capture/{rec.token}",
        "account_id": rec.account_id,
        "field": rec.field,
        "description": rec.description,
        "expires_in_seconds": 600,
    }, indent=2)


@mcp.tool()
def prepare_credential_capture(account_id: str, field: str) -> str:
    """Return the instructions the user should follow to set or update a credential.

    Use this when a tool returns a "credentials not configured" error and
    you (the LLM) need to tell the user what to do — INSTEAD of asking
    them for the password in chat. The returned string includes the exact
    CLI command. Relay it VERBATIM.

    Today the capture happens via the terminal (``aamp-set-credential``,
    handled by Python's ``getpass`` so nothing is echoed). When the web
    capture UI lands later, this same tool will return a one-time URL
    instead — callers don't change.

    Args:
        account_id: the canonical account id (e.g. ``"aamp"``, ``"device"``,
            ``"elevenlabs"``). See KNOWN_SECRETS in src/aamp/credentials.py.
        field: the canonical field name (e.g. ``"password"``,
            ``"default_password"``, ``"api_key"``).

    Returns:
        A short instruction string with the literal CLI command. Includes
        a "do NOT type the password in chat" reminder so the chat agent
        always passes that warning through.

    Examples:
        prepare_credential_capture("device", "default_password")
        prepare_credential_capture("aamp", "password")
        prepare_credential_capture("elevenlabs", "api_key")
    """
    from .credentials import KNOWN_SECRETS, secret_for
    s = secret_for(account_id, field)
    if s is None:
        # Unknown — but the CLI still accepts arbitrary slots; tell the user
        # and list what we DO know about so the LLM can suggest a fix.
        known = "\n".join(
            f"  {ks.account_id}/{ks.field:<24}  {ks.description}"
            for ks in KNOWN_SECRETS
        )
        return (
            f"'{account_id}/{field}' is not a canonical credential slot.\n"
            f"Did you mean one of these?\n{known}"
        )
    return (
        f"To set the {s.description} ({s.account_id}/{s.field}) without "
        f"exposing it in chat, open a TERMINAL and run:\n\n"
        f"    aamp-set-credential {s.account_id}/{s.field}\n\n"
        f"Type the value when prompted (input hidden). Then retry the "
        f"original action. Do NOT type the password into this chat — it "
        f"would be logged in the transcript and sent to the LLM."
    )


@mcp.tool()
def onboard_axis_device(ip: str, dry_run: bool = False) -> str:
    """Run the full 4-step onboarding pipeline against one Axis audio device.

    Steps (each is idempotent — re-running is safe):
      1. inspect device + check whether root has been set up yet
      2. authenticate (try fleet candidate passwords) OR create root user
         with AAMP_DEVICE_DEFAULT_PASSWORD if device is in factory state
      3. install + start the AAM Pro ACAP for the device's architecture
      4. point the device at the AAM Pro server (this machine) via param.cgi

    Args:
        ip: the device's IP address (e.g. '192.0.2.10').
        dry_run: if True, only read probes — no writes. The trace shows
            what each step WOULD do without doing it. Good for first
            contact with a new device or before a fleet run.

    Returns:
        Markdown trace of every step with pass/fail status. On failure the
        trace still includes the prior successful steps so you can see how
        far the device got.

    Notes for the chat agent:
      - The device may take ~30s to appear in AAM Pro after step 4 succeeds.
      - If a device is quarantined by AAM Pro, surface the MAC/serial from
        the result so the user can approve it manually in the SPA.
      - If a step fails with a "credentials not configured" message, relay
        the tool's CLI instruction VERBATIM. Do NOT ask the user for a
        password in chat — passwords belong in the OS keyring, not the
        chat context. The tool tells the user exactly which `aamp-set-credential`
        command to run.
    """
    try:
        result = _onboard.onboard_device(ip, dry_run=dry_run)
    except RuntimeError as e:
        return f"Onboarding aborted: {e}"
    return "\n".join(_format_onboarding_result(result))


@mcp.tool()
def onboard_axis_fleet(
    dry_run: bool = False,
    ip_list: Optional[list[str]] = None,
    prefer_mdns: bool = True,
    mdns_timeout: float = 5.0,
) -> str:
    """Discover-and-onboard every Axis audio device on the LAN.

    Runs ``discover_axis_devices`` first (unless ``ip_list`` is provided),
    then runs the per-device onboarding pipeline against each one
    sequentially. Returns one section per device.

    Args:
        dry_run: pass True for a no-write probe of every device. Strongly
            recommended for the first fleet run.
        ip_list: explicit list of IPs to bypass discovery (useful for
            cross-subnet deployments where mDNS/ARP can't see the devices).
        prefer_mdns: see discover_axis_devices.
        mdns_timeout: see discover_axis_devices.

    Returns:
        Markdown summary, one section per device. The top line tallies
        ok / failed / partial across the fleet.

    Notes for the chat agent: if any device fails with a "credentials not
    configured" message, relay the tool's CLI instruction VERBATIM. Do NOT
    ask the user for a password in chat. The tool tells the user exactly
    which `aamp-set-credential` command to run in their terminal.
    """
    try:
        results = _onboard.onboard_fleet(
            dry_run=dry_run, ip_list=ip_list,
            prefer_mdns=prefer_mdns, mdns_timeout=mdns_timeout,
        )
    except RuntimeError as e:
        return f"Fleet onboarding aborted: {e}"
    if not results:
        return ("No devices to onboard. Discovery returned zero results.\n"
                "  - Verify devices are powered and on the same LAN.\n"
                "  - Try ip_list=['10.0.0.x', ...] to bypass discovery.")
    summary: dict[str, int] = {"ok": 0, "failed": 0, "partial": 0}
    for r in results:
        summary[r.overall] = summary.get(r.overall, 0) + 1
    header = (
        f"# Fleet onboarding: {len(results)} device(s) — "
        f"ok={summary.get('ok', 0)}, failed={summary.get('failed', 0)}"
        + (f", partial={summary['partial']}" if summary.get('partial') else "")
        + ("  (DRY RUN)" if dry_run else "")
    )
    out = [header, ""]
    for r in results:
        out.extend(_format_onboarding_result(r))
        out.append("")
    return "\n".join(out).rstrip()


def main() -> None:
    """Console-script entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
