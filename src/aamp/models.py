"""Typed domain models for AAM Pro concepts.

Each model is a *decoded* view of one or more raw DB rows — enums are turned
into strings, daymasks into lists, sentinel datetimes into ``None``, and
references are resolved into ids so the model can stand alone.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Category names are loaded dynamically from aam_category, but the three seeded
# ones map cleanly to these literals.
Category = Literal["music", "announcement", "paging", "unknown"]

# aam_zone.type
ZoneKind = Literal["physical", "destination", "volume", "web_audio_session", "web_listen_session", "paging", "unknown"]

# db_itf_schedulers.repeattype
RepeatKind = Literal[
    "none",
    "daily_working_days",
    "daily_every_n",
    "weekly",
    "monthly_specific",
    "monthly_weekday",
    "yearly_specific",
    "yearly_weekday",
]

EndKind = Literal["never", "after_occurrences", "by_date"]

SchedEventKind = Literal["prop_source", "prop_set", "tmpl_set", "unknown"]

TimeAnchor = Literal["absolute", "opening_start", "opening_end"]


class Site(BaseModel):
    id: int
    name: Optional[str] = None
    organization: Optional[str] = None


class Zone(BaseModel):
    """A row from aam_zone. Both physical zones and destinations live here,
    distinguished by ``kind``."""
    id: int
    site_id: int
    kind: ZoneKind
    name: Optional[str] = None
    description: Optional[str] = None
    # parents/children resolved via aam_zone_bind
    parent_zone_ids: list[int] = Field(default_factory=list)
    child_zone_ids: list[int] = Field(default_factory=list)


class Destination(Zone):
    """A content-routing zone (aam_zone.type=1). Contains one or more physical zones."""
    kind: Literal["destination"] = "destination"
    member_physical_zone_ids: list[int] = Field(default_factory=list)


class PhysicalZone(Zone):
    kind: Literal["physical"] = "physical"


class Source(BaseModel):
    """An aam_dev_source — a thing that can be played (file, stream, paging, etc.)."""
    id: int
    name: Optional[str] = None
    category: Category = "unknown"
    source_type: str = "unknown"  # 'playlist', 'rtp', 'web', etc.
    library_path: Optional[str] = None  # for playlist sources, the underlying file
    prop_id: Optional[int] = None
    device_id: Optional[int] = None


class Template(BaseModel):
    id: int
    site_id: int
    name: Optional[str] = None
    category: Category = "unknown"
    # Sources this template plays (via aam_tmpl_set + aam_tmpl_set_source).
    source_ids: list[int] = Field(default_factory=list)


class Recurrence(BaseModel):
    """How often a schedule fires."""
    kind: RepeatKind = "none"
    days_of_week: list[str] = Field(default_factory=list)  # for weekly: ['Mon', 'Wed', ...]
    every_n_days: int = 1
    # monthly/yearly specifics — exposed but unused for bell-schedule MVP
    every_n_weeks: int = 1
    every_n_months: int = 1
    every_n_years: int = 1
    monthly_day: int = 0
    monthly_week: int = 0
    monthly_days_mask: int = 0
    yearly_month: int = 0
    yearly_day: int = 0
    yearly_week: int = 0
    yearly_days_mask: int = 0
    # window
    start_date: Optional[date] = None
    end_kind: EndKind = "never"
    end_date: Optional[date] = None
    end_after_occurrences: Optional[int] = None


class TimeOfDay(BaseModel):
    """One firing time within a day. Schedules can have many."""
    id: int  # db_itf_scheduler_times.id
    hour: int
    minute: int
    duration_minutes: int = 0  # 0 = instantaneous; 1440 = all-day
    start_anchor: TimeAnchor = "absolute"
    end_anchor: TimeAnchor = "absolute"
    start_offset_minutes: int = 0
    end_offset_minutes: int = 0


class Occurrence(BaseModel):
    """A single materialized occurrence from db_itf_scheduler_calendar.

    Most occurrences are auto-generated from the recurrence rule and aren't
    interesting individually. Two kinds matter for our purposes:
      - ``deleted=True``: the user removed this single occurrence.
      - ``exception=True``: the user added/moved this single occurrence
        (a one-off shift, or a custom one-off date).
    We only surface those overrides up to the LLM.
    """
    id: int
    scheduler_id: int
    time_id: int
    start_time: datetime
    duration_minutes: int = 0
    deleted: bool = False
    exception: bool = False
    name: Optional[str] = None


class ScheduleEvent(BaseModel):
    """A scheduled audio event = recurrence + times + content target.

    Combines a db_itf_schedulers row with its aam_sched_event linkage so the
    LLM sees one cohesive object per 'thing that fires on the calendar'.
    """
    id: int
    name: Optional[str] = None
    enabled: bool = True
    kind: SchedEventKind = "unknown"
    destination_id: Optional[int] = None  # resolved through prop_source/prop_set -> prop -> zone
    source_id: Optional[int] = None       # for prop_source events
    template_id: Optional[int] = None     # if a template is bound to this scheduler
    recurrence: Recurrence = Field(default_factory=Recurrence)
    times: list[TimeOfDay] = Field(default_factory=list)
    overrides: list[Occurrence] = Field(default_factory=list)  # user-edited occurrences only
    opening_hours_id: Optional[int] = None
    exception_group_id: Optional[int] = None


class OpeningHoursItem(BaseModel):
    id: int
    days_of_week: list[str] = Field(default_factory=list)
    hour_start: int = 0
    minute_start: int = 0
    length_minutes: int = 0
    active: bool = True


class OpeningHours(BaseModel):
    id: int
    name: Optional[str] = None
    items: list[OpeningHoursItem] = Field(default_factory=list)


class ExceptionGroup(BaseModel):
    id: int
    name: Optional[str] = None
    items: list["ExceptionItem"] = Field(default_factory=list)


class ExceptionItem(BaseModel):
    id: int
    exception_group_id: int
    kind: Literal["one_year", "every_year"] = "one_year"
    day: int = 0
    month: int = 0
    year: int = 0


ExceptionGroup.model_rebuild()
