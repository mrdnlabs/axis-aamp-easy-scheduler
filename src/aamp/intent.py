"""Per-site intent document — the user's *intended* schedule, in markdown.

Separate from the live DB state (which describe_site_schedule renders). The
intent doc captures things the DB can't: the *why* behind a schedule, the
human names for day-patterns ("block_day", "early_dismissal"), notes about
exceptions, and free-form prose context the LLM can lean on.

Layout
------
``<project>/intent/site_<id>.md`` — one file per site. Sections:

- Description   — free-form prose about the site
- Day schedules — named patterns ("regular_day", "block_day", ...)
- Application   — which pattern applies when
- One-off events — specific-date exceptions
- Notes         — anything else

The bootstrap template is intentionally sparse — meant to be filled in by a
conversation between the user and the LLM, not pre-populated from a guess.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import psycopg

from . import read
from .describe import describe_site_schedule


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Locate the project root for intent storage.

    Order: ``AAMP_PROJECT_ROOT`` env var, then the directory containing this
    package's parent of ``src``, then CWD. Falls back to ``C:\\20260520_AampEasyScheduler``.
    """
    env = os.environ.get("AAMP_PROJECT_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    # src/aamp/intent.py -> src/aamp -> src -> <project>
    candidate = here.parent.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path(r"C:\20260520_AampEasyScheduler")


def intent_dir() -> Path:
    d = _project_root() / "intent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def intent_path(site_id: int) -> Path:
    return intent_dir() / f"site_{site_id}.md"


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def read_intent(site_id: int) -> Optional[str]:
    """Return the intent doc for a site, or ``None`` if it doesn't exist yet."""
    p = intent_path(site_id)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def write_intent(site_id: int, content: str) -> Path:
    """Overwrite the entire intent doc for a site."""
    p = intent_path(site_id)
    p.write_text(content, encoding="utf-8")
    return p


SECTION_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def patch_intent_section(site_id: int, section_title: str, new_body: str) -> Path:
    """Replace the body of one ``## <section_title>`` section in the intent doc.

    Matches the first ``## section_title`` (case-insensitive) and replaces its
    body up to the next heading of equal-or-higher level. Raises ``KeyError``
    if no matching section is found.
    """
    text = read_intent(site_id)
    if text is None:
        raise FileNotFoundError(f"No intent doc for site {site_id}; run bootstrap_intent first")
    headings = list(SECTION_HEADING_RE.finditer(text))
    target_idx = None
    for i, m in enumerate(headings):
        if m.group(1) == "##" and m.group(2).strip().lower() == section_title.strip().lower():
            target_idx = i
            break
    if target_idx is None:
        raise KeyError(f"Section '## {section_title}' not found in intent doc")
    start = headings[target_idx].end()
    # Find next heading of level <= 2 (## or #)
    end = len(text)
    for m in headings[target_idx + 1:]:
        if len(m.group(1)) <= 2:
            end = m.start()
            break
    new_text = text[:start] + "\n\n" + new_body.rstrip() + "\n\n" + text[end:]
    # Collapse multiple blank lines
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    return write_intent(site_id, new_text)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

INTENT_TEMPLATE = """\
# {site_label} — schedule intent

_Intent document for AAM Pro natural-language scheduling. Edit any section freely._
_Last updated: {timestamp}_

## Description

**[ Site name unknown — ask the user. ]**

_(Describe the site in the user's own words: the actual name of the school, business, or organization; the kind of place it is; which buildings/areas/floors are involved; roughly how many people use it; any scheduling quirks. Two examples just to show the shape — do **not** substitute these for real info:_

_Example 1 (school):  "Lincoln Middle School, about 600 students. Three buildings: main, gym, cafeteria. Block schedules Tue/Thu; traditional six-period Mon/Wed/Fri. District holidays cancel all bells."_

_Example 2 (office):  "Northpoint Corporate HQ, 4 floors plus a lobby and 2 conference centers. Background music in common areas during business hours; chimes at 12:00 for lunch."_

_Replace this whole block — including the bracketed note — once you've confirmed the real site name and basic structure with the user.)_

## School year

_(Explicit calendar window(s) for the current and next school year. Example:_

```
- Current year (2026-27): 2026-09-01 to 2027-06-15
- Next year (2027-28): TBD
```

_)_

## Day schedules

_(Named patterns of bells/announcements for different kinds of days. One section per day-type. Bells usually fire at period transitions — typically two bells close together (end + start with a passing period between). Example:_

```
### regular_day
- 08:00 period 1 start
- 08:55 period 1 end (5-min passing)
- 09:00 period 2 start
- 09:55 period 2 end (5-min passing)
- 10:00 period 3 start
- ...
- 14:30 dismissal

### block_day_odd
- 08:00 period 1 start
- 09:30 period 1 end (5-min passing)
- 09:35 period 3 start
- 11:10 period 3 end (5-min passing)
- 11:15 period 5 start
- 13:45 dismissal

### block_day_even
- (...periods 2, 4, 6...)

### early_dismissal_wednesday
- (...shortened periods, dismissal at 12:30...)
```

_)_

## Application

_(Which day-type applies on which days, and to which destinations. Example:_

```
- regular_day:        Mon, Wed, Fri (2026-09-01 to 2027-06-15) — Elementary, Middle School
- block_day_odd:      Tue (2026-09-01 to 2027-06-15) — Middle School only
- block_day_even:     Thu (2026-09-01 to 2027-06-15) — Middle School only
- early_dismissal:    Wed (selected weeks; see Notes)
- none:               weekends, district holidays
```

_)_

## One-off events

_(Specific dated events outside the normal pattern. Example:_

```
- 2026-11-15 14:00  fire drill bell (all destinations)
- 2026-12-20 10:30  pep rally announcement (gym + middle school)
```

_)_

## Notes

_(Anything else worth recording — quirks, preferences, history, source documents imported. Example:_

```
- 2026-09-01: Imported initial schedule from district master schedule PDF.
- District calendar: snow days, in-service days, breaks per official calendar.
- Middle school uses A-day/B-day rotation independent of elementary.
```

_)_
"""


def bootstrap_intent(conn: psycopg.Connection, site_id: Optional[int] = None, *, overwrite: bool = False) -> Path:
    """Create an initial intent doc for a site if one doesn't exist.

    Args:
        conn: open psycopg connection (used to look up the site name).
        site_id: target site; defaults to the first/only site.
        overwrite: if True, replace any existing intent doc.

    Returns:
        Path to the (now-existing) intent doc.
    """
    sites = read.list_sites(conn)
    if not sites:
        raise RuntimeError("No sites found in the database — cannot bootstrap intent.")
    if site_id is None:
        site = sites[0]
    else:
        match = next((s for s in sites if s.id == site_id), None)
        if match is None:
            raise KeyError(f"No site with id={site_id}")
        site = match
    p = intent_path(site.id)
    if p.exists() and not overwrite:
        return p
    label = site.name or f"site #{site.id}"
    content = INTENT_TEMPLATE.format(site_label=label, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"))
    return write_intent(site.id, content)


def render_db_snapshot(conn: psycopg.Connection, site_id: Optional[int] = None) -> str:
    """Convenience: current DB state as markdown. Kept here so the LLM can request both halves of the picture from one tool surface."""
    return describe_site_schedule(conn, site_id)
