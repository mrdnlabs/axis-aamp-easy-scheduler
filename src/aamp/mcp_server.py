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
