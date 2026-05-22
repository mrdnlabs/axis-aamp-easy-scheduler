"""Decoded enum constants and mask helpers for the AXIS Audio Manager Pro schema.

Values are taken from the ``sql_enums`` table on a live AAM Pro 5.1.34 install.
Keep this in sync with the verified mapping in
``reference_aamppro_scheduler_schema.md`` (memory).
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Scheduler types (db_itf_schedulers.type)
# ---------------------------------------------------------------------------
# AXIS PBX (non-AAM) values 0..2 are filtered out elsewhere.
SCHED_TYPE_AAM_PROP = 983040
SCHED_TYPE_AAM_PROP_SOURCE = 983041  # plays a source on a destination
SCHED_TYPE_AAM_PROP_SET = 983042     # plays a prop-set (continuous music, etc.)
SCHED_TYPE_AAM_TMPL_SET = 983043     # template-binding stub (no recurrence)

AAM_SCHED_TYPES = {
    SCHED_TYPE_AAM_PROP: "prop",
    SCHED_TYPE_AAM_PROP_SOURCE: "prop_source",
    SCHED_TYPE_AAM_PROP_SET: "prop_set",
    SCHED_TYPE_AAM_TMPL_SET: "tmpl_set",
}

# ---------------------------------------------------------------------------
# Recurrence (db_itf_schedulers.repeattype)
# ---------------------------------------------------------------------------
REPEAT_NONE = 0
REPEAT_DAILY_WORKING_DAYS = 1
REPEAT_DAILY_EVERY_N = 2
REPEAT_WEEKLY = 3
REPEAT_MONTHLY_SPECIFIC = 4
REPEAT_MONTHLY_WEEKDAY = 5
REPEAT_YEARLY_SPECIFIC = 6
REPEAT_YEARLY_WEEKDAY = 7

REPEAT_NAMES: dict[int, str] = {
    REPEAT_NONE: "none",
    REPEAT_DAILY_WORKING_DAYS: "daily_working_days",
    REPEAT_DAILY_EVERY_N: "daily_every_n",
    REPEAT_WEEKLY: "weekly",
    REPEAT_MONTHLY_SPECIFIC: "monthly_specific",
    REPEAT_MONTHLY_WEEKDAY: "monthly_weekday",
    REPEAT_YEARLY_SPECIFIC: "yearly_specific",
    REPEAT_YEARLY_WEEKDAY: "yearly_weekday",
}

# End-of-recurrence (db_itf_schedulers.endtype)
END_NEVER = 0
END_AFTER_OCCURRENCES = 1
END_BY_DATE = 2

# ---------------------------------------------------------------------------
# Day-of-week bitmask (weeklydaymask, monthlydaymask, opening_hours_items.daymask)
# ---------------------------------------------------------------------------
DAY_MON = 1
DAY_TUE = 2
DAY_WED = 4
DAY_THU = 8
DAY_FRI = 16
DAY_SAT = 32
DAY_SUN = 64
DAY_HOLIDAY = 128

DAY_NAMES_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Holiday"]
DAY_NAMES_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Holiday"]
DAY_VALUES = [DAY_MON, DAY_TUE, DAY_WED, DAY_THU, DAY_FRI, DAY_SAT, DAY_SUN, DAY_HOLIDAY]

DayName = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Holiday"]


def daymask_to_days(mask: int, *, long_names: bool = False) -> list[str]:
    """Decode a daymask bitmask into a list of day names (in Mon-first order)."""
    names = DAY_NAMES_LONG if long_names else DAY_NAMES_SHORT
    return [name for name, bit in zip(names, DAY_VALUES) if mask & bit]


def days_to_daymask(days: list[str]) -> int:
    """Encode a list of day names (case-insensitive Mon/Tue/.../Holiday or long) into a daymask."""
    lookup: dict[str, int] = {}
    for short, long_, value in zip(DAY_NAMES_SHORT, DAY_NAMES_LONG, DAY_VALUES):
        lookup[short.lower()] = value
        lookup[long_.lower()] = value
    mask = 0
    for d in days:
        key = d.strip().lower()
        if key not in lookup:
            raise ValueError(f"Unknown day name: {d!r}")
        mask |= lookup[key]
    return mask


def humanize_daymask(mask: int) -> str:
    """Render a daymask as 'Mon, Wed, Fri' or 'every day' / 'weekdays' / 'weekends'."""
    if mask == 0:
        return "(no days)"
    weekdays = DAY_MON | DAY_TUE | DAY_WED | DAY_THU | DAY_FRI
    weekends = DAY_SAT | DAY_SUN
    days_only = mask & (weekdays | weekends | DAY_HOLIDAY)
    if days_only == weekdays:
        return "weekdays"
    if days_only == weekends:
        return "weekends"
    if days_only == (weekdays | weekends):
        return "every day"
    return ", ".join(daymask_to_days(mask))


# Time-of-day relative anchoring (db_itf_scheduler_times.timeschedstarttype / endtype)
TIME_ABSOLUTE = 0
TIME_RELATIVE_FROM_OPENING_START = 1
TIME_RELATIVE_FROM_OPENING_END = 2

# ---------------------------------------------------------------------------
# Zone types (aam_zone.type)
# ---------------------------------------------------------------------------
ZONE_PHYSICAL = 0
ZONE_CONTENT = 1   # "Destination" in the UI
ZONE_VOLUME = 2
ZONE_WEB_AUDIO = 3
ZONE_WEB_LISTEN = 4
ZONE_PAGING = 5

ZONE_TYPE_NAMES: dict[int, str] = {
    ZONE_PHYSICAL: "physical",
    ZONE_CONTENT: "destination",
    ZONE_VOLUME: "volume",
    ZONE_WEB_AUDIO: "web_audio_session",
    ZONE_WEB_LISTEN: "web_listen_session",
    ZONE_PAGING: "paging",
}

# ---------------------------------------------------------------------------
# Prop object types (aam_prop.objecttype)
# ---------------------------------------------------------------------------
PROP_OBJ_SITE = 1
PROP_OBJ_ZONE = 2
PROP_OBJ_DEV_SINK = 3

# ---------------------------------------------------------------------------
# Template (aam_tmpl.type, aam_tmpl_bind.objecttype)
# ---------------------------------------------------------------------------
TMPL_TYPE_TARGETS = 0
TMPL_TYPE_SCHED_CONTENT = 1

TMPL_BIND_ZONE = 0
TMPL_BIND_SCHED = 1

# ---------------------------------------------------------------------------
# Category (aam_category) — Music / Announcement / Paging are seeded on install.
# These are the typical ids but check the DB to confirm per-site.
# ---------------------------------------------------------------------------
CATEGORY_NAMES: dict[int, str] = {
    1: "music",
    2: "announcement",
    3: "paging",
}

# ---------------------------------------------------------------------------
# Source (aam_dev_source.type)
# ---------------------------------------------------------------------------
SOURCE_TYPE_INPUT = 1
SOURCE_TYPE_RTP = 32
SOURCE_TYPE_NET_SOURCE = 33
SOURCE_TYPE_PLAYLIST = 34
SOURCE_TYPE_PAGING = 35
SOURCE_TYPE_HW_ENDPOINT = 36
SOURCE_TYPE_PAGING_2WAY = 38
SOURCE_TYPE_WEB = 41

SOURCE_TYPE_NAMES: dict[int, str] = {
    SOURCE_TYPE_INPUT: "input",
    SOURCE_TYPE_RTP: "rtp",
    SOURCE_TYPE_NET_SOURCE: "net_source",
    SOURCE_TYPE_PLAYLIST: "playlist",
    SOURCE_TYPE_PAGING: "paging",
    SOURCE_TYPE_HW_ENDPOINT: "hw_endpoint",
    SOURCE_TYPE_PAGING_2WAY: "paging_2way",
    SOURCE_TYPE_WEB: "web",
}

# ---------------------------------------------------------------------------
# Sched event mode (aam_sched_event.mode)
# ---------------------------------------------------------------------------
SCHED_MODE_MANUAL = 0
SCHED_MODE_MANUAL_RESET = 1
SCHED_MODE_AUTO = 2
SCHED_MODE_AUTO_RESET = 3

# ---------------------------------------------------------------------------
# Sentinel values used by the app
# ---------------------------------------------------------------------------
UNSET_DATETIME_LITERAL = "1601-01-01 00:00:00"  # Windows FILETIME epoch
NO_END_DATETIME_LITERAL = "9999-01-01 00:00:00"
