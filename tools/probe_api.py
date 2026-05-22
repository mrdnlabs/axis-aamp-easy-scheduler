"""Probe every documented /webapi/v1/* endpoint and snapshot its response shape.

Uses the OAuth client to authenticate, then GETs each endpoint with sensible
defaults. Saves both:
- ``logs/api_probe_<ts>.jsonl`` — one line per call with url, status, headers, body
- ``logs/api_probe_<ts>.md``     — human-readable summary

Endpoints with path params (e.g., ``/zones/{id}``) use the first known id
discovered from a prior list call. Filterable endpoints get a few variants
covered (e.g., ``/zones?type=CONTENT`` vs ``?type=PHYSICAL``).

Read-only. Never POSTs or PATCHes.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Optional

import httpx

from aamp.auth import AampAuth
from aamp.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TODAY = date.today()


def is_sensitive_path(p: str) -> bool:
    return any(s in p for s in ("/token", "/clients", "/authorize"))


def shape_of(value: Any, depth: int = 0, max_depth: int = 4) -> Any:
    """Produce a compact shape description of a JSON value.

    Recursive: dicts -> {key: shape_of(value)}, lists -> [shape_of(first)],
    primitives -> their python type name. Truncates deeply nested structures.
    """
    if depth >= max_depth:
        return "..."
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:30]:
            out[k] = shape_of(v, depth + 1, max_depth)
        return out
    if isinstance(value, list):
        if not value:
            return []
        return [shape_of(value[0], depth + 1, max_depth)]
    if value is None:
        return "null"
    return type(value).__name__


def run() -> int:
    cfg = load_config()
    log_path_jsonl = LOG_DIR / f"api_probe_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    log_path_md = LOG_DIR / f"api_probe_{datetime.now():%Y%m%d_%H%M%S}.md"

    summary = StringIO()
    summary.write(f"# AAM Pro API endpoint probe\n_(generated {datetime.now():%Y-%m-%d %H:%M})_\n\n")
    summary.write(f"Auth: {cfg.username} @ {cfg.host}\n\n")

    with AampAuth(cfg) as auth, log_path_jsonl.open("w", encoding="utf-8", buffering=1) as jsonl, \
         httpx.Client(base_url=cfg.host, verify=cfg.verify_tls, timeout=15.0) as http:

        headers = auth.http_headers()
        # IDs discovered along the way for use in /resource/{id} endpoints.
        discovered: dict[str, list[int]] = {
            "site_ids": [], "destination_ids": [], "physical_zone_ids": [],
            "scheduler_ids": [], "template_ids": [], "source_ids": [],
            "event_ids": [], "library_ids": [], "visual_profile_ids": [],
        }

        def call(label: str, method: str, path: str, params: Optional[dict] = None, expect_json: bool = True) -> Optional[Any]:
            try:
                r = http.request(method, path, headers=headers, params=params)
            except Exception as e:
                jsonl.write(json.dumps({"label": label, "method": method, "path": path, "params": params, "error": str(e)}) + "\n")
                summary.write(f"## {method} {path}\n_(label: {label})_\n\nERROR: {e}\n\n")
                return None
            body: Any = None
            content_type = r.headers.get("content-type", "")
            try:
                if expect_json and "json" in content_type:
                    body = r.json()
            except Exception:
                body = r.text[:500]
            jsonl.write(json.dumps({
                "label": label, "method": method, "path": path, "params": params,
                "status": r.status_code, "content_type": content_type,
                "body": body,
            }, default=str) + "\n")
            # Markdown summary entry
            summary.write(f"## `{method} {path}`")
            if params:
                summary.write(f" *(params: {params})*")
            summary.write(f"\n\nStatus: **{r.status_code}** ({content_type})\n\n")
            if r.status_code >= 400:
                summary.write(f"```\n{(r.text or '')[:600]}\n```\n\n")
                return None
            if body is not None:
                shape = shape_of(body)
                summary.write(f"Shape:\n\n```json\n{json.dumps(shape, indent=2)[:2000]}\n```\n\n")
                # Sample (first 1500 chars of pretty JSON)
                sample = json.dumps(body, indent=2, default=str)
                if len(sample) > 2000:
                    sample = sample[:2000] + "\n...[truncated]"
                summary.write(f"Sample:\n\n```json\n{sample}\n```\n\n")
            return body

        # ---- top-level reads -------------------------------------------
        summary.write("# Top-level reads\n\n")
        sites = call("sites", "GET", "/webapi/v1/sites")
        if sites and isinstance(sites.get("data"), list):
            discovered["site_ids"] = [s["id"] for s in sites["data"]]
        call("account", "GET", "/webapi/v1/account")
        call("dashboard", "GET", "/webapi/v1/dashboard")
        call("dashboard_hints", "GET", "/webapi/v1/dashboard/hints")
        call("notifications", "GET", "/webapi/v1/notifications")
        call("server_info_attempt", "GET", "/api/serverInfo")  # operational API — expect 404 (not enabled)

        # ---- global settings -------------------------------------------
        summary.write("# Global settings\n\n")
        call("globalSettings_general", "GET", "/webapi/v1/globalSettings/general")
        call("globalSettings_siteName", "GET", "/webapi/v1/globalSettings/siteName")
        call("globalSettings_localDateTime", "GET", "/webapi/v1/globalSettings/localDateTime")
        call("globalSettings_calendar", "GET", "/webapi/v1/globalSettings/calendar")
        call("globalSettings_visualProfile", "GET", "/webapi/v1/globalSettings/visualProfile")

        # ---- zones -----------------------------------------------------
        summary.write("# Zones\n\n")
        dests = call("zones_CONTENT", "GET", "/webapi/v1/zones", params={"type": "CONTENT", "size": 2147483647})
        if dests and isinstance(dests.get("data"), list):
            discovered["destination_ids"] = [d["id"] for d in dests["data"]]
        physical = call("zones_PHYSICAL", "GET", "/webapi/v1/zones", params={"type": "PHYSICAL", "size": 2147483647})
        if physical and isinstance(physical.get("data"), list):
            discovered["physical_zone_ids"] = [d["id"] for d in physical["data"]]
        for kind in ("VOLUME", "PAGING", "WEB_AUDIO_SESSION", "WEB_LISTEN_SESSION"):
            call(f"zones_{kind}", "GET", "/webapi/v1/zones", params={"type": kind, "size": 2147483647})

        if discovered["destination_ids"]:
            d_id = discovered["destination_ids"][0]
            call("zone_by_id", "GET", f"/webapi/v1/zones/{d_id}")
            call("zone_sources", "GET", f"/webapi/v1/zones/{d_id}/sources", params={"size": 2147483647})
        if discovered["physical_zone_ids"]:
            pz_id = discovered["physical_zone_ids"][0]
            call("zone_physical_by_id", "GET", f"/webapi/v1/zones/{pz_id}", params={"type": "PHYSICAL"})

        # ---- templates -------------------------------------------------
        summary.write("# Templates\n\n")
        tmpls = call("templates", "GET", "/webapi/v1/templates")
        if isinstance(tmpls, list):
            discovered["template_ids"] = [t["id"] for t in tmpls]
        elif tmpls and isinstance(tmpls.get("data"), list):
            discovered["template_ids"] = [t["id"] for t in tmpls["data"]]
        if discovered["template_ids"]:
            tid = discovered["template_ids"][0]
            call("template_by_id", "GET", f"/webapi/v1/templates/{tid}")

        # ---- sources & library ----------------------------------------
        summary.write("# Sources & library\n\n")
        for combo in (
            ("PLAYLIST", "ANNOUNCEMENT"),
            ("PLAYLIST", "MUSIC"),
            ("PLAYLIST", "PAGING"),
            ("NET_SOURCE", "MUSIC"),
            ("RTP", "MUSIC"),
        ):
            stype, cat = combo
            call(f"sources_{stype}_{cat}", "GET", "/webapi/v1/sources",
                 params={"sourceType": stype, "category": cat, "size": 2147483647})
        all_sources = call("sources_all", "GET", "/webapi/v1/sources", params={"size": 2147483647})
        if all_sources and isinstance(all_sources.get("data"), list):
            discovered["source_ids"] = [s["id"] for s in all_sources["data"]]

        # Libraries: try a few common ids (we know id=3 is the announcement library).
        for lib_id in (1, 2, 3, 4):
            call(f"library_{lib_id}_items", "GET", f"/webapi/v1/libraries/{lib_id}/items",
                 params={"path": "/", "size": 2147483647})

        # ---- schedulers ------------------------------------------------
        summary.write("# Schedulers & events\n\n")
        # No top-level GET /webapi/v1/schedulers in the capture — let's still try.
        call("schedulers_list_attempt", "GET", "/webapi/v1/schedulers")
        # Known: GET /webapi/v1/schedulers/{id}
        for sid in (1, 2, 3, 4, 5, 6):
            r = call(f"scheduler_{sid}", "GET", f"/webapi/v1/schedulers/{sid}")
            if r:
                discovered["scheduler_ids"].append(sid)
        # Events in a window for destination01
        if discovered["destination_ids"]:
            d = discovered["destination_ids"][0]
            t_from = TODAY.isoformat() + "T00:00"
            t_to = (TODAY + timedelta(days=14)).isoformat() + "T23:59"
            evs = call("events_window", "GET", "/webapi/v1/events",
                       params={"zoneId": d, "from": t_from, "to": t_to})
            if evs and isinstance(evs.get("data"), list):
                discovered["event_ids"] = [e["id"] for e in evs["data"]][:5]
            for eid in discovered["event_ids"][:1]:
                call(f"event_{eid}", "GET", f"/webapi/v1/events/{eid}")
        call("agenda_today", "GET", "/webapi/v1/agenda", params={"date": TODAY.isoformat()})

        # ---- opening hours & exceptions --------------------------------
        summary.write("# Opening hours & exception groups\n\n")
        call("openingHours_site", "GET", "/webapi/v1/openingHours/site")
        # Various plural/singular and discovery
        for path in ("/webapi/v1/openingHours", "/webapi/v1/exceptionGroups",
                     "/webapi/v1/holidays", "/webapi/v1/dayExceptions"):
            call(f"discover_{path.replace('/', '_')}", "GET", path)

        # ---- visual / audio / accessories ----------------------------
        summary.write("# Visual profiles & related\n\n")
        vp = call("visualProfiles", "GET", "/webapi/v1/visualProfiles")
        if isinstance(vp, list):
            discovered["visual_profile_ids"] = [v["id"] for v in vp]
        elif vp and isinstance(vp.get("data"), list):
            discovered["visual_profile_ids"] = [v["id"] for v in vp["data"]]
        if discovered["visual_profile_ids"]:
            vid = discovered["visual_profile_ids"][0]
            call("visualProfile_by_id", "GET", f"/webapi/v1/visualProfiles/{vid}")
        call("audioProfiles", "GET", "/webapi/v1/audioProfiles")
        call("lightProfiles", "GET", "/webapi/v1/lightProfiles")
        call("textProfiles", "GET", "/webapi/v1/textProfiles")
        call("textSources", "GET", "/webapi/v1/textSources")

        # ---- devices --------------------------------------------------
        summary.write("# Devices\n\n")
        call("devices", "GET", "/webapi/v1/devices")
        call("deviceGroups", "GET", "/webapi/v1/deviceGroups")
        call("sinks", "GET", "/webapi/v1/sinks")

        # ---- paging & announcements ----------------------------------
        summary.write("# Paging / announcements\n\n")
        call("paging", "GET", "/webapi/v1/paging")
        call("pagingConfigurations", "GET", "/webapi/v1/pagingConfigurations")
        call("announcements", "GET", "/webapi/v1/announcements")
        call("contacts", "GET", "/webapi/v1/contacts")

        # ---- tones / library --------------------------------------------
        summary.write("# Tones & libraries (discovery)\n\n")
        call("tones", "GET", "/webapi/v1/tones")
        call("libraries", "GET", "/webapi/v1/libraries")

        # ---- discovery probes for anything we might have missed ---------
        summary.write("# Random discovery probes\n\n")
        for path in (
            "/webapi/v1/sessions",
            "/webapi/v1/sessionQueues",
            "/webapi/v1/users",
            "/webapi/v1/groups",
            "/webapi/v1/roles",
            "/webapi/v1/permissions",
            "/webapi/v1/categories",
            "/webapi/v1/playlists",
            "/webapi/v1/streams",
            "/webapi/v1/colors",
            "/webapi/v1/system/status",
            "/webapi/v1/system/info",
            "/webapi/v1/license",
            "/api/v1.2/serverInfo",
            "/api/v1.2/targets",
        ):
            call(f"discover_{path.replace('/', '_')}", "GET", path)

        summary.write("\n# Discovered IDs\n\n")
        summary.write(f"```json\n{json.dumps(discovered, indent=2)}\n```\n")

    log_path_md.write_text(summary.getvalue(), encoding="utf-8")
    print(f"JSONL:  {log_path_jsonl}")
    print(f"Markdown summary: {log_path_md}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
