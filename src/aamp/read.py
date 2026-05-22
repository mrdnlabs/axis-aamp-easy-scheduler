"""Read-side functions that turn raw DB rows into typed domain models.

Every public function takes a psycopg ``Connection`` and returns one or more
Pydantic models from :mod:`aamp.models`. These are the primary callables that
get wrapped as MCP tools.

Design notes
------------
* We deliberately filter out the AAM Pro generic-scheduler types 0-2 (which
  belong to AXIS PBX features); only types 983040-983043 are AAM.
* For ``list_schedule_events`` we only surface *overrides* (calendar rows
  with deleted=True or exception=True) rather than the full materialized
  occurrence list, which would balloon LLM context for no benefit.
* The TMPL_SET stub scheduler rows (type=983043) are merged into their paired
  PROP_SOURCE event so the LLM sees one logical "event" per user-visible
  schedule, not two parallel rows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import psycopg

from . import enums
from .db import dict_rows
from .models import (
    Category,
    Destination,
    EndKind,
    ExceptionGroup,
    ExceptionItem,
    Occurrence,
    OpeningHours,
    OpeningHoursItem,
    PhysicalZone,
    Recurrence,
    RepeatKind,
    ScheduleEvent,
    SchedEventKind,
    Site,
    Source,
    Template,
    TimeAnchor,
    TimeOfDay,
    Zone,
    ZoneKind,
)

# ---------------------------------------------------------------------------
# Category lookup (used to translate categoryid → 'music'/'announcement'/'paging')
# ---------------------------------------------------------------------------

def load_categories(conn: psycopg.Connection) -> dict[int, Category]:
    """Map ``aam_category.id`` → category name."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM aam_category")
        out: dict[int, Category] = {}
        for cid, name in cur.fetchall():
            lname = (name or "").lower()
            if lname in ("music", "announcement", "paging"):
                out[cid] = lname  # type: ignore[assignment]
            else:
                out[cid] = "unknown"
        return out


# ---------------------------------------------------------------------------
# Sites & zones
# ---------------------------------------------------------------------------

def list_sites(conn: psycopg.Connection) -> list[Site]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, organizationname FROM aam_site ORDER BY id")
        return [Site(id=sid, name=name, organization=org) for sid, name, org in cur.fetchall()]


def _zone_kind_from_int(t: int) -> ZoneKind:
    name = enums.ZONE_TYPE_NAMES.get(t)
    return name if name in {"physical", "destination", "volume", "web_audio_session", "web_listen_session", "paging"} else "unknown"  # type: ignore[return-value]


def _load_zone_relationships(conn: psycopg.Connection) -> dict[int, dict[str, list[int]]]:
    """Return ``{zone_id: {'parents': [...], 'children': [...]}}`` from aam_zone_bind."""
    rels: dict[int, dict[str, list[int]]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT zoneid, childid FROM aam_zone_bind")
        for parent_id, child_id in cur.fetchall():
            rels.setdefault(parent_id, {"parents": [], "children": []})["children"].append(child_id)
            rels.setdefault(child_id, {"parents": [], "children": []})["parents"].append(parent_id)
    return rels


def list_zones(conn: psycopg.Connection, site_id: Optional[int] = None) -> list[Zone]:
    """All zones (physical, destination, volume, etc.) with parent/child relations resolved."""
    rels = _load_zone_relationships(conn)
    with conn.cursor() as cur:
        if site_id is None:
            cur.execute("SELECT id, type, siteid, name, description FROM aam_zone ORDER BY id")
        else:
            cur.execute(
                "SELECT id, type, siteid, name, description FROM aam_zone WHERE siteid=%s ORDER BY id",
                (site_id,),
            )
        out: list[Zone] = []
        for zid, ztype, sid, name, desc in cur.fetchall():
            r = rels.get(zid, {"parents": [], "children": []})
            out.append(
                Zone(
                    id=zid,
                    site_id=sid,
                    kind=_zone_kind_from_int(ztype),
                    name=name,
                    description=desc,
                    parent_zone_ids=r["parents"],
                    child_zone_ids=r["children"],
                )
            )
        return out


def list_physical_zones(conn: psycopg.Connection, site_id: Optional[int] = None) -> list[PhysicalZone]:
    return [
        PhysicalZone(**z.model_dump(exclude={"kind"}))
        for z in list_zones(conn, site_id)
        if z.kind == "physical"
    ]


def list_destinations(conn: psycopg.Connection, site_id: Optional[int] = None) -> list[Destination]:
    """Content-routing zones (type=1). Members come from zone_bind where the destination is parent."""
    all_zones = list_zones(conn, site_id)
    physical_ids = {z.id for z in all_zones if z.kind == "physical"}
    out: list[Destination] = []
    for z in all_zones:
        if z.kind != "destination":
            continue
        members = [c for c in z.child_zone_ids if c in physical_ids]
        out.append(
            Destination(
                id=z.id,
                site_id=z.site_id,
                name=z.name,
                description=z.description,
                parent_zone_ids=z.parent_zone_ids,
                child_zone_ids=z.child_zone_ids,
                member_physical_zone_ids=members,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def list_sources(conn: psycopg.Connection) -> list[Source]:
    categories = load_categories(conn)
    # Pull underlying library file paths via aam_playlist + aam_playlist_item + aam_library_item.
    # A source of type=34 (playlist) wraps one or more library files; we surface the first file's path.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ds.id, ds.name, ds.categoryid, ds.type, ds.propid, ds.devid,
                li.path
            FROM aam_dev_source ds
            LEFT JOIN aam_playlist_item pi ON pi.playlistid = ds.id
            LEFT JOIN aam_library_item li ON li.id = pi.fileid
            ORDER BY ds.id
            """
        )
        rows = cur.fetchall()
    # Deduplicate by source id (one row per playlist item joined, take the first path).
    seen: dict[int, Source] = {}
    for sid, name, cat_id, stype, prop_id, dev_id, path in rows:
        if sid in seen:
            continue
        seen[sid] = Source(
            id=sid,
            name=name,
            category=categories.get(cat_id, "unknown"),
            source_type=enums.SOURCE_TYPE_NAMES.get(stype, f"type_{stype}"),
            library_path=path,
            prop_id=prop_id,
            device_id=dev_id,
        )
    return list(seen.values())


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def list_templates(conn: psycopg.Connection, site_id: Optional[int] = None) -> list[Template]:
    categories = load_categories(conn)
    where = "" if site_id is None else " WHERE t.siteid = %s"
    params: tuple = () if site_id is None else (site_id,)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT t.id, t.siteid, t.name, t.categoryid,
                   array_remove(array_agg(tss.sourceid ORDER BY tss.sequence), NULL) AS source_ids
            FROM aam_tmpl t
            LEFT JOIN aam_tmpl_set ts ON ts.tmplid = t.id
            LEFT JOIN aam_tmpl_set_source tss ON tss.tmplsetid = ts.id
            {where}
            GROUP BY t.id, t.siteid, t.name, t.categoryid
            ORDER BY t.id
            """,
            params,
        )
        return [
            Template(
                id=tid,
                site_id=sid,
                name=name,
                category=categories.get(cat_id, "unknown"),
                source_ids=list(source_ids or []),
            )
            for tid, sid, name, cat_id, source_ids in cur.fetchall()
        ]


# ---------------------------------------------------------------------------
# Schedule events
# ---------------------------------------------------------------------------

def _decode_sentinel_date(d: Optional[datetime]) -> Optional[date]:
    """Translate AAM Pro's sentinel datetimes (1601-01-01 / 9999-01-01) into ``None``."""
    if d is None:
        return None
    if d.year <= 1601 or d.year >= 9999:
        return None
    return d.date()


def _repeat_kind(t: int) -> RepeatKind:
    name = enums.REPEAT_NAMES.get(t, "none")
    return name  # type: ignore[return-value]


def _end_kind(t: int) -> EndKind:
    return {0: "never", 1: "after_occurrences", 2: "by_date"}.get(t, "never")  # type: ignore[return-value]


def _sched_event_kind(t: int) -> SchedEventKind:
    return {
        enums.SCHED_TYPE_AAM_PROP_SOURCE: "prop_source",
        enums.SCHED_TYPE_AAM_PROP_SET: "prop_set",
        enums.SCHED_TYPE_AAM_TMPL_SET: "tmpl_set",
    }.get(t, "unknown")  # type: ignore[return-value]


def _time_anchor(t: int) -> TimeAnchor:
    return {0: "absolute", 1: "opening_start", 2: "opening_end"}.get(t, "absolute")  # type: ignore[return-value]


def _resolve_destination_id(conn: psycopg.Connection, sched_event_type: int, object_id: int) -> Optional[int]:
    """Follow the prop bridge to find the destination zone for a sched_event."""
    with conn.cursor() as cur:
        if sched_event_type == enums.SCHED_TYPE_AAM_PROP_SOURCE:
            cur.execute(
                """
                SELECT p.objectid
                FROM aam_prop_source ps
                JOIN aam_prop p ON p.id = ps.propid
                WHERE ps.id = %s AND p.objecttype = %s
                """,
                (object_id, enums.PROP_OBJ_ZONE),
            )
        elif sched_event_type == enums.SCHED_TYPE_AAM_PROP_SET:
            cur.execute(
                """
                SELECT p.objectid
                FROM aam_prop_set pset
                JOIN aam_prop p ON p.id = pset.propid
                WHERE pset.id = %s AND p.objecttype = %s
                """,
                (object_id, enums.PROP_OBJ_ZONE),
            )
        elif sched_event_type == enums.SCHED_TYPE_AAM_TMPL_SET:
            # tmpl_set itself isn't bound to a destination — the PROP_SOURCE paired
            # scheduler is. Return None and let the caller dedupe.
            return None
        else:
            return None
        row = cur.fetchone()
        return row[0] if row else None


def _resolve_source_id(conn: psycopg.Connection, sched_event_type: int, object_id: int) -> Optional[int]:
    if sched_event_type != enums.SCHED_TYPE_AAM_PROP_SOURCE:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT sourceid FROM aam_prop_source WHERE id = %s", (object_id,))
        row = cur.fetchone()
        return row[0] if row else None


def _resolve_template_id(conn: psycopg.Connection, scheduler_id: int) -> Optional[int]:
    """Find a template bound to this scheduler via aam_tmpl_bind."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tmplid FROM aam_tmpl_bind
            WHERE objecttype = %s AND objectid = %s
            LIMIT 1
            """,
            (enums.TMPL_BIND_SCHED, scheduler_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def list_schedule_events(
    conn: psycopg.Connection,
    destination_id: Optional[int] = None,
    *,
    include_internal_stubs: bool = False,
) -> list[ScheduleEvent]:
    """All scheduled audio events (recurrence + times + content target).

    Args:
        destination_id: filter to events that fire on this destination.
        include_internal_stubs: include the TMPL_SET stub scheduler rows that
            mirror PROP_SOURCE rows. Off by default — those are internal.
    """
    # Pull all AAM schedulers (filter out PBX scheduler types <983040).
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.type, s.name, s.enable, s.repeattype, s.weeklydaymask, s.weeklyrecure,
                   s.dayilyrecure, s.startdate, s.endtype, s.enddate, s.endoccurencies,
                   s.openinghoursid, s.exceptiongroupid,
                   s.monthlydayinmonth, s.monthlyweekinmonth, s.monthlydaymask, s.monthlyrecure,
                   s.yearlydayofmonth, s.yearlyweekinmonth, s.yearlydaymask, s.yearlymonth, s.yearlyrecure,
                   se.objecttype, se.objectid
            FROM db_itf_schedulers s
            JOIN aam_sched_event se ON se.id = s.id
            WHERE s.type >= 983040
            ORDER BY s.id
            """
        )
        sched_rows = dict_rows(cur)

    # Pull all times in one pass.
    times_by_sched: dict[int, list[TimeOfDay]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, schedulerid, timehourstart, timeminstart, length,
                   timeschedstarttype, timeschedendtype, relativestartoffset, relativeendoffset
            FROM db_itf_scheduler_times
            ORDER BY schedulerid, id
            """
        )
        for r in dict_rows(cur):
            times_by_sched.setdefault(r["schedulerid"], []).append(
                TimeOfDay(
                    id=r["id"],
                    hour=r["timehourstart"],
                    minute=r["timeminstart"],
                    duration_minutes=r["length"],
                    start_anchor=_time_anchor(r["timeschedstarttype"]),
                    end_anchor=_time_anchor(r["timeschedendtype"]),
                    start_offset_minutes=r["relativestartoffset"],
                    end_offset_minutes=r["relativeendoffset"],
                )
            )

    # Pull only the overrides from the calendar (deleted=True OR exception=True).
    overrides_by_sched: dict[int, list[Occurrence]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, schedulerid, timeid, starttime, length, deleted, exception, name
            FROM db_itf_scheduler_calendar
            WHERE deleted = TRUE OR exception = TRUE
            ORDER BY schedulerid, starttime
            """
        )
        for r in dict_rows(cur):
            overrides_by_sched.setdefault(r["schedulerid"], []).append(
                Occurrence(
                    id=r["id"],
                    scheduler_id=r["schedulerid"],
                    time_id=r["timeid"],
                    start_time=r["starttime"],
                    duration_minutes=r["length"],
                    deleted=r["deleted"],
                    exception=r["exception"],
                    name=r["name"],
                )
            )

    # Build events.
    out: list[ScheduleEvent] = []
    for r in sched_rows:
        kind = _sched_event_kind(r["type"])
        if kind == "tmpl_set" and not include_internal_stubs:
            continue
        days = enums.daymask_to_days(r["weeklydaymask"]) if r["repeattype"] == enums.REPEAT_WEEKLY else []
        rec = Recurrence(
            kind=_repeat_kind(r["repeattype"]),
            days_of_week=days,
            every_n_days=r["dayilyrecure"] or 1,
            every_n_weeks=r["weeklyrecure"] or 1,
            every_n_months=r["monthlyrecure"] or 1,
            every_n_years=r["yearlyrecure"] or 1,
            monthly_day=r["monthlydayinmonth"],
            monthly_week=r["monthlyweekinmonth"],
            monthly_days_mask=r["monthlydaymask"],
            yearly_month=r["yearlymonth"],
            yearly_day=r["yearlydayofmonth"],
            yearly_week=r["yearlyweekinmonth"],
            yearly_days_mask=r["yearlydaymask"],
            start_date=_decode_sentinel_date(r["startdate"]),
            end_kind=_end_kind(r["endtype"]),
            end_date=_decode_sentinel_date(r["enddate"]),
            end_after_occurrences=r["endoccurencies"] or None,
        )
        ev = ScheduleEvent(
            id=r["id"],
            name=r["name"],
            enabled=r["enable"],
            kind=kind,
            destination_id=_resolve_destination_id(conn, r["objecttype"], r["objectid"]),
            source_id=_resolve_source_id(conn, r["objecttype"], r["objectid"]),
            template_id=_resolve_template_id(conn, r["id"]),
            recurrence=rec,
            times=times_by_sched.get(r["id"], []),
            overrides=overrides_by_sched.get(r["id"], []),
            opening_hours_id=r["openinghoursid"],
            exception_group_id=r["exceptiongroupid"],
        )
        if destination_id is not None and ev.destination_id != destination_id:
            continue
        out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Opening hours & exception groups
# ---------------------------------------------------------------------------

def list_opening_hours(conn: psycopg.Connection) -> list[OpeningHours]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM db_itf_opening_hours ORDER BY id")
        hours = {oid: OpeningHours(id=oid, name=name) for oid, name in cur.fetchall()}
        cur.execute(
            """
            SELECT id, openinghoursid, daymask, timehourstart, timeminstart, length, active
            FROM db_itf_opening_hours_items ORDER BY openinghoursid, id
            """
        )
        for iid, oh_id, mask, h, m, length, active in cur.fetchall():
            if oh_id in hours:
                hours[oh_id].items.append(
                    OpeningHoursItem(
                        id=iid,
                        days_of_week=enums.daymask_to_days(mask),
                        hour_start=h,
                        minute_start=m,
                        length_minutes=length,
                        active=active,
                    )
                )
    return list(hours.values())


def list_exception_groups(conn: psycopg.Connection) -> list[ExceptionGroup]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM db_itf_exception_group ORDER BY id")
        groups = {gid: ExceptionGroup(id=gid, name=name) for gid, name in cur.fetchall()}
        cur.execute(
            """
            SELECT id, exceptiongroupid, type, day, month, year
            FROM db_itf_exception_item ORDER BY exceptiongroupid, id
            """
        )
        for iid, gid, etype, day, month, year in cur.fetchall():
            if gid in groups:
                kind = "one_year" if etype == 0 else "every_year"
                groups[gid].items.append(
                    ExceptionItem(
                        id=iid,
                        exception_group_id=gid,
                        kind=kind,  # type: ignore[arg-type]
                        day=day,
                        month=month,
                        year=year,
                    )
                )
    return list(groups.values())
