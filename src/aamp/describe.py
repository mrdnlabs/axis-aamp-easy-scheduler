"""Render the current AAM Pro state as human-readable markdown.

This is the bridge from raw DB rows to the intent-doc format. A site
description produced here is meant to be readable by both humans and the
LLM, and ideally to map nearly 1:1 to the user's mental model.
"""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from typing import Optional

import psycopg

from . import enums
from . import read
from .models import (
    Destination,
    Occurrence,
    PhysicalZone,
    Recurrence,
    ScheduleEvent,
    Source,
    Template,
    TimeOfDay,
)


def _fmt_time(t: TimeOfDay) -> str:
    base = f"{t.hour:02d}:{t.minute:02d}"
    if t.start_anchor == "opening_start":
        sign = "+" if t.start_offset_minutes >= 0 else "-"
        return f"opening start {sign}{abs(t.start_offset_minutes)}min"
    if t.start_anchor == "opening_end":
        sign = "+" if t.start_offset_minutes >= 0 else "-"
        return f"opening end {sign}{abs(t.start_offset_minutes)}min"
    if t.duration_minutes == 1440:
        return "all day (24h)"
    if t.duration_minutes:
        return f"{base} (lasts {t.duration_minutes}min)"
    return base


def _fmt_recurrence(r: Recurrence) -> str:
    """Render a recurrence rule as a short English phrase."""
    if r.kind == "none":
        # Common for the TMPL_SET stub rows; filter shouldn't reach here usually.
        return "(no recurrence)"
    if r.kind == "daily_working_days":
        body = "every working day"
    elif r.kind == "daily_every_n":
        body = "every day" if r.every_n_days == 1 else f"every {r.every_n_days} days"
    elif r.kind == "weekly":
        days = ", ".join(r.days_of_week) if r.days_of_week else "(no days)"
        if r.every_n_weeks > 1:
            body = f"every {r.every_n_weeks} weeks on {days}"
        else:
            body = f"weekly on {days}"
    elif r.kind == "monthly_specific":
        body = f"monthly on day {r.monthly_day}"
    elif r.kind == "monthly_weekday":
        body = f"monthly on week {r.monthly_week}, days mask {r.monthly_days_mask}"
    elif r.kind == "yearly_specific":
        body = f"yearly on {r.yearly_month}/{r.yearly_day}"
    elif r.kind == "yearly_weekday":
        body = f"yearly in month {r.yearly_month}, week {r.yearly_week}"
    else:
        body = r.kind

    parts = [body]
    if r.start_date:
        parts.append(f"starting {r.start_date.isoformat()}")
    if r.end_kind == "by_date" and r.end_date:
        parts.append(f"until {r.end_date.isoformat()}")
    elif r.end_kind == "after_occurrences" and r.end_after_occurrences:
        parts.append(f"for {r.end_after_occurrences} occurrences")
    return ", ".join(parts)


def _fmt_override(o: Occurrence, indent: str = "      ") -> str:
    if o.deleted and not o.exception:
        return f"{indent}- cancelled: {o.start_time:%Y-%m-%d %H:%M}"
    if o.exception and not o.deleted:
        return f"{indent}- one-off / moved: {o.start_time:%Y-%m-%d %H:%M}"
    return f"{indent}- override {o.start_time:%Y-%m-%d %H:%M} (deleted={o.deleted}, exception={o.exception})"


def describe_destination(
    dest: Destination,
    *,
    physical_zones_by_id: dict[int, PhysicalZone],
    events: list[ScheduleEvent],
    templates_by_id: dict[int, Template],
    sources_by_id: dict[int, Source],
) -> str:
    """Render one destination's full configuration as markdown."""
    out = StringIO()
    name = dest.name or f"destination #{dest.id}"
    out.write(f"### {name}\n\n")

    if dest.member_physical_zone_ids:
        zone_names = [
            (physical_zones_by_id.get(zid).name if zid in physical_zones_by_id else None)
            or f"zone #{zid}"
            for zid in dest.member_physical_zone_ids
        ]
        out.write(f"- Physical zones: {', '.join(zone_names)}\n")
    else:
        out.write("- Physical zones: (none assigned)\n")

    dest_events = [e for e in events if e.destination_id == dest.id]
    if not dest_events:
        out.write("- No scheduled events.\n\n")
        return out.getvalue()

    out.write("- Scheduled events:\n")
    for ev in dest_events:
        ev_name = ev.name or f"event #{ev.id}"
        source_name = (
            (sources_by_id.get(ev.source_id).name if ev.source_id in sources_by_id else None)
            or (f"source #{ev.source_id}" if ev.source_id else None)
        )
        template_name = (
            (templates_by_id.get(ev.template_id).name if ev.template_id in templates_by_id else None)
            or (f"template #{ev.template_id}" if ev.template_id else None)
        )

        head = f"  - **{ev_name}** ({ev.kind})"
        if not ev.enabled:
            head += " [disabled]"
        out.write(head + "\n")

        rec = _fmt_recurrence(ev.recurrence)
        out.write(f"    - When: {rec}\n")
        if ev.times:
            times_str = ", ".join(_fmt_time(t) for t in ev.times)
            out.write(f"    - Times: {times_str}\n")
        if source_name:
            out.write(f"    - Plays: {source_name}\n")
        if template_name:
            out.write(f"    - Template: {template_name}\n")
        if ev.opening_hours_id is not None:
            out.write(f"    - Anchored to opening-hours #{ev.opening_hours_id}\n")
        if ev.exception_group_id is not None:
            out.write(f"    - Honors exception-group #{ev.exception_group_id}\n")
        if ev.overrides:
            out.write(f"    - Per-occurrence edits ({len(ev.overrides)}):\n")
            for o in ev.overrides:
                out.write(_fmt_override(o) + "\n")
    out.write("\n")
    return out.getvalue()


def describe_site_schedule(conn: psycopg.Connection, site_id: Optional[int] = None) -> str:
    """Build a full markdown overview of one site (or the only site) suitable for an intent doc."""
    sites = read.list_sites(conn)
    if not sites:
        return "_(no sites)_\n"
    if site_id is None:
        site = sites[0]
    else:
        candidates = [s for s in sites if s.id == site_id]
        if not candidates:
            return f"_(no site with id={site_id})_\n"
        site = candidates[0]

    physical = read.list_physical_zones(conn, site.id)
    physical_by_id = {z.id for z in physical}
    physical_models = {z.id: z for z in physical}
    destinations = read.list_destinations(conn, site.id)
    sources = read.list_sources(conn)
    sources_by_id = {s.id: s for s in sources}
    templates = read.list_templates(conn, site.id)
    templates_by_id = {t.id: t for t in templates}
    events = read.list_schedule_events(conn)
    opening_hours = read.list_opening_hours(conn)
    exception_groups = read.list_exception_groups(conn)

    out = StringIO()
    out.write(f"# {site.name or 'Site'} (site #{site.id})\n\n")
    out.write(f"_Snapshot generated {datetime.now():%Y-%m-%d %H:%M} from the live AAM Pro database._\n\n")

    # Physical layout
    out.write("## Physical zones\n\n")
    if not physical:
        out.write("_(none)_\n\n")
    else:
        # Render as a flat list with parent hints (no full tree for MVP).
        def _zone_label(z: PhysicalZone) -> str:
            return z.name or f"zone #{z.id}"

        roots = [z for z in physical if not any(p in physical_by_id for p in z.parent_zone_ids)]
        seen: set[int] = set()

        def render_tree(z: PhysicalZone, depth: int) -> None:
            if z.id in seen:
                return
            seen.add(z.id)
            out.write(f"{'  ' * depth}- {_zone_label(z)}\n")
            for c in z.child_zone_ids:
                child = physical_models.get(c)
                if child:
                    render_tree(child, depth + 1)

        for r in roots:
            render_tree(r, 0)
        # Any orphans (shouldn't happen but be defensive)
        for z in physical:
            if z.id not in seen:
                out.write(f"- {_zone_label(z)} _(orphan)_\n")
        out.write("\n")

    # Destinations
    out.write("## Destinations\n\n")
    if not destinations:
        out.write("_(none)_\n\n")
    else:
        for d in destinations:
            out.write(
                describe_destination(
                    d,
                    physical_zones_by_id=physical_models,
                    events=events,
                    templates_by_id=templates_by_id,
                    sources_by_id=sources_by_id,
                )
            )

    # Templates
    out.write("## Templates\n\n")
    if not templates:
        out.write("_(none)_\n\n")
    else:
        for t in templates:
            src_names = [
                (sources_by_id.get(sid).name if sid in sources_by_id else None) or f"source #{sid}"
                for sid in t.source_ids
            ]
            out.write(f"- **{t.name or f'template #{t.id}'}** ({t.category}): plays {', '.join(src_names) or '(no sources)'}\n")
        out.write("\n")

    # Opening hours
    out.write("## Opening hours\n\n")
    if not opening_hours:
        out.write("_(none)_\n\n")
    else:
        for oh in opening_hours:
            out.write(f"- **{oh.name or f'opening-hours #{oh.id}'}**\n")
            for it in oh.items:
                days = ", ".join(it.days_of_week) or "(no days)"
                state = "" if it.active else " [inactive]"
                end_h, end_m = divmod(it.minute_start + it.length_minutes, 60)
                out.write(
                    f"  - {days}: {it.hour_start:02d}:{it.minute_start:02d} for {it.length_minutes}min"
                    f"{state}\n"
                )
        out.write("\n")

    # Exception groups
    out.write("## Exception groups\n\n")
    user_facing = [g for g in exception_groups if g.name] or exception_groups
    if not user_facing:
        out.write("_(none)_\n\n")
    else:
        for g in user_facing:
            out.write(f"- **{g.name or f'exception-group #{g.id}'}**: {len(g.items)} dates\n")
            for it in g.items[:10]:
                date_str = f"{it.year:04d}-{it.month:02d}-{it.day:02d}" if it.kind == "one_year" else f"every year on {it.month:02d}-{it.day:02d}"
                out.write(f"  - {date_str}\n")
            if len(g.items) > 10:
                out.write(f"  - ... and {len(g.items) - 10} more\n")
        out.write("\n")

    return out.getvalue()
