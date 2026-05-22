"""Smoke test for the plan-and-apply layer."""

from __future__ import annotations

from aamp import plan
from aamp.db import connect


def main() -> None:
    # A small multi-step plan: create a physical zone + destination + template
    # (all in dry-run mode — no live mutations).
    operations = [
        {
            "action": "create_physical_zone",
            "args": {"site_id": 1, "name": "_plan_test_room"},
        },
        {
            "action": "create_destination",
            "args": {"site_id": 1, "name": "_plan_test_dest", "physical_zone_ids": [3, 7]},
        },
        {
            "action": "create_template",
            "args": {
                "site_id": 1,
                "name": "_plan_test_template",
                "category": "announcement",
                "source_ids": [1],
            },
        },
        {
            "action": "create_event",
            "args": {
                "name": "_plan_test_friday_bell",
                "destination_id": 2,
                "source_id": 6,
                "days_of_week": ["Fri"],
                "times": ["08:00", "15:30"],
                "start_date": "2027-09-01",
                "end_date": "2028-06-15",
            },
        },
    ]

    print("=" * 70)
    print("DRY RUN")
    print("=" * 70)
    with connect() as conn:
        print(plan.execute_plan(conn, operations, dry_run=True))

    print()
    print("=" * 70)
    print("INTENTIONAL FAILURE (unknown action) — should report and abort cleanly")
    print("=" * 70)
    bad = operations + [{"action": "do_the_thing", "args": {}}]
    with connect() as conn:
        try:
            print(plan.execute_plan(conn, bad, dry_run=True))
        except ValueError as e:
            print(f"OK — validation rejected: {e}")

    print()
    print("=" * 70)
    print("MID-PLAN FAILURE (bad FK) - earlier steps should roll back")
    print("=" * 70)
    bad2 = [
        {
            "action": "create_physical_zone",
            "args": {"site_id": 1, "name": "_plan_test_room"},
        },
        {
            "action": "create_destination",
            "args": {"site_id": 1, "name": "_plan_test_dest", "physical_zone_ids": [99999]},
        },
    ]
    with connect() as conn:
        try:
            print(plan.execute_plan(conn, bad2, dry_run=True))
        except plan.PlanError as e:
            print(f"OK - PlanError raised as expected: step {e.step_index} ({e.action})")
            print(f"     original: {type(e.original).__name__}")
            # Verify zone count is unchanged (rollback worked).
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM aam_zone WHERE name = '_plan_test_room'")
                leaked = cur.fetchone()[0]
            print(f"     zones leaked from step 1: {leaked} (should be 0)")


if __name__ == "__main__":
    main()
