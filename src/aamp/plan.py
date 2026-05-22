"""Batch / change-set execution layer with dry-run preview — REST API edition.

Operations are dispatched to :mod:`aamp.write` (which now delegates to
:class:`aamp.api.AampApi`). A *plan* is an ordered list of
``{"action": "<name>", "args": {...}}`` dicts; the dispatcher invokes
each action against a shared API client.

``dry_run=True`` previously executed against the DB inside a savepoint and
rolled back so the user could see what *would* happen. The REST API has no
such transactional sandbox — so dry-run now just **describes** what each
action would do, without executing. For higher-fidelity preview, the LLM
should call read endpoints first to confirm prerequisites.
"""

from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from typing import Any, Callable, Optional

from . import write as _write
from .api import AampApi
from .config import load_config


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------

ActionFn = Callable[[AampApi, dict[str, Any]], str]


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _parse_times(value: Any) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for t in value or []:
        if isinstance(t, str):
            h, m = t.split(":", 1)
            out.append((int(h), int(m)))
        elif isinstance(t, dict):
            out.append((int(t["hour"]), int(t["minute"])))
        elif isinstance(t, (list, tuple)) and len(t) >= 2:
            out.append((int(t[0]), int(t[1])))
        else:
            raise ValueError(f"Cannot parse time: {t!r}")
    return out


# ---- action implementations ------------------------------------------------

def _do_create_physical_zone(api: AampApi, args: dict) -> str:
    new_id = _write.create_physical_zone(
        api,
        site_id=int(args.get("site_id", 1)),
        name=str(args["name"]),
        parent_zone_id=args.get("parent_zone_id"),
    )
    extra = f" under #{args['parent_zone_id']}" if args.get("parent_zone_id") else ""
    return f"Created physical zone '{args['name']}' (id={new_id}){extra}."


def _do_create_destination(api: AampApi, args: dict) -> str:
    pz = list(args.get("physical_zone_ids") or [])
    new_id = _write.create_destination(
        api,
        site_id=int(args.get("site_id", 1)),
        name=str(args["name"]),
        physical_zone_ids=pz,
    )
    suffix = f" (physical_zone_ids hint {pz}, binding pending PATCH endpoint capture)" if pz else ""
    return f"Created destination '{args['name']}' (id={new_id}){suffix}."


def _do_create_template(api: AampApi, args: dict) -> str:
    new_id = _write.create_template(
        api,
        site_id=int(args.get("site_id", 1)),
        name=str(args["name"]),
        category=str(args["category"]),
    )
    return f"Created {args['category']} template '{args['name']}' (id={new_id})."


def _do_delete_template(api: AampApi, args: dict) -> str:
    _write.delete_template(api, int(args["template_id"]))
    return f"Deleted template #{args['template_id']}."


def _do_delete_destination(api: AampApi, args: dict) -> str:
    _write.delete_destination(api, int(args["destination_id"]))
    return f"Deleted destination #{args['destination_id']}."


def _do_add_template_content(api: AampApi, args: dict) -> str:
    new_id = _write.add_template_content(
        api,
        template_id=int(args["template_id"]),
        files=list(args.get("files", [])),
        scheduler_name=str(args["scheduler_name"]),
        specific_times=list(args.get("specific_times", [])),
        autostart=bool(args.get("autostart", True)),
        queueable=bool(args.get("queueable", True)),
    )
    times = args.get("specific_times", [])
    return (
        f"Added content to template #{args['template_id']}: scheduler "
        f"'{args['scheduler_name']}' (id={new_id}), fires at {times}."
    )


def _do_schedule_template(api: AampApi, args: dict) -> str:
    start = _parse_date(args.get("start_date"))
    end = _parse_date(args.get("end_date"))
    if start is None:
        raise ValueError("start_date is required")
    _write.schedule_template_on_destination(
        api,
        template_id=int(args["template_id"]),
        destination_id=int(args["destination_id"]),
        days_of_week=list(args["days_of_week"]),
        start_date=start,
        end_date=end,
        week_every=int(args.get("week_every", 1)),
        color_id=int(args.get("color_id", 1)),
    )
    days = ", ".join(args["days_of_week"])
    range_s = f"{start}" + (f" to {end}" if end else " (no end)")
    return (
        f"Scheduled template #{args['template_id']} on destination "
        f"#{args['destination_id']}: {days}, {range_s}."
    )


def _do_unschedule_template(api: AampApi, args: dict) -> str:
    _write.unschedule_template_on_destination(
        api,
        template_id=int(args["template_id"]),
        destination_id=int(args["destination_id"]),
        interval=dict(args["interval"]),
    )
    return (
        f"Unscheduled template #{args['template_id']} from "
        f"destination #{args['destination_id']}."
    )


def _do_create_day_exception(api: AampApi, args: dict) -> str:
    d = _parse_date(args["exception_date"])
    if d is None:
        raise ValueError("exception_date required")
    _write.create_day_exception(
        api,
        template_id=int(args["template_id"]),
        destination_id=int(args["destination_id"]),
        exception_date=d,
    )
    return (
        f"Cancelled template #{args['template_id']} on destination "
        f"#{args['destination_id']} for {d.isoformat()}."
    )


def _do_create_event(api: AampApi, args: dict) -> str:
    times = _parse_times(args.get("times"))
    start = _parse_date(args.get("start_date"))
    end = _parse_date(args.get("end_date"))
    if start is None:
        raise ValueError("start_date is required")
    sched_id = _write.create_event(
        api,
        name=str(args["name"]),
        destination_id=int(args["destination_id"]),
        source_id=int(args.get("source_id", 0)),
        days_of_week=list(args["days_of_week"]),
        times=times,
        start_date=start,
        end_date=end,
        enabled=bool(args.get("enabled", True)),
        category=str(args.get("category", "ANNOUNCEMENT")),
        sources=args.get("sources"),
    )
    days = ", ".join(args["days_of_week"])
    times_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    return (
        f"Created event '{args['name']}' (scheduler #{sched_id}): "
        f"{days} at {times_str}, from {start}"
        f"{(' until ' + str(end)) if end else ' (no end)'}."
    )


def _do_delete_event(api: AampApi, args: dict) -> str:
    _write.delete_event(api, int(args["scheduler_id"]))
    return f"Deleted scheduler #{args['scheduler_id']}."


def _do_move_occurrence(api: AampApi, args: dict) -> str:
    new_dt = _parse_datetime(args["new_start_time"])
    end_dt = _parse_datetime(args.get("new_end_time"))
    _write.move_occurrence(
        api,
        event_id=int(args["event_id"]),
        new_start_time=new_dt,
        new_end_time=end_dt,
        name=args.get("name"),
    )
    return f"Moved event #{args['event_id']} to {new_dt:%Y-%m-%d %H:%M}."


ACTIONS: dict[str, ActionFn] = {
    "create_physical_zone": _do_create_physical_zone,
    "create_destination": _do_create_destination,
    "create_template": _do_create_template,
    "delete_template": _do_delete_template,
    "delete_destination": _do_delete_destination,
    "add_template_content": _do_add_template_content,
    "schedule_template": _do_schedule_template,
    "unschedule_template": _do_unschedule_template,
    "create_day_exception": _do_create_day_exception,
    "create_event": _do_create_event,
    "delete_event": _do_delete_event,
    "move_occurrence": _do_move_occurrence,
}


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------

class PlanError(RuntimeError):
    def __init__(self, step_index: int, action: str, original: BaseException) -> None:
        super().__init__(f"Step {step_index} ({action}) failed: {original}")
        self.step_index = step_index
        self.action = action
        self.original = original


def _validate(operations: list[dict]) -> None:
    if not isinstance(operations, list):
        raise ValueError("operations must be a list of {action, args} dicts")
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            raise ValueError(f"step {i}: not a dict")
        action = op.get("action")
        if action not in ACTIONS:
            known = ", ".join(sorted(ACTIONS))
            raise ValueError(f"step {i}: unknown action {action!r}. Known: {known}")
        if not isinstance(op.get("args", {}), dict):
            raise ValueError(f"step {i}: args must be a dict")


def execute_plan(
    operations: list[dict],
    *,
    api: Optional[AampApi] = None,
    dry_run: bool = True,
) -> str:
    """Run a list of operations.

    Args:
        operations: ``[{"action": ..., "args": {...}}, ...]``.
        api: pre-constructed API client; one is created on demand if omitted.
        dry_run: if True, print each step's intended description **without
            executing**. The REST API lacks a savepoint, so dry-run here is a
            best-effort textual preview (rather than the rolled-back execution
            we had with direct DB writes).

    On any execution error in non-dry-run mode, prior successful steps are
    **already committed** — the API has no batch transaction. Callers should
    treat plan failures as partial completion and inspect state.
    """
    _validate(operations)
    out = StringIO()
    out.write(f"Plan with {len(operations)} step(s) [{'DRY RUN' if dry_run else 'APPLY'}]:\n\n")

    if dry_run:
        for i, op in enumerate(operations, start=1):
            action = op["action"]
            args = op.get("args", {})
            out.write(f"  {i}. [{action}] would call with args={args}\n")
        out.write(
            "\nStatus: PREVIEWED (no calls made).\n"
            "Note: dry-run does not validate FKs against the live API. "
            "Re-run with dry_run=False to apply."
        )
        return out.getvalue()

    own_api = api is None
    if api is None:
        api = AampApi.from_config(load_config())
    try:
        for i, op in enumerate(operations, start=1):
            action = op["action"]
            args = op.get("args", {})
            fn = ACTIONS[action]
            try:
                msg = fn(api, args)
            except Exception as e:  # noqa: BLE001
                out.write(f"\nStatus: FAILED at step {i} ({action}).\n")
                out.write("Note: earlier steps in this plan have ALREADY BEEN COMMITTED "
                          "to AAM Pro — no rollback is possible via the REST API.\n")
                raise PlanError(i, action, e) from e
            out.write(f"  {i}. [{action}] {msg}\n")
        out.write("\nStatus: COMMITTED.")
    finally:
        if own_api:
            api.close()
    return out.getvalue()
