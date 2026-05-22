"""Summarize an observer JSONL log for human (and LLM) consumption.

Usage:
    python tools/summarize_traffic.py                  # summarize most recent log
    python tools/summarize_traffic.py logs/traffic_*.jsonl
    python tools/summarize_traffic.py --tail 50        # only the most recent 50 entries

Output sections:
  1. Endpoints touched (count, methods, status mix) — sorted by interest
  2. Per-path sample request/response bodies (first occurrence each)
  3. Authentication-related calls (OAuth / OIDC / token endpoints)
  4. Errors (4xx/5xx) with bodies
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def latest_log() -> Path:
    files = sorted(LOG_DIR.glob("traffic_*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No traffic logs in {LOG_DIR}")
    return files[-1]


def normalize_path(url: str) -> str:
    """Strip host + query for grouping; preserve numeric ids only as :id."""
    p = re.sub(r"^https?://[^/]+", "", url)
    p = p.split("?", 1)[0]
    # Replace numeric segments with :id for grouping ('/webapi/v1/zones/23' -> '/webapi/v1/zones/:id')
    p = re.sub(r"/\d+(?=/|$)", "/:id", p)
    return p


def is_auth(url: str) -> bool:
    if re.search(r":(1003[2-4])\b", url):
        return True
    lower = url.lower()
    return any(s in lower for s in ("/token", "/oauth", "/authorize", "/login", "/openid-configuration", "/jwks"))


def summarize(log_path: Path, tail: int | None = None) -> str:
    entries: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if tail:
        entries = entries[-tail:]

    out: list[str] = []
    out.append(f"# Traffic summary: {log_path.name}")
    out.append(f"_({len(entries)} entries)_\n")

    # ----- Group endpoints -----
    endpoints: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "statuses": defaultdict(int), "sample_req": None, "sample_resp": None}
    )
    auth_calls: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    # Pair requests with responses by url+timestamp (sequential)
    pending_req: dict[str, dict[str, Any]] = {}

    for e in entries:
        url = e.get("url", "")
        method = e.get("method", "")
        key = (method, normalize_path(url))
        bucket = endpoints[key]
        if e.get("phase") == "request":
            bucket["count"] += 1
            if not bucket["sample_req"]:
                bucket["sample_req"] = {
                    "url": url,
                    "headers": e.get("headers"),
                    "body": e.get("body"),
                }
            pending_req[url] = e
            if is_auth(url):
                auth_calls.append({"phase": "request", **e})
        elif e.get("phase") == "response":
            status = e.get("status", 0)
            bucket["statuses"][status] += 1
            if not bucket["sample_resp"]:
                bucket["sample_resp"] = {
                    "url": url,
                    "status": status,
                    "headers": e.get("headers"),
                    "body": e.get("body"),
                }
            if is_auth(url):
                auth_calls.append({"phase": "response", **e})
            if isinstance(status, int) and status >= 400:
                errors.append(e)

    # ----- Section 1: endpoints touched -----
    out.append("## Endpoints touched\n")
    if not endpoints:
        out.append("_(none)_\n")
    else:
        # Sort by interest: /webapi/ first, then /api/, then everything else; within group, by count desc
        def rank(key: tuple[str, str]) -> tuple[int, int]:
            _method, path = key
            if "/webapi/" in path:
                cat = 0
            elif "/api/" in path:
                cat = 1
            elif is_auth(path):
                cat = 2
            else:
                cat = 9
            return (cat, -endpoints[key]["count"])

        for (method, path) in sorted(endpoints, key=rank):
            b = endpoints[(method, path)]
            statuses = ", ".join(f"{s}×{c}" for s, c in sorted(b["statuses"].items()))
            out.append(f"- `{method} {path}` — {b['count']}× [{statuses or 'no response captured'}]")
        out.append("")

    # ----- Section 2: sample bodies for /webapi/ and /api/ endpoints -----
    out.append("## Sample request / response bodies (first occurrence per endpoint)\n")
    interesting_keys = [k for k in endpoints if "/webapi/" in k[1] or "/api/" in k[1] or is_auth(k[1])]
    if not interesting_keys:
        out.append("_(no /api/ or /webapi/ traffic captured)_\n")
    else:
        # Sort by category then path
        def rank2(key: tuple[str, str]) -> tuple[int, str]:
            _, path = key
            if "/webapi/" in path:
                return (0, path)
            if "/api/" in path:
                return (1, path)
            return (2, path)

        for (method, path) in sorted(interesting_keys, key=rank2):
            b = endpoints[(method, path)]
            out.append(f"### `{method} {path}`")
            if b["sample_req"]:
                req = b["sample_req"]
                out.append(f"- request URL: `{req['url']}`")
                if req["body"]:
                    body_preview = req["body"]
                    if len(body_preview) > 1500:
                        body_preview = body_preview[:1500] + "...[truncated]"
                    out.append(f"- request body:\n  ```\n  {body_preview}\n  ```")
            if b["sample_resp"]:
                resp = b["sample_resp"]
                out.append(f"- response: **{resp['status']}**")
                if resp["body"]:
                    body_preview = resp["body"]
                    if len(body_preview) > 1500:
                        body_preview = body_preview[:1500] + "...[truncated]"
                    out.append(f"- response body:\n  ```\n  {body_preview}\n  ```")
            out.append("")

    # ----- Section 3: auth -----
    if auth_calls:
        out.append("## Auth flow\n")
        for a in auth_calls[:20]:
            phase = a.get("phase")
            if phase == "request":
                out.append(f"- {a['method']} {a['url']}")
                if a.get("body"):
                    out.append(f"    body: `{(a['body'] or '')[:200]}`")
            else:
                out.append(f"  -> {a.get('status')} {a.get('url')}")
                if a.get("body"):
                    out.append(f"     body: `{(a.get('body') or '')[:200]}`")
        if len(auth_calls) > 20:
            out.append(f"_(... and {len(auth_calls) - 20} more)_")
        out.append("")

    # ----- Section 4: errors -----
    if errors:
        out.append("## Errors (4xx/5xx)\n")
        for e in errors[:10]:
            out.append(f"- {e.get('status')} {e.get('method')} {e.get('url')}")
            if e.get("body"):
                preview = (e.get("body") or "")[:400]
                out.append(f"    body: `{preview}`")
        if len(errors) > 10:
            out.append(f"_(... and {len(errors) - 10} more)_")
        out.append("")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile", nargs="?", help="JSONL log path (default: latest in logs/)")
    ap.add_argument("--tail", type=int, default=None, help="Only summarize last N entries")
    args = ap.parse_args()
    path = Path(args.logfile) if args.logfile else latest_log()
    print(summarize(path, tail=args.tail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
