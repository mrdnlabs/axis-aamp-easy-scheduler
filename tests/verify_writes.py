"""Exercise the write layer inside a rolled-back transaction.

Goal: prove the SQL is valid and produces the expected row shape, without
mutating the live AAM Pro database. Every test opens a transaction, performs
writes, asserts the new rows are visible, then raises ``_RollbackSignal`` to
force psycopg's transaction context manager to roll back on exit.
"""

from __future__ import annotations

import contextlib
from datetime import date

from aamp import read, write
from aamp.db import connect


class _RollbackSignal(Exception):
    """Raised at the end of a write-test block to force rollback without committing."""


@contextlib.contextmanager
def _rollback_after(conn):
    """``with _rollback_after(conn):`` — runs the block in a transaction and rolls back."""
    try:
        with conn.transaction():
            yield
            raise _RollbackSignal
    except _RollbackSignal:
        pass


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    with connect() as conn:
        # Snapshot of starting state.
        sites = read.list_sites(conn)
        if not sites:
            print("No sites; aborting.")
            return
        site_id = sites[0].id

        starting_physical = len(read.list_physical_zones(conn, site_id))
        starting_destinations = len(read.list_destinations(conn, site_id))
        starting_templates = len(read.list_templates(conn, site_id))
        starting_events = len(read.list_schedule_events(conn))
        print(
            f"Starting state: site={sites[0].name!r}, "
            f"{starting_physical} physical zones, "
            f"{starting_destinations} destinations, "
            f"{starting_templates} templates, "
            f"{starting_events} events."
        )

        # ------------------------------------------------------------------
        section("Test 1: create_physical_zone")
        # ------------------------------------------------------------------
        with _rollback_after(conn):
            pz_id = write.create_physical_zone(conn, site_id=site_id, name="_test_room", parent_zone_id=1)
            print(f"  created physical zone id={pz_id}")
            zones = read.list_physical_zones(conn, site_id)
            assert len(zones) == starting_physical + 1, "physical zone count didn't increase"
            new_zone = next((z for z in zones if z.id == pz_id), None)
            assert new_zone is not None and new_zone.name == "_test_room", "new zone not found in read"
            print(f"  visible in list_physical_zones: parents={new_zone.parent_zone_ids}")
        zones_after = read.list_physical_zones(conn, site_id)
        assert len(zones_after) == starting_physical, "rollback didn't undo"
        print("  rollback OK (count restored)")

        # ------------------------------------------------------------------
        section("Test 2: create_destination + bind to physical zones")
        # ------------------------------------------------------------------
        physical_ids = [z.id for z in read.list_physical_zones(conn, site_id)[:2]]
        with _rollback_after(conn):
            d_id = write.create_destination(
                conn, site_id=site_id, name="_test_destination",
                physical_zone_ids=physical_ids,
            )
            print(f"  created destination id={d_id}")
            dests = read.list_destinations(conn, site_id)
            new_dest = next((d for d in dests if d.id == d_id), None)
            assert new_dest is not None, "new destination not found"
            print(f"  members: {new_dest.member_physical_zone_ids}")
            assert set(new_dest.member_physical_zone_ids) == set(physical_ids), "members mismatch"
        print("  rollback OK")

        # ------------------------------------------------------------------
        section("Test 3: create_template with existing sources")
        # ------------------------------------------------------------------
        sources = read.list_sources(conn)
        announcement_sources = [s for s in sources if s.category == "announcement"][:2]
        source_ids = [s.id for s in announcement_sources]
        with _rollback_after(conn):
            t_id = write.create_template(
                conn, site_id=site_id, name="_test_template",
                category="announcement", source_ids=source_ids,
            )
            print(f"  created template id={t_id}")
            templates = read.list_templates(conn, site_id)
            new_t = next((t for t in templates if t.id == t_id), None)
            assert new_t is not None, "new template not found"
            print(f"  category={new_t.category!r}, sources={new_t.source_ids}")
            assert new_t.source_ids == source_ids, "template sources mismatch"
        print("  rollback OK")

        # ------------------------------------------------------------------
        section("Test 4: create_exception_group + attach to existing scheduler")
        # ------------------------------------------------------------------
        all_events = read.list_schedule_events(conn)
        target_event = all_events[0] if all_events else None
        with _rollback_after(conn):
            eg_id = write.create_exception_group(
                conn, name="_test_holidays_2026",
                dates=[date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 1)],
                yearly_dates=[(7, 4)],
            )
            print(f"  created exception group id={eg_id}")
            groups = read.list_exception_groups(conn)
            new_g = next((g for g in groups if g.id == eg_id), None)
            assert new_g is not None, "new exception group not found"
            print(f"  items: {len(new_g.items)} ({sum(1 for i in new_g.items if i.kind=='one_year')} one-off, {sum(1 for i in new_g.items if i.kind=='every_year')} yearly)")
            if target_event:
                write.attach_exception_group(conn, target_event.id, eg_id)
                refreshed = next(
                    (e for e in read.list_schedule_events(conn) if e.id == target_event.id), None
                )
                assert refreshed and refreshed.exception_group_id == eg_id
                print(f"  attached to scheduler #{target_event.id}: exception_group_id={refreshed.exception_group_id}")
        print("  rollback OK")

        # ------------------------------------------------------------------
        section("Test 5: create_event (EXPERIMENTAL) — non-template")
        # ------------------------------------------------------------------
        destinations = read.list_destinations(conn, site_id)
        target_dest = destinations[0] if destinations else None
        target_source = announcement_sources[0] if announcement_sources else None
        if target_dest and target_source:
            with _rollback_after(conn):
                sched_id = write.create_event(
                    conn,
                    name="_test_friday_bell",
                    destination_id=target_dest.id,
                    source_id=target_source.id,
                    days_of_week=["Fri"],
                    times=[(16, 30)],
                    start_date=date(2026, 5, 25),
                    end_date=date(2026, 12, 31),
                )
                print(f"  created scheduler id={sched_id}")
                events = read.list_schedule_events(conn, target_dest.id)
                new_ev = next((e for e in events if e.id == sched_id), None)
                assert new_ev is not None, "event not visible"
                print(f"  name={new_ev.name!r}, days={new_ev.recurrence.days_of_week}, times={[(t.hour, t.minute) for t in new_ev.times]}")
                assert new_ev.recurrence.days_of_week == ["Fri"]
                assert new_ev.destination_id == target_dest.id
                print("  rollback OK")
        else:
            print("  (skipped — no destination/source available)")

        # ------------------------------------------------------------------
        section("Test 6: apply_template (EXPERIMENTAL)")
        # ------------------------------------------------------------------
        existing_templates = read.list_templates(conn, site_id)
        target_template = existing_templates[0] if existing_templates else None
        if target_template and target_dest:
            with _rollback_after(conn):
                sched_id = write.apply_template(
                    conn,
                    template_id=target_template.id,
                    destination_id=target_dest.id,
                    name="_test_applied_bell",
                    days_of_week=["Tue", "Thu"],
                    times=[(9, 0), (9, 30)],
                    start_date=date(2026, 5, 25),
                    end_date=date(2026, 12, 31),
                )
                print(f"  created PROP_SOURCE scheduler id={sched_id} bound to template #{target_template.id}")
                events = read.list_schedule_events(conn, target_dest.id)
                new_ev = next((e for e in events if e.id == sched_id), None)
                assert new_ev is not None, "event not visible"
                print(
                    f"  name={new_ev.name!r}, template={new_ev.template_id}, "
                    f"days={new_ev.recurrence.days_of_week}, "
                    f"times={[(t.hour, t.minute) for t in new_ev.times]}"
                )
                assert new_ev.template_id == target_template.id, "template binding not visible"
                print("  rollback OK")
        else:
            print("  (skipped — no existing template/destination available)")

        # ------------------------------------------------------------------
        section("Final state check (should equal starting state)")
        # ------------------------------------------------------------------
        end_physical = len(read.list_physical_zones(conn, site_id))
        end_destinations = len(read.list_destinations(conn, site_id))
        end_templates = len(read.list_templates(conn, site_id))
        end_events = len(read.list_schedule_events(conn))
        print(
            f"  {end_physical} physical zones (was {starting_physical}), "
            f"{end_destinations} destinations (was {starting_destinations}), "
            f"{end_templates} templates (was {starting_templates}), "
            f"{end_events} events (was {starting_events})"
        )
        assert end_physical == starting_physical
        assert end_destinations == starting_destinations
        assert end_templates == starting_templates
        assert end_events == starting_events
        print("\nAll write tests PASSED (no live mutations).")


if __name__ == "__main__":
    main()
