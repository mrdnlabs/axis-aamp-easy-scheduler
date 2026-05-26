"""Site-overview HTTP surface.

Extracts a short human-readable label from the intent doc's
``Description`` section so the web TopBar can show the user's real
organization name instead of a hardcoded placeholder.

Endpoint:

  ``GET /api/site-overview?site_id=1`` → ``{site_label, headline, source}``.

If the intent doc has no real label yet (still the
``[ Site name unknown — ask. ]`` placeholder, or no doc exists), we
return ``site_label = None`` and let the frontend fall back to a
generic title. This way the TopBar doesn't fabricate a school name
for users who haven't completed the org-intake conversation yet.
"""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from .. import intent as _intent


router = APIRouter(prefix="/site-overview", tags=["site"])


class SiteOverview(BaseModel):
    """What the TopBar needs to render a header. All fields optional
    so the placeholder-doc case doesn't fail the request."""

    site_id: int
    site_label: Optional[str] = None
    headline: Optional[str] = None
    source: str  # "intent_doc" | "placeholder" | "missing"


# The Description section is bordered by ``## Description`` and the
# next ``## ``. We strip leading bold markers, italics, and the
# bracketed placeholder so the headline reads cleanly.
_SECTION_RE = re.compile(
    r"^##\s+Description\s*\n(?P<body>.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
_PLACEHOLDER_RE = re.compile(r"\[\s*[^\]]*unknown[^\]]*\]", re.IGNORECASE)


def _extract_label(doc: str) -> tuple[Optional[str], Optional[str], str]:
    """Returns ``(site_label, headline, source)``.

    ``site_label`` is a short noun phrase for a top-bar; ``headline``
    is one full sentence the UI can show in a hover or sub-header.
    """
    m = _SECTION_RE.search(doc)
    if not m:
        return None, None, "missing"

    body = m.group("body").strip()

    # Take the first non-blank line that isn't the placeholder marker
    # and isn't a pure italic helper sentence wrapped in underscores.
    headline: Optional[str] = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _PLACEHOLDER_RE.search(line):
            continue
        # Drop wrapping markdown emphasis / bold tokens.
        clean = line.strip("*_").strip()
        # Skip italic-only help text ("_(...)_") that the template
        # uses to explain the section.
        if clean.startswith("(") and clean.endswith(")"):
            continue
        headline = clean
        break

    if headline is None:
        return None, None, "placeholder"

    # Site label = first comma-or-period-delimited chunk of the
    # headline. "Lincoln Middle School, about 600 students." →
    # "Lincoln Middle School". Mirrors how the TopBar's siteName prop
    # is used today (short).
    label = re.split(r"[,.]", headline, maxsplit=1)[0].strip()
    return label or None, headline, "intent_doc"


@router.get("", response_model=SiteOverview)
def http_get(site_id: int = 1) -> SiteOverview:
    doc = _intent.read_intent(site_id)
    if not doc:
        return SiteOverview(site_id=site_id, source="missing")
    label, headline, source = _extract_label(doc)
    return SiteOverview(
        site_id=site_id,
        site_label=label,
        headline=headline,
        source=source,
    )
