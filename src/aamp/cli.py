"""Tiny CLI entry points for smoke-testing the read layer.

Not the primary interface — that's the MCP server in :mod:`aamp.mcp_server`.
Use ``python -m aamp.cli describe`` for a quick check that DB reads work.
"""

from __future__ import annotations

import sys

from .db import connect
from .describe import describe_site_schedule


def describe_main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    site_id: int | None = None
    if argv:
        try:
            site_id = int(argv[0])
        except ValueError:
            print(f"Usage: aamp-describe [site_id]", file=sys.stderr)
            return 2
    with connect() as conn:
        print(describe_site_schedule(conn, site_id))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "Usage:\n"
            "  python -m aamp.cli describe [site_id]   # render current state as markdown\n"
            "  python -m aamp.cli list-events          # show schedule events as JSON\n"
        )
        return 0
    cmd = argv[0]
    if cmd == "describe":
        return describe_main(argv[1:])
    if cmd == "list-events":
        import json

        from .read import list_schedule_events
        with connect() as conn:
            events = list_schedule_events(conn)
        print(json.dumps([e.model_dump(mode="json") for e in events], indent=2, default=str))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
