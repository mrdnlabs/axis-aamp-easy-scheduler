"""Live-fire test of create_event against the running AAM Pro instance.

Strategy:
- Pick a future-dated, off-hours event with a distinctive name so it's
  easy to identify and easy to clean up.
- Commit it via the write layer (NOT in a rolled-back transaction this time).
- Sample db_itf_scheduler_calendar at intervals to see whether AAM Pro's
  background regenerator materializes occurrences automatically.
- Print everything the user needs to verify the event in the AAM Pro UI.
- Provide a one-command rollback at the end.

Run:
    .venv\\Scripts\\python.exe tests\\live_test_create_event.py
    .venv\\Scripts\\python.exe tests\\live_test_create_event.py --cleanup
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from typing import Optional

from aamp import read, write
from aamp.db import connect

TEST_EVENT_NAME = "VERIFY_TEST_DO_NOT_FIRE"
TEST_DESTINATION_ID = 2  # destination01
TEST_SOURCE_ID = 6        # End tone (already has prop_source on destination01)
TEST_DAYS = ["Wed"]
TEST_TIMES = [(4, 0)]     # 04:00 — well off-hours
TEST_START = date(2027, 1, 1)
TEST_END = date(2027, 1, 31)  # ~4 Wednesdays in January 2027


def banner(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def find_existing_test_event(conn) -> Optional[int]:
    """Return the scheduler_id of the test event if it exists, else None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM db_itf_schedulers WHERE name = %s",
            (TEST_EVENT_NAME,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def calendar_rows_for(conn, scheduler_id: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, starttime, length, deleted, exception, name
            FROM db_itf_scheduler_calendar
            WHERE schedulerid = %s
            ORDER BY starttime
            """,
            (scheduler_id,),
        )
        return cur.fetchall()


def cleanup() -> None:
    banner("CLEANUP — removing test event if present")
    with connect() as conn:
        sched_id = find_existing_test_event(conn)
        if sched_id is None:
            print(f"  No event named {TEST_EVENT_NAME!r} found. Nothing to do.")
            return
        print(f"  Found existing test event scheduler id={sched_id}; deleting…")
        write.delete_event(conn, sched_id)
        conn.commit()
        confirm = find_existing_test_event(conn)
        if confirm is None:
            print("  Cleanup OK — scheduler deleted.")
        else:
            print(f"  WARNING: scheduler {confirm} still present after delete!")


def run() -> None:
    banner("LIVE TEST — create_event end-to-end")
    print(f"Test parameters:")
    print(f"  name        = {TEST_EVENT_NAME}")
    print(f"  destination = #{TEST_DESTINATION_ID}")
    print(f"  source      = #{TEST_SOURCE_ID}")
    print(f"  days        = {TEST_DAYS}")
    print(f"  times       = {TEST_TIMES}")
    print(f"  window      = {TEST_START} to {TEST_END}")

    with connect() as conn:
        # Refuse to run twice without explicit cleanup.
        existing = find_existing_test_event(conn)
        if existing is not None:
            print(
                f"\nABORT: an event named {TEST_EVENT_NAME!r} already exists "
                f"(scheduler id={existing}). Run with --cleanup first."
            )
            sys.exit(2)

        # Snapshot counts before.
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM db_itf_schedulers")
            (start_sched_count,) = cur.fetchone()
            cur.execute("SELECT count(*) FROM db_itf_scheduler_calendar")
            (start_cal_count,) = cur.fetchone()
        print(f"\nBefore commit: {start_sched_count} schedulers, {start_cal_count} calendar rows.")

        # --- The actual write ---
        banner("Writing the new event")
        sched_id = write.create_event(
            conn,
            name=TEST_EVENT_NAME,
            destination_id=TEST_DESTINATION_ID,
            source_id=TEST_SOURCE_ID,
            days_of_week=TEST_DAYS,
            times=TEST_TIMES,
            start_date=TEST_START,
            end_date=TEST_END,
        )
        conn.commit()
        commit_time = datetime.now()
        print(f"  scheduler id = {sched_id}")
        print(f"  committed at = {commit_time:%H:%M:%S.%f}")

        # --- Inspect new rows ---
        banner("Row inspection")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, type, name, repeattype, weeklydaymask, startdate, enddate, endtype "
                "FROM db_itf_schedulers WHERE id = %s",
                (sched_id,),
            )
            print(f"  db_itf_schedulers: {cur.fetchone()}")
            cur.execute("SELECT id, objecttype, objectid, mode, queueid FROM aam_sched_event WHERE id = %s", (sched_id,))
            print(f"  aam_sched_event:   {cur.fetchone()}")
            cur.execute(
                "SELECT id, timehourstart, timeminstart, length FROM db_itf_scheduler_times "
                "WHERE schedulerid = %s ORDER BY id",
                (sched_id,),
            )
            for r in cur.fetchall():
                print(f"  scheduler_times:   {r}")

        # --- Calendar materialization watch ---
        banner("Calendar materialization watch")
        for delay in (0, 5, 15, 30):
            if delay:
                time.sleep(delay)
            rows = calendar_rows_for(conn, sched_id)
            now = datetime.now()
            elapsed = (now - commit_time).total_seconds()
            print(f"  t+{elapsed:5.1f}s ({now:%H:%M:%S}): {len(rows)} calendar rows for scheduler {sched_id}")
            if rows:
                for r in rows:
                    print(f"      {r}")
                break

        # --- Re-read via the typed pipeline (does it round-trip cleanly?) ---
        banner("Read-back via typed pipeline")
        events = read.list_schedule_events(conn, destination_id=TEST_DESTINATION_ID)
        ours = next((e for e in events if e.id == sched_id), None)
        if ours:
            print(f"  Event '{ours.name}' visible via list_schedule_events:")
            print(f"    destination_id  = {ours.destination_id}")
            print(f"    source_id       = {ours.source_id}")
            print(f"    recurrence.kind = {ours.recurrence.kind}")
            print(f"    days_of_week    = {ours.recurrence.days_of_week}")
            print(f"    times           = {[(t.hour, t.minute) for t in ours.times]}")
            print(f"    start_date      = {ours.recurrence.start_date}")
            print(f"    end_date        = {ours.recurrence.end_date}")
            print(f"    end_kind        = {ours.recurrence.end_kind}")
        else:
            print(f"  WARN: scheduler {sched_id} not found via list_schedule_events!")

        # --- Final summary + UI verification instructions ---
        banner("What to check in the AAM Pro UI")
        print(f"""
1. Open AAM Pro web UI (https://localhost/ or https://127.0.0.1/).
2. Navigate to Scheduling & destinations -> Destinations -> destination01 -> Schedule.
3. Look for an event named '{TEST_EVENT_NAME}' scheduled on Wednesdays at 04:00.
4. Date range should be {TEST_START} to {TEST_END}.

Things to verify:
  a) Does the event appear in the UI? (yes => AAM Pro picks up DB writes live)
  b) If you re-open the UI / refresh, does it still appear?
  c) Note whether the calendar shows materialized occurrences for the
     4 Wednesdays in January 2027.

When done, clean up with:
    .venv\\Scripts\\python.exe tests\\live_test_create_event.py --cleanup
""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true", help="Remove the test event and exit.")
    args = ap.parse_args()
    if args.cleanup:
        cleanup()
    else:
        run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
