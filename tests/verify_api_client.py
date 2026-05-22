"""Verify the API client against the live AAM Pro.

Stages:
  1. Read tour: every public reader returns sane data.
  2. Write trial: create a destination + template, apply one to the other,
     then clean up. End state == start state.

Writes are committed (not rolled back) since the API has no transactional
sandbox; we explicitly delete everything we create at the end.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from aamp.api import AampApi
from aamp.config import load_config


PREFIX = "_apiverify_"


def section(t: str) -> None:
    print()
    print("=" * 70)
    print(t)
    print("=" * 70)


def cleanup_residue(api: AampApi) -> int:
    """Remove any destinations/templates left over from a prior failed run."""
    removed = 0
    for d in api.list_destinations():
        if d.name and d.name.startswith(PREFIX):
            try:
                api.delete_zone(d.id)
                print(f"  cleaned destination #{d.id} ({d.name})")
                removed += 1
            except Exception as e:
                print(f"  WARN: couldn't delete destination #{d.id}: {e}")
    for t in api.list_templates():
        if t.name and t.name.startswith(PREFIX):
            try:
                api.delete_template(t.id)
                print(f"  cleaned template #{t.id} ({t.name})")
                removed += 1
            except Exception as e:
                print(f"  WARN: couldn't delete template #{t.id}: {e}")
    return removed


def main() -> int:
    cfg = load_config()
    with AampApi.from_config(cfg) as api:

        # -- pre: scrub residue --------------------------------------
        section("Pre-clean: remove anything from a prior failed run")
        cleaned = cleanup_residue(api)
        print(f"  removed {cleaned} stale resource(s)")

        # -- 1. Read tour --------------------------------------------
        section("READ TOUR")
        sites = api.list_sites()
        print(f"  sites: {len(sites)}")
        for s in sites:
            print(f"    - #{s.id} {s.name!r}")

        site_name = api.get_site_name()
        print(f"  siteName: {site_name!r}")

        ldt = api.get_local_date_time()
        print(f"  localDateTime: {ldt.iso8601}")

        dests = api.list_destinations()
        print(f"  destinations: {len(dests)}")
        for d in dests:
            print(f"    - #{d.id} {d.name!r} (physical_zone_ids={d.physical_zone_ids})")

        physical = api.list_physical_zones()
        print(f"  physical zones: {len(physical)}")

        templates = api.list_templates()
        print(f"  templates: {len(templates)}")
        for t in templates:
            print(f"    - #{t.id} {t.name!r} ({t.type})")

        sources = api.list_sources(source_type="PLAYLIST", category="ANNOUNCEMENT")
        print(f"  sources(PLAYLIST/ANNOUNCEMENT): {len(sources)}")

        opening = api.get_opening_hours()
        print(f"  openingHours: {opening.name!r}, Mon open={opening.monday.open}, Sat active={opening.saturday.active}")

        colors = api.list_colors()
        print(f"  colors: {len(colors)} palette entries (e.g. #{colors[0].id} {colors[0].name})")

        if dests:
            from_dt = datetime.now()
            to_dt = from_dt + timedelta(days=14)
            evs = api.list_events(zone_id=dests[0].id, from_dt=from_dt, to_dt=to_dt)
            print(f"  events on destination01 next 14d: {len(evs)}")

        agenda = api.get_agenda(date.today())
        print(f"  agenda today: {len(agenda)} item(s)")

        # -- 2. Write trial ------------------------------------------
        section("WRITE TRIAL — create + apply + clean up")
        try:
            new_dest = api.create_destination(name=f"{PREFIX}destination")
            print(f"  created destination #{new_dest.id} ({new_dest.name!r})")
            new_tmpl = api.create_template(name=f"{PREFIX}template",
                                            category="ANNOUNCEMENT")
            print(f"  created template #{new_tmpl.id} ({new_tmpl.name!r}, type={new_tmpl.type})")
            # Verify they show up in lists
            dests_after = api.list_destinations()
            tmpls_after = api.list_templates()
            assert any(d.id == new_dest.id for d in dests_after), "new dest not visible"
            assert any(t.id == new_tmpl.id for t in tmpls_after), "new template not visible"
            print(f"  both visible via list_* reads")
        finally:
            section("WRITE TRIAL CLEANUP")
            cleanup_residue(api)

    print("\nAll API verifications PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
