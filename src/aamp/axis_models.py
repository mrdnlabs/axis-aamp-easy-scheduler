"""Catalog of Axis Network Audio model numbers.

Compiled from axis.com product pages + help.axis.com documentation
(researched 2026-05-21). Used by :mod:`aamp.discovery` to classify
discovered Axis devices as audio vs camera vs other.

**Three signals contribute to classification, in order of strength:**

1. **mDNS service type** — `_axis-audiosite._tcp.local.` is audio-specific
   (only audio firmware advertises here). Strongest pre-auth signal.
2. **Model number** — once we have it (from `basic_info`), we look up
   against the catalog below. Exact match -> audio with subtype.
3. **Heuristic** — model prefix matches a known audio family pattern
   (C1xxx / C2xxx / C3xxx / C6xxx / C8xxx). Used when the model isn't in
   the catalog (newer release, OEM variant). Lower confidence — surfaced
   as `'audio?'` to invite manual verification.

Sources verified 2026-05-21:
- https://www.axis.com/products/network-speakers
- https://www.axis.com/products/system-devices-for-network-audio
- https://www.axis.com/products/network-paging-consoles
- https://help.axis.com/en-us/axis-audio-manager-edge (referenced fleet)
- Discontinuation statements (axis.com/dam/public/.../discontinuation-...)

Update this file when Axis releases new models or when you encounter an
audio device not classified by the heuristic.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Speakers — endpoint audio output devices
# ---------------------------------------------------------------------------

# Current speakers per axis.com/products/network-speakers (May 2026).
AUDIO_SPEAKERS_CURRENT: set[str] = {
    "C1110-E",        # Cabinet speaker (Verified on hardware 2026-05-21)
    "C1111-E",        # Cabinet speaker
    "C1210",          # Ceiling speaker
    "C1211",          # Ceiling speaker
    "C1310-E Mk II",  # Horn speaker
    "XC1311",         # Explosion-Protected horn speaker
    "C1410 Mk II",    # Mini speaker
    "C1510",          # Pendant speaker
    "C1511",          # Pendant speaker
    "C1610-VE",       # Sound projector
    "C1710",          # Display speaker
    "C1720",          # Display speaker
    "D4200-VE",       # Strobe speaker (audio + visual)
}

# Legacy / discontinued speakers — Axis Audio Player era (pre-AAM Pro 4).
# Still found on customer networks; older firmware path may apply.
AUDIO_SPEAKERS_LEGACY: set[str] = {
    "C1004-E",        # Discontinued (per Audio Player legacy listing)
    "C1310-E",        # Pre-Mk II original
    "C1410",          # Pre-Mk II original
    "C1611-E",        # Older sound projector
    "C2005",          # Network ceiling speaker (discontinued, per Axis statement)
    "C3003-E",        # Discontinued
    "C3211-E",        # Discontinued ("Not recommended" per AAM Edge docs)
}

# ---------------------------------------------------------------------------
# System devices — amplifiers, bridges, volume controllers
# ---------------------------------------------------------------------------

AUDIO_AMPLIFIERS: set[str] = {
    "C8210",          # Network audio amplifier (current flagship)
    "C8410",          # Larger amplifier (where present)
}

AUDIO_BRIDGES: set[str] = {
    "C8110",          # Network audio bridge (current)
    "C8033",          # Network audio bridge (discontinued — Audio Player legacy)
}

AUDIO_VOLUME_CONTROLLERS: set[str] = {
    "C8310",          # Volume controller
}

# ---------------------------------------------------------------------------
# Paging consoles — input devices for live announcements
# ---------------------------------------------------------------------------

AUDIO_PAGING_CONSOLES: set[str] = {
    "C6110",          # Network paging console (current)
    # Older paging consoles (if any) would go here; none identified in 2026-05 sweep.
}

# Microphones used WITH paging consoles (typically integrated, not standalone
# network audio devices, but listed for completeness).
AUDIO_MICROPHONES: set[str] = {
    "TC6901",         # Gooseneck microphone accessory for C6110
}

# ---------------------------------------------------------------------------
# Other audio-adjacent sensors that include audio capability
# ---------------------------------------------------------------------------

AUDIO_SENSORS: set[str] = {
    "D3110",          # (Legacy speaker referenced in AAM Edge docs)
    "D6310",          # Air-quality sensor — has speaker for audio alerts
}

# ---------------------------------------------------------------------------
# AAM Pro server hardware — runs AAM Pro itself, NOT an audio endpoint.
# Useful to distinguish: a C7050 on the network is the AAM Pro server, not
# a device to onboard.
# ---------------------------------------------------------------------------

AAMP_SERVER_HW: set[str] = {
    "C7050",
    "C7050 Mk II",
    "C7050 Mk III",
    "C7110",
}

# ---------------------------------------------------------------------------
# Combined sets for classification
# ---------------------------------------------------------------------------

#: Every Axis model that's an audio endpoint device (regardless of subtype).
#: Excludes the AAM Pro server appliances (C70xx) — those run AAM Pro, they
#: aren't onboarded as devices.
AUDIO_ENDPOINT_MODELS: set[str] = (
    AUDIO_SPEAKERS_CURRENT
    | AUDIO_SPEAKERS_LEGACY
    | AUDIO_AMPLIFIERS
    | AUDIO_BRIDGES
    | AUDIO_VOLUME_CONTROLLERS
    | AUDIO_PAGING_CONSOLES
    | AUDIO_MICROPHONES
    | AUDIO_SENSORS
)


# Per-model audio subtype lookup (for the UI / display layer).
_SUBTYPE_BY_SET: list[tuple[str, set[str]]] = [
    ("speaker", AUDIO_SPEAKERS_CURRENT | AUDIO_SPEAKERS_LEGACY),
    ("amplifier", AUDIO_AMPLIFIERS),
    ("bridge", AUDIO_BRIDGES),
    ("volume_controller", AUDIO_VOLUME_CONTROLLERS),
    ("paging_console", AUDIO_PAGING_CONSOLES),
    ("microphone", AUDIO_MICROPHONES),
    ("sensor", AUDIO_SENSORS),
]


# ---------------------------------------------------------------------------
# Heuristic fallback — for models not in the catalog
# ---------------------------------------------------------------------------

# Axis network-audio product naming conventions (verified across all current
# and legacy models above):
#   - Speakers:           C1xxx, C2xxx, C3xxx, D3xxx, D4xxx (display/strobe)
#   - Paging consoles:    C6xxx
#   - AAM Pro server hw:  C7xxx  (NOT an audio endpoint)
#   - System devices:     C8xxx (amplifiers, bridges, volume controllers)
#   - Sensors (audio cap.): D6xxx
#   - Explosion-protected speakers:  XC1xxx
# Cameras and other Axis products use different model prefixes:
#   - M-series, P-series, Q-series cameras
#   - F-series modular cameras
#   - I-series intercoms
#   - A-series access control
#   - T-series accessories
# So a model matching C1xxx-C3xxx, C6xxx, C8xxx, D3xxx, D4xxx, D6xxx, XC1xxx
# is likely (but not certainly) an audio device. C7xxx is server hardware.

# Match patterns roughly in declining confidence order. Each entry maps a
# regex (case-insensitive, applied to the trimmed model) to a subtype label.
_HEURISTIC_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^X?C1\d{3}", re.IGNORECASE), "speaker?"),         # C1xxx, XC1xxx
    (re.compile(r"^C2\d{3}", re.IGNORECASE), "speaker?"),
    (re.compile(r"^C3\d{3}", re.IGNORECASE), "speaker?"),
    (re.compile(r"^C6\d{3}", re.IGNORECASE), "paging_console?"),
    (re.compile(r"^C8\d{3}", re.IGNORECASE), "system_device?"),     # amp/bridge/volume
    (re.compile(r"^D3\d{3}", re.IGNORECASE), "speaker?"),
    (re.compile(r"^D4\d{3}", re.IGNORECASE), "strobe_speaker?"),
    (re.compile(r"^D6\d{3}", re.IGNORECASE), "sensor?"),
]

_AAMP_SERVER_PATTERN = re.compile(r"^C7\d{3}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public classification helpers
# ---------------------------------------------------------------------------

def _norm(model: Optional[str]) -> str:
    """Normalize model string for comparison: strip "AXIS " prefix + whitespace."""
    if not model:
        return ""
    m = model.strip()
    if m.upper().startswith("AXIS "):
        m = m[5:].strip()
    return m


def is_audio_device(model: Optional[str]) -> bool:
    """Return True if ``model`` is an Axis network audio endpoint.

    Catalog match first; falls back to the prefix heuristic for unknown models.
    Excludes the C70xx server-hardware family.
    """
    m = _norm(model)
    if not m:
        return False
    if m in AUDIO_ENDPOINT_MODELS:
        return True
    # Try a few mild normalizations — Axis uses both "C1310-E" and
    # "C1310E" interchangeably in different places, and the "Mk II" suffix
    # may have varying whitespace.
    if m.replace(" ", "") in {x.replace(" ", "") for x in AUDIO_ENDPOINT_MODELS}:
        return True
    if _AAMP_SERVER_PATTERN.match(m):
        return False  # C70xx is server HW, not an audio endpoint
    return any(p.match(m) for p, _ in _HEURISTIC_PATTERNS)


def is_aamp_server_hw(model: Optional[str]) -> bool:
    """Return True if ``model`` is an AAM Pro server appliance (C70xx)."""
    m = _norm(model)
    return bool(m) and (m in AAMP_SERVER_HW or bool(_AAMP_SERVER_PATTERN.match(m)))


def audio_subtype(model: Optional[str]) -> Optional[str]:
    """Return a category label for an audio model, or None.

    Returns one of:
      - "speaker" / "amplifier" / "bridge" / "volume_controller" /
        "paging_console" / "microphone" / "sensor"  (from the catalog)
      - "speaker?" / "system_device?" / "paging_console?" / etc.
        with a trailing "?" when the match came from the heuristic
        rather than the explicit catalog
      - None if the model isn't recognized as audio at all
    """
    m = _norm(model)
    if not m:
        return None
    # Try normalized variant too.
    for label, members in _SUBTYPE_BY_SET:
        if m in members or m.replace(" ", "") in {x.replace(" ", "") for x in members}:
            return label
    if _AAMP_SERVER_PATTERN.match(m):
        return None  # not an audio endpoint
    for pattern, label in _HEURISTIC_PATTERNS:
        if pattern.match(m):
            return label
    return None


def classify_device(model: Optional[str]) -> str:
    """High-level device class for a discovered Axis device.

    Returns one of:
      - ``"audio"`` — confirmed audio endpoint (catalog match)
      - ``"audio?"`` — heuristic match (model prefix matches a known
        audio family but isn't yet in the catalog)
      - ``"aam-pro-server"`` — C70xx server appliance (runs AAM Pro itself)
      - ``"non-audio"`` — we have a model number, and it's recognizably
        NOT audio (cameras M/P/Q/F-series, intercoms I-, access A-,
        accessories T-, switches, etc.)
      - ``"unknown"`` — no model info available yet
    """
    m = _norm(model)
    if not m:
        return "unknown"
    if is_aamp_server_hw(m):
        return "aam-pro-server"
    sub = audio_subtype(m)
    if sub is not None:
        return "audio?" if sub.endswith("?") else "audio"
    # Has a model, no audio match — it's a known non-audio Axis product
    # (camera / intercom / access control / accessory / etc.).
    return "non-audio"
