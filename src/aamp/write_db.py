"""Write-side operations for AAM Pro.

Every public function takes a psycopg ``Connection`` and runs inside the
caller's transaction (so a batch of writes can be wrapped in one
``with conn.transaction():``). MCP-tool wrappers in :mod:`aamp.mcp_server`
open and commit transactions per call.

Centralizing every write here is deliberate — when we eventually swap from
direct DB writes to AAM Pro's HTTP API, only this one module changes.

Stability tiers
---------------
**Stable (well-understood from the empty→populated DB diff):**
    create_physical_zone, create_destination, create_template,
    create_exception_group, attach_exception_group,
    delete_occurrence, move_occurrence, delete_event.

**Experimental (educated guesses pending live verification):**
    create_event (non-template scheduled event),
    apply_template (full template binding flow).

The experimental writes are marked with the ``EXPERIMENTAL_`` prefix on
their function signature comment and should be tested by creating one
row, restarting AAM Pro, and verifying the app sees + fires the event
correctly before being trusted at scale.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from typing import Iterable, Optional

import psycopg

from . import enums, read


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _next_id(conn: psycopg.Connection, table: str) -> int:
    """Pull the next id from a table's sequence (AAM Pro has one per table)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT nextval('{table}_id_seq')")
        return int(cur.fetchone()[0])


def _new_uuid() -> str:
    return str(_uuid.uuid4())


def _get_category_id(conn: psycopg.Connection, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM aam_category WHERE lower(name) = lower(%s) LIMIT 1", (name,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No category named {name!r} in aam_category")
        return int(row[0])


def _ensure_default_session_queue(conn: psycopg.Connection, site_id: int) -> int:
    """The 'Default' session queue id — used by every sched_event."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM aam_session_queue WHERE siteid=%s ORDER BY id LIMIT 1",
            (site_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"No aam_session_queue row for site {site_id}; AAM Pro should have seeded one.")
        return int(row[0])


def _ensure_zone_prop(conn: psycopg.Connection, zone_id: int) -> int:
    """Return the aam_prop row id for a zone, creating it with sentinel values if missing.

    Mirrors the shape of zone-prop rows the AAM Pro UI creates: every optional
    field set to -1, everything else NULL or default. ``muteenable`` defaults
    to TRUE (matches existing UI-created destinations).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM aam_prop WHERE objecttype=%s AND objectid=%s LIMIT 1",
            (enums.PROP_OBJ_ZONE, zone_id),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        new_id = _next_id(conn, "aam_prop")
        cur.execute(
            """
            INSERT INTO aam_prop (
                id, uuid, objecttype, objectid,
                audioprofileid, enable, mute, stats, mcast, mcastport, mcastttl,
                crypt, cryptosuite, textenable, textprofileid, displayprofileid,
                textsourceid, mcastdscp, pbeep, audioeqprofileid, muteenable, clientdata
            ) VALUES (
                %s, %s::uuid, %s, %s,
                NULL, -1, -1, -1, -1, 0, -1,
                -1, 0, -1, NULL, NULL,
                NULL, -1, -1, NULL, TRUE, NULL
            )
            """,
            (new_id, _new_uuid(), enums.PROP_OBJ_ZONE, zone_id),
        )
        # Mirror UI: create one prop_category row per existing category (so the
        # destination shows up in volume sliders for music/announcement/paging).
        cur.execute("SELECT id FROM aam_category ORDER BY id")
        cat_ids = [int(r[0]) for r in cur.fetchall()]
        for cid in cat_ids:
            cur.execute(
                """
                INSERT INTO aam_prop_category (
                    id, uuid, propid, categoryid, enable, mute,
                    minvolume, maxvolume, volume, defvolume,
                    textenable, textprofileid, textsourceid
                ) VALUES (
                    nextval('aam_prop_category_id_seq'), %s::uuid, %s, %s, -1, -1,
                    -2147483648, 2147483647, 0, 0,
                    -1, NULL, NULL
                )
                """,
                (_new_uuid(), new_id, cid),
            )
        return new_id


def _ensure_prop_source(
    conn: psycopg.Connection,
    *,
    destination_id: int,
    dev_source_id: int,
) -> int:
    """Return the aam_prop_source id linking a source to a destination, creating if needed."""
    dest_prop_id = _ensure_zone_prop(conn, destination_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM aam_prop_source WHERE propid=%s AND sourceid=%s LIMIT 1",
            (dest_prop_id, dev_source_id),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        new_id = _next_id(conn, "aam_prop_source")
        # Priority pattern from observed rows: ~101000 base, increments by 100 per source.
        # Use a safe default; user can adjust later via UI if priorities matter.
        cur.execute(
            """
            INSERT INTO aam_prop_source (
                id, sourceid, volume, propid, priority, enable, mute, uuid, clientdata
            ) VALUES (
                %s, %s, 0, %s, 101000, -1, -1, %s::uuid, NULL
            )
            """,
            (new_id, dev_source_id, dest_prop_id, _new_uuid()),
        )
        return new_id


# ---------------------------------------------------------------------------
# Stable: physical zones, destinations, templates
# ---------------------------------------------------------------------------

def create_physical_zone(
    conn: psycopg.Connection,
    *,
    site_id: int,
    name: str,
    parent_zone_id: Optional[int] = None,
) -> int:
    """Create a physical zone. Optionally bind it under an existing parent zone."""
    new_id = _next_id(conn, "aam_zone")
    with conn.cursor() as cur:
        # NOTE: clientid/clientdata/description are NULL on existing rows;
        # aam_zone_i1 is UNIQUE(clientid) which only allows multiple NULLs.
        cur.execute(
            """
            INSERT INTO aam_zone (id, type, siteid, name, subtype, description, clientid, clientdata, uuid, apipriority)
            VALUES (%s, %s, %s, %s, 0, NULL, NULL, NULL, %s::uuid, 0)
            """,
            (new_id, enums.ZONE_PHYSICAL, site_id, name, _new_uuid()),
        )
        if parent_zone_id is not None:
            cur.execute(
                """
                INSERT INTO aam_zone_bind (id, zoneid, childid)
                VALUES (nextval('aam_zone_bind_id_seq'), %s, %s)
                """,
                (parent_zone_id, new_id),
            )
    _ensure_zone_prop(conn, new_id)
    return new_id


def create_destination(
    conn: psycopg.Connection,
    *,
    site_id: int,
    name: str,
    physical_zone_ids: Iterable[int] = (),
) -> int:
    """Create a destination (content-routing zone). Bind it to one or more physical zones."""
    new_id = _next_id(conn, "aam_zone")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO aam_zone (id, type, siteid, name, subtype, description, clientid, clientdata, uuid, apipriority)
            VALUES (%s, %s, %s, %s, 0, NULL, NULL, NULL, %s::uuid, 0)
            """,
            (new_id, enums.ZONE_CONTENT, site_id, name, _new_uuid()),
        )
        for pz_id in physical_zone_ids:
            cur.execute(
                """
                INSERT INTO aam_zone_bind (id, zoneid, childid)
                VALUES (nextval('aam_zone_bind_id_seq'), %s, %s)
                """,
                (new_id, pz_id),
            )
    _ensure_zone_prop(conn, new_id)
    return new_id


def create_template(
    conn: psycopg.Connection,
    *,
    site_id: int,
    name: str,
    category: str,  # 'music' | 'announcement' | 'paging'
    source_ids: Iterable[int] = (),
) -> int:
    """Create a template containing the given sources."""
    cat_id = _get_category_id(conn, category)
    tmpl_id = _next_id(conn, "aam_tmpl")
    set_id = _next_id(conn, "aam_tmpl_set")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO aam_tmpl (id, siteid, type, name, categoryid)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (tmpl_id, site_id, enums.TMPL_TYPE_SCHED_CONTENT, name, cat_id),
        )
        cur.execute(
            """
            INSERT INTO aam_tmpl_set (id, tmplid) VALUES (%s, %s)
            """,
            (set_id, tmpl_id),
        )
        for seq, src_id in enumerate(source_ids):
            cur.execute(
                """
                INSERT INTO aam_tmpl_set_source (id, tmplsetid, sourceid, sequence)
                VALUES (nextval('aam_tmpl_set_source_id_seq'), %s, %s, %s)
                """,
                (set_id, src_id, seq),
            )
    return tmpl_id


def delete_template(conn: psycopg.Connection, template_id: int) -> None:
    """Delete a template. ``aam_tmpl_set`` cascades, and ``aam_tmpl_bind`` rows
    are removed by their tmplid FK. Schedulers bound to it are NOT deleted —
    they're left orphaned (pointing at a missing template). Use
    ``delete_event`` separately if you want those gone too."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM aam_tmpl WHERE id = %s", (template_id,))


def delete_destination(conn: psycopg.Connection, destination_id: int) -> None:
    """Delete a destination (content zone). Cascades via aam_zone_bind to drop
    membership of physical zones. Scheduled events pointing at this destination
    will need their prop_sources cleaned up separately — for safety this raises
    if any events still reference the destination."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.name FROM db_itf_schedulers s
            JOIN aam_sched_event se ON se.id = s.id
            LEFT JOIN aam_prop_source ps ON ps.id = se.objectid AND se.objecttype = %s
            LEFT JOIN aam_prop_set pset ON pset.id = se.objectid AND se.objecttype = %s
            LEFT JOIN aam_prop p ON p.id IN (ps.propid, pset.propid)
            WHERE p.objecttype = %s AND p.objectid = %s
            """,
            (enums.SCHED_TYPE_AAM_PROP_SOURCE, enums.SCHED_TYPE_AAM_PROP_SET, enums.PROP_OBJ_ZONE, destination_id),
        )
        events = cur.fetchall()
        if events:
            names = ", ".join(f"{e[1] or e[0]}" for e in events)
            raise RuntimeError(
                f"Destination {destination_id} has {len(events)} scheduled event(s) ({names}); "
                f"delete them first with delete_event."
            )
        cur.execute("DELETE FROM aam_zone WHERE id = %s AND type = %s", (destination_id, enums.ZONE_CONTENT))


# ---------------------------------------------------------------------------
# Stable: exception groups
# ---------------------------------------------------------------------------

def create_exception_group(
    conn: psycopg.Connection,
    *,
    name: str,
    dates: Iterable[date] = (),
    yearly_dates: Iterable[tuple[int, int]] = (),  # list of (month, day) for repeating-year holidays
) -> int:
    """Create a named exception group (blackout dates).

    Args:
        name: human-readable name (e.g. "district_holidays_2026_2027").
        dates: specific one-year exceptions.
        yearly_dates: (month, day) pairs that repeat every year.
    """
    new_id = _next_id(conn, "db_itf_exception_group")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO db_itf_exception_group (id, name) VALUES (%s, %s)",
            (new_id, name),
        )
        for d in dates:
            cur.execute(
                """
                INSERT INTO db_itf_exception_item (id, exceptiongroupid, type, day, month, year)
                VALUES (nextval('db_itf_exception_item_id_seq'), %s, 0, %s, %s, %s)
                """,
                (new_id, d.day, d.month, d.year),
            )
        for month, day in yearly_dates:
            cur.execute(
                """
                INSERT INTO db_itf_exception_item (id, exceptiongroupid, type, day, month, year)
                VALUES (nextval('db_itf_exception_item_id_seq'), %s, 1, %s, %s, 0)
                """,
                (new_id, day, month),
            )
    return new_id


def attach_exception_group(conn: psycopg.Connection, scheduler_id: int, exception_group_id: Optional[int]) -> None:
    """Bind (or unbind, by passing ``None``) an exception group to a scheduler."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE db_itf_schedulers SET exceptiongroupid = %s WHERE id = %s",
            (exception_group_id, scheduler_id),
        )


# ---------------------------------------------------------------------------
# Stable: per-occurrence overrides (calendar table)
# ---------------------------------------------------------------------------

def delete_occurrence(conn: psycopg.Connection, scheduler_id: int, start_time: datetime) -> int:
    """Cancel a single occurrence. Returns number of calendar rows updated.

    The calendar row may or may not exist yet — if the app hasn't materialized
    that occurrence we can't override it (raises). If it exists, mark it
    deleted and null the name (matching the UI's behavior)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE db_itf_scheduler_calendar
               SET deleted = TRUE, name = NULL
             WHERE schedulerid = %s AND starttime = %s
            """,
            (scheduler_id, start_time),
        )
        if cur.rowcount == 0:
            raise LookupError(
                f"No calendar row for scheduler {scheduler_id} at {start_time}. "
                f"The app may not have materialized that occurrence yet."
            )
        return cur.rowcount


def move_occurrence(
    conn: psycopg.Connection,
    scheduler_id: int,
    original_start_time: datetime,
    new_start_time: datetime,
) -> tuple[int, int]:
    """Shift a single occurrence to a different time.

    Implements the UI's two-row pattern: mark the original row deleted+name=NULL,
    insert a new row with exception=TRUE and the scheduler's name preserved.
    Returns ``(rows_marked_deleted, new_row_id)``.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, timeid FROM db_itf_schedulers s "
            "JOIN db_itf_scheduler_calendar c ON c.schedulerid = s.id "
            "WHERE s.id = %s AND c.starttime = %s",
            (scheduler_id, original_start_time),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(
                f"No calendar row for scheduler {scheduler_id} at {original_start_time}."
            )
        sched_name, time_id = row
        cur.execute(
            """
            UPDATE db_itf_scheduler_calendar
               SET deleted = TRUE, name = NULL
             WHERE schedulerid = %s AND starttime = %s
            """,
            (scheduler_id, original_start_time),
        )
        deleted_count = cur.rowcount
        new_cal_id = _next_id(conn, "db_itf_scheduler_calendar")
        cur.execute(
            """
            INSERT INTO db_itf_scheduler_calendar
                (id, name, schedulerid, timeid, starttime, length, deleted, exception)
            VALUES (%s, %s, %s, %s, %s, 0, FALSE, TRUE)
            """,
            (new_cal_id, sched_name, scheduler_id, time_id, new_start_time),
        )
        return deleted_count, new_cal_id


# ---------------------------------------------------------------------------
# Stable: delete a whole scheduled event
# ---------------------------------------------------------------------------

def delete_event(conn: psycopg.Connection, scheduler_id: int) -> None:
    """Remove a scheduled event entirely. Cascades through:
      - aam_sched_event (FK on id)
      - db_itf_scheduler_times (schedulerid FK)
      - db_itf_scheduler_calendar (schedulerid FK)
      - db_itf_schedulers_gen (id FK)
    aam_tmpl_bind rows pointing at this scheduler are cleaned up manually
    (no FK from objectid).
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM aam_tmpl_bind WHERE objecttype = %s AND objectid = %s",
            (enums.TMPL_BIND_SCHED, scheduler_id),
        )
        cur.execute("DELETE FROM db_itf_schedulers WHERE id = %s", (scheduler_id,))


# ---------------------------------------------------------------------------
# Experimental: create a scheduled event (non-template)
# ---------------------------------------------------------------------------

def create_event(
    conn: psycopg.Connection,
    *,
    name: str,
    destination_id: int,
    source_id: int,
    days_of_week: Iterable[str],
    times: Iterable[tuple[int, int]],
    start_date: date,
    end_date: Optional[date] = None,
    enabled: bool = True,
) -> int:
    """EXPERIMENTAL — create a non-template recurring weekly event.

    Produces the row pattern observed for the Saturday-morning-announcement
    test case: one PROP_SOURCE scheduler + one sched_event + N scheduler_times
    + a prop_source linking the source to the destination (created if absent).

    Does NOT populate ``db_itf_scheduler_calendar`` — relies on AAM Pro's
    background regenerator to materialize occurrences from the new rule.
    Verify this assumption before trusting at scale.
    """
    if not list(days_of_week):
        raise ValueError("days_of_week must contain at least one day")
    times_list = list(times)
    if not times_list:
        raise ValueError("times must contain at least one (hour, minute) pair")

    daymask = enums.days_to_daymask(list(days_of_week))

    # Find the site for queue lookup via the destination zone.
    with conn.cursor() as cur:
        cur.execute("SELECT siteid FROM aam_zone WHERE id = %s", (destination_id,))
        row = cur.fetchone()
        if not row:
            raise LookupError(f"No zone (destination) with id={destination_id}")
        site_id = int(row[0])
    queue_id = _ensure_default_session_queue(conn, site_id)
    prop_source_id = _ensure_prop_source(conn, destination_id=destination_id, dev_source_id=source_id)

    sched_id = _next_id(conn, "db_itf_schedulers")
    end_type = enums.END_BY_DATE if end_date else enums.END_NEVER
    end_dt = (
        datetime(end_date.year, end_date.month, end_date.day)
        if end_date
        else datetime(1601, 1, 1)
    )
    start_dt = datetime(start_date.year, start_date.month, start_date.day)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO db_itf_schedulers (
                id, extid, type, started, endscheduler, generateid, enable, name,
                negative, externallength, openinghoursid, exceptiongroupid,
                startdate, endtype, enddate, endoccurencies,
                repeattype, dayilyrecure, weeklyrecure, weeklydaymask,
                monthlydayinmonth, monthlyweekinmonth, monthlydaymask, monthlyrecure,
                yearlydayofmonth, yearlyweekinmonth, yearlydaymask, yearlymonth, yearlyrecure
            ) VALUES (
                %s, %s, %s, FALSE, '9999-01-01 00:00:00', 0, %s, %s,
                FALSE, 0, NULL, NULL,
                %s, %s, %s, 0,
                %s, 0, 1, %s,
                0, 0, 0, 0,
                0, 0, 0, 0, 0
            )
            """,
            (
                sched_id, sched_id, enums.SCHED_TYPE_AAM_PROP_SOURCE,
                enabled, name,
                start_dt, end_type, end_dt,
                enums.REPEAT_WEEKLY, daymask,
            ),
        )
        # The aam_sched_event row — id matches scheduler id (FK).
        cur.execute(
            """
            INSERT INTO aam_sched_event (
                id, objecttype, objectid, mode, queueid, lifetime, step, textenable, textprofileid, textsourceid
            ) VALUES (
                %s, %s, %s, %s, %s, -1, -1, -1, NULL, NULL
            )
            """,
            (sched_id, enums.SCHED_TYPE_AAM_PROP_SOURCE, prop_source_id, enums.SCHED_MODE_AUTO_RESET, queue_id),
        )
        for hour, minute in times_list:
            cur.execute(
                """
                INSERT INTO db_itf_scheduler_times (
                    id, schedulerid, timeschedstarttype, timeschedendtype,
                    relativestartoffset, relativeendoffset,
                    timehourstart, timeminstart, length
                ) VALUES (
                    nextval('db_itf_scheduler_times_id_seq'), %s, 0, 0, 0, 0, %s, %s, 0
                )
                """,
                (sched_id, hour, minute),
            )
    return sched_id


# ---------------------------------------------------------------------------
# Experimental: apply a template to a destination on a schedule
# ---------------------------------------------------------------------------

def apply_template(
    conn: psycopg.Connection,
    *,
    template_id: int,
    destination_id: int,
    name: str,
    days_of_week: Iterable[str],
    times: Iterable[tuple[int, int]],
    start_date: date,
    end_date: Optional[date] = None,
    enabled: bool = True,
) -> int:
    """EXPERIMENTAL — bind a template to a destination with a recurrence.

    Mirrors the row pattern observed for bell01/bell02. Creates the
    PROP_SOURCE scheduler with the recurrence + times, plus aam_tmpl_bind
    pointing back at the new scheduler.

    Open question (not yet verified): the UI also creates a paired TMPL_SET
    "stub" scheduler row (type=983043, no recurrence). We *don't* create it
    here — testing should confirm whether AAM Pro requires it or just creates
    it as a UI artifact. If the bell doesn't fire after applying, that's the
    first thing to suspect.

    Returns the new PROP_SOURCE scheduler id.
    """
    # Fetch the template's sources — we'll create a prop_source for each one
    # so the destination has access to the source's content.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tss.sourceid
            FROM aam_tmpl_set ts
            JOIN aam_tmpl_set_source tss ON tss.tmplsetid = ts.id
            WHERE ts.tmplid = %s
            ORDER BY tss.sequence
            """,
            (template_id,),
        )
        source_ids = [int(r[0]) for r in cur.fetchall()]
    if not source_ids:
        raise ValueError(f"Template {template_id} has no sources")

    # Use the first source as the prop_source target for the sched_event.
    # AAM Pro UI creates one prop_source per (destination, source) pair; the
    # sched_event points at one of them. Multi-source templates may need
    # extra handling — flag for verification.
    primary_source_id = source_ids[0]
    sched_id = create_event(
        conn,
        name=name,
        destination_id=destination_id,
        source_id=primary_source_id,
        days_of_week=days_of_week,
        times=times,
        start_date=start_date,
        end_date=end_date,
        enabled=enabled,
    )

    # Bind the template to the new scheduler.
    bind_id = _next_id(conn, "aam_tmpl_bind")
    with conn.cursor() as cur:
        # Find the next schedulesequence for this template (1-based).
        cur.execute(
            "SELECT COALESCE(MAX(schedulesequence), 0) + 1 FROM aam_tmpl_bind WHERE tmplid = %s",
            (template_id,),
        )
        next_seq = int(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO aam_tmpl_bind (id, schedulesequence, tmplid, objecttype, objectid)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (bind_id, next_seq, template_id, enums.TMPL_BIND_SCHED, sched_id),
        )
    # Also wire up prop_sources for any *additional* template sources so they
    # exist on the destination (the sched_event only references one, but the
    # destination should be able to play any of the template's sources).
    for sid in source_ids[1:]:
        _ensure_prop_source(conn, destination_id=destination_id, dev_source_id=sid)

    return sched_id
