"""Pydantic models matching the AAM Pro REST API JSON shapes.

Captured from live SPA traffic (2026-05-21) and the systematic API probe
(``tools/probe_api.py``). Field names use snake_case in Python but serialize
to camelCase via aliases so we can ``model_dump(by_alias=True)`` when sending
to the server.

Models intentionally use ``model_config = ConfigDict(extra="allow")`` so
fields we haven't catalogued yet flow through transparently — important
because the API surface is undocumented and shapes may grow between AAM Pro
versions.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Common enumerations exposed by the API as string values.
Category = Literal["MUSIC", "ANNOUNCEMENT", "PAGING"]
ZoneKind = Literal["PHYSICAL", "CONTENT", "VOLUME", "PAGING", "WEB_AUDIO_SESSION", "WEB_LISTEN_SESSION"]
RepeatType = Literal["NONE", "DAY", "WEEK", "MONTH", "YEAR"]
EndOnType = Literal["NO_END", "END_BY_DATE", "END_BY_OCCURRENCIES"]
TimeSchedulingType = Literal["SPECIFIC_TIME", "RELATIVE_TIME"]
DailyRecurrencesType = Literal["DAYS", "WORKING_DAYS"]
SourceType = Literal["INPUT", "RTP", "NET_SOURCE", "PLAYLIST", "PAGING", "HW_ENDPOINT", "PAGING_2WAY", "WEB"]
SourceSubtype = Literal["SINGLEFILE", "PLAYLIST", "STREAM", "UNKNOWN"]
PriorityGroup = Literal["LOW", "HIGH"]
VisualProfileEnabled = Literal["DEFAULT", "ENABLED", "DISABLED"]
TristateString = Literal["DEFAULT", "TRUE", "FALSE"]  # observed on enabled/muted

# ---------------------------------------------------------------------------
# Base config
# ---------------------------------------------------------------------------

class _ApiModel(BaseModel):
    """Pydantic base with API-friendly defaults.

    - populate_by_name lets you construct with snake_case or alias names.
    - by alias is set via convenience methods to_dict() and to_json_body().
    - extra='allow' preserves unknown server-added fields.
    """
    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )

    def to_dict(self, exclude_none: bool = True) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=exclude_none, mode="json")


# ---------------------------------------------------------------------------
# Library / files
# ---------------------------------------------------------------------------

class LibraryItem(_ApiModel):
    # ``id`` is absent for directory entries (folder=True). Pydantic allows None
    # so directory listings can be materialized alongside file entries.
    id: Optional[int] = None
    library_id: int = Field(alias="libraryId")
    url: bool = False
    folder: bool = False
    delete: bool = False
    path: str = ""
    title: Optional[str] = None
    duration: Optional[float] = None  # seconds (float in templateSets POST, ms in responses!)
    artist: Optional[str] = None
    album: Optional[str] = None
    contains_dir: bool = Field(default=False, alias="containsDir")
    contains_files: bool = Field(default=False, alias="containsFiles")
    used_by_pre_post: bool = Field(default=False, alias="usedByPrePost")
    content_playlist_ids: list[int] = Field(default_factory=list, alias="contentPlaylistIds")


# ---------------------------------------------------------------------------
# Sites & zones
# ---------------------------------------------------------------------------

class Site(_ApiModel):
    id: int
    name: str = ""
    muted: TristateString = "DEFAULT"
    enabled: TristateString = "DEFAULT"


class PhysicalZoneSummary(_ApiModel):
    """The reduced form found embedded in a Destination's ``physicalZones`` list."""
    id: int
    name: str = ""
    type: ZoneKind = "PHYSICAL"
    path: list[dict[str, Any]] = Field(default_factory=list)


class Zone(_ApiModel):
    """Both physical zones and destinations. Distinguished by ``type``."""
    id: int
    name: str = ""
    type: ZoneKind
    enabled: TristateString = "DEFAULT"
    muted: TristateString = "DEFAULT"
    sink_stats: Optional[str] = Field(default=None, alias="sinkStats")
    sink_ids: list[int] = Field(default_factory=list, alias="sinkIds")
    sink_paths: list[Any] = Field(default_factory=list, alias="sinkPaths")
    has_multicast: Optional[str] = Field(default=None, alias="hasMulticast")
    physical_zone_ids: list[int] = Field(default_factory=list, alias="physicalZoneIds")
    physical_zones: list[PhysicalZoneSummary] = Field(default_factory=list, alias="physicalZones")
    device_groups: list[Any] = Field(default_factory=list, alias="deviceGroups")
    templates_used: list["TemplateUsage"] = Field(default_factory=list, alias="templatesUsed")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class SourceSummary(_ApiModel):
    """Embedded source descriptor (e.g., inside Scheduler.sources)."""
    source_id: Optional[int] = Field(default=None, alias="sourceId")
    name: Optional[str] = Field(default=None, alias="sourceName")
    source_type: Optional[SourceType] = Field(default=None, alias="sourceType")
    source_subtype: Optional[SourceSubtype] = Field(default=None, alias="sourceSubtype")
    priority: Optional[int] = None
    priority_group: PriorityGroup = Field(default="LOW", alias="priorityGroup")
    active: bool = True
    library_item: Optional[LibraryItem] = Field(default=None, alias="libraryItem")


class Source(_ApiModel):
    """A full source row (e.g., from GET /sources or zones/{id}/sources)."""
    id: int
    name: Optional[str] = None
    gain_offset: Optional[int] = Field(default=None, alias="gainOffset")
    enabled: bool = True
    source_type: Optional[SourceType] = Field(default=None, alias="sourceType")
    source_subtype: Optional[SourceSubtype] = Field(default=None, alias="sourceSubtype")
    used_as_inter: Optional[Any] = Field(default=None, alias="usedAsInter")  # observed; type unclear


# ---------------------------------------------------------------------------
# Schedulers & events
# ---------------------------------------------------------------------------

class SpecificTime(_ApiModel):
    """A single ``startTime`` (and optional ``endTime``) entry in scheduler.specificTimes."""
    start_time: str = Field(alias="startTime")          # "HH:MM"
    end_time: Optional[str] = Field(default=None, alias="endTime")


class RelativeTime(_ApiModel):
    """A relative-to-opening-hours offset (for TimeSchedulingType=RELATIVE_TIME)."""
    # Observed shape not yet captured — leave generic for now.
    model_config = ConfigDict(extra="allow")


class RecurrenceInterval(_ApiModel):
    """The window-and-pattern half of a scheduler. Reused in:
       - Scheduler itself (top-level fields)
       - Template.usedInZones[].interval
       - POST /templates/{id}/scheduleOn/{zoneId} request body
       - POST /templates/{id}/unscheduleOn/{zoneId} request body
    """
    start_on: Optional[str] = Field(default=None, alias="startOn")  # "YYYY-MM-DD"
    end_on: Optional[str] = Field(default=None, alias="endOn")
    end_on_type: EndOnType = Field(default="NO_END", alias="endOnType")
    max_occurencies: Optional[int] = Field(default=None, alias="maxOccurencies")
    repeat_type: RepeatType = Field(default="NONE", alias="repeatType")
    daily_recurrences_type: Optional[DailyRecurrencesType] = Field(default=None, alias="dailyRecurrencesType")
    day_every: Optional[int] = Field(default=None, alias="dayEvery")
    day_in_month: Optional[int] = Field(default=None, alias="dayInMonth")
    day_in_week: Optional[int] = Field(default=None, alias="dayInWeek")
    week_every: Optional[int] = Field(default=None, alias="weekEvery")
    on_mon: bool = Field(default=False, alias="onMon")
    on_tue: bool = Field(default=False, alias="onTue")
    on_wed: bool = Field(default=False, alias="onWed")
    on_thu: bool = Field(default=False, alias="onThu")
    on_fri: bool = Field(default=False, alias="onFri")
    on_sat: bool = Field(default=False, alias="onSat")
    on_sun: bool = Field(default=False, alias="onSun")
    on_hol: bool = Field(default=False, alias="onHol")
    monthly_recurrence_type: Optional[str] = Field(default=None, alias="monthlyRecurrenceType")
    month_every: Optional[int] = Field(default=None, alias="monthEvery")
    monthly_week_in_month: Optional[int] = Field(default=None, alias="monthlyWeekInMonth")
    yearly_recurrence_type: Optional[str] = Field(default=None, alias="yearlyRecurrenceType")
    yearly_week_in_month: Optional[int] = Field(default=None, alias="yearlyWeekInMonth")
    year_every: Optional[int] = Field(default=None, alias="yearEvery")
    month: Optional[int] = None
    color_id: int = Field(default=1, alias="colorId")
    color_hex: Optional[str] = Field(default=None, alias="colorHex")


class UpcomingEvent(_ApiModel):
    """``nearestUpcomingEvent`` field on a Scheduler — a denormalized event preview."""
    id: int
    zone_id: int = Field(alias="zoneId")
    sources: list[SourceSummary] = Field(default_factory=list)
    category: Category
    scheduler_id: int = Field(alias="schedulerId")
    name: Optional[str] = None
    from_: str = Field(alias="from")  # ISO datetime "YYYY-MM-DDTHH:MM"
    exception: bool = False
    scheduler_name: Optional[str] = Field(default=None, alias="schedulerName")
    scheduler_color_id: Optional[int] = Field(default=None, alias="schedulerColorId")
    scheduler_color_hex: Optional[str] = Field(default=None, alias="schedulerColorHex")
    autostart: bool = True
    visual_profile_enabled: VisualProfileEnabled = Field(default="DEFAULT", alias="visualProfileEnabled")


class Scheduler(_ApiModel):
    """A scheduled audio rule — recurrence + time-of-day + zone + sources."""
    id: int
    name: Optional[str] = None
    zone_id: Optional[int] = Field(default=None, alias="zoneId")
    category: Optional[Category] = None

    # Recurrence interval (flattened on the Scheduler object)
    start_on: Optional[str] = Field(default=None, alias="startOn")
    end_on: Optional[str] = Field(default=None, alias="endOn")
    end_on_type: EndOnType = Field(default="NO_END", alias="endOnType")
    max_occurencies: Optional[int] = Field(default=None, alias="maxOccurencies")
    repeat_type: RepeatType = Field(default="NONE", alias="repeatType")
    daily_recurrences_type: Optional[DailyRecurrencesType] = Field(default=None, alias="dailyRecurrencesType")
    day_every: Optional[int] = Field(default=None, alias="dayEvery")
    week_every: Optional[int] = Field(default=None, alias="weekEvery")
    on_mon: bool = Field(default=False, alias="onMon")
    on_tue: bool = Field(default=False, alias="onTue")
    on_wed: bool = Field(default=False, alias="onWed")
    on_thu: bool = Field(default=False, alias="onThu")
    on_fri: bool = Field(default=False, alias="onFri")
    on_sat: bool = Field(default=False, alias="onSat")
    on_sun: bool = Field(default=False, alias="onSun")
    on_hol: bool = Field(default=False, alias="onHol")
    monthly_recurrence_type: Optional[str] = Field(default=None, alias="monthlyRecurrenceType")
    month_every: Optional[int] = Field(default=None, alias="monthEvery")
    monthly_week_in_month: Optional[int] = Field(default=None, alias="monthlyWeekInMonth")
    yearly_recurrence_type: Optional[str] = Field(default=None, alias="yearlyRecurrenceType")
    yearly_week_in_month: Optional[int] = Field(default=None, alias="yearlyWeekInMonth")
    year_every: Optional[int] = Field(default=None, alias="yearEvery")
    month: Optional[int] = None

    # Time-of-day
    time_scheduling_type: TimeSchedulingType = Field(default="SPECIFIC_TIME", alias="timeSchedulingType")
    specific_times: list[SpecificTime] = Field(default_factory=list, alias="specificTimes")
    relative_times: list[RelativeTime] = Field(default_factory=list, alias="relativeTimes")

    # Sources & playback
    sources: list[SourceSummary] = Field(default_factory=list)
    autostart: bool = True
    queueable: bool = True
    enabled: bool = True

    # Visuals
    color_id: int = Field(default=1, alias="colorId")
    color_hex: Optional[str] = Field(default=None, alias="colorHex")
    visual_profile_enabled: VisualProfileEnabled = Field(default="DEFAULT", alias="visualProfileEnabled")
    visual_profile_id: Optional[int] = Field(default=None, alias="visualProfileId")
    custom_text: Optional[str] = Field(default=None, alias="customText")

    nearest_upcoming_event: Optional[UpcomingEvent] = Field(default=None, alias="nearestUpcomingEvent")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateSet(_ApiModel):
    """The 'content + schedulers' container inside a Template."""
    id: int
    template_id: int = Field(alias="templateId")
    sources: list[SourceSummary] = Field(default_factory=list)
    single_files: list[LibraryItem] = Field(default_factory=list, alias="singleFiles")
    schedulers: list[Scheduler] = Field(default_factory=list)


class TemplateUsage(_ApiModel):
    """One application of a template to a zone — ``interval`` + ``zone`` summary."""
    interval: RecurrenceInterval
    zone: Optional[Zone] = None
    template: Optional["Template"] = None  # forward ref — sometimes present, sometimes just zone


class Template(_ApiModel):
    id: int
    name: str = ""
    type: Category
    template_sets: list[TemplateSet] = Field(default_factory=list, alias="templateSets")
    used_in_zones: list[TemplateUsage] = Field(default_factory=list, alias="usedInZones")


# ---------------------------------------------------------------------------
# Events (materialized occurrences)
# ---------------------------------------------------------------------------

class Event(_ApiModel):
    id: int
    zone_id: int = Field(alias="zoneId")
    sources: list[SourceSummary] = Field(default_factory=list)
    category: Category
    scheduler_id: Optional[int] = Field(default=None, alias="schedulerId")
    template_id: Optional[int] = Field(default=None, alias="templateId")
    template_name: Optional[str] = Field(default=None, alias="templateName")
    name: str = ""
    from_: str = Field(alias="from")
    to_: Optional[str] = Field(default=None, alias="to")
    color_id: int = Field(default=1, alias="colorId")
    color_hex: Optional[str] = Field(default=None, alias="colorHex")
    exception: bool = False
    scheduler_name: Optional[str] = Field(default=None, alias="schedulerName")
    scheduler_color_id: Optional[int] = Field(default=None, alias="schedulerColorId")
    scheduler_color_hex: Optional[str] = Field(default=None, alias="schedulerColorHex")
    single_event: bool = Field(default=False, alias="singleEvent")
    autostart: bool = True
    visual_profile_enabled: VisualProfileEnabled = Field(default="DEFAULT", alias="visualProfileEnabled")


# ---------------------------------------------------------------------------
# Opening hours
# ---------------------------------------------------------------------------

class OpeningHoursDay(_ApiModel):
    open: str = "08:00"
    close: str = "17:00"
    active: bool = True


class OpeningHours(_ApiModel):
    name: str = ""
    starting_day: int = Field(default=1, alias="startingDay")  # 1=Monday
    monday: OpeningHoursDay = Field(default_factory=OpeningHoursDay)
    tuesday: OpeningHoursDay = Field(default_factory=OpeningHoursDay)
    wednesday: OpeningHoursDay = Field(default_factory=OpeningHoursDay)
    thursday: OpeningHoursDay = Field(default_factory=OpeningHoursDay)
    friday: OpeningHoursDay = Field(default_factory=OpeningHoursDay)
    saturday: OpeningHoursDay = Field(default_factory=lambda: OpeningHoursDay(active=False))
    sunday: OpeningHoursDay = Field(default_factory=lambda: OpeningHoursDay(active=False))


# ---------------------------------------------------------------------------
# Visual / palette / misc
# ---------------------------------------------------------------------------

class VisualProfile(_ApiModel):
    id: int
    name: str
    description: Optional[str] = None
    text: Optional[str] = None
    text_layout: Optional[str] = Field(default=None, alias="textLayout")
    scroll_speed: Optional[int] = Field(default=None, alias="scrollSpeed")
    font_colour_hex: Optional[str] = Field(default=None, alias="fontColourHex")
    background_colour_hex: Optional[str] = Field(default=None, alias="backgroundColourHex")
    audio_sync: bool = Field(default=True, alias="audioSync")
    repetition: int = 1
    time_limit: bool = Field(default=False, alias="timeLimit")
    duration: int = 15
    light_enabled: bool = Field(default=False, alias="lightEnabled")
    paging_default: bool = Field(default=False, alias="pagingDefault")
    announcement_default: bool = Field(default=False, alias="announcementDefault")
    used: bool = False


class Color(_ApiModel):
    id: int
    name: str
    color_hex: str = Field(alias="colorHex")


class LocalDateTime(_ApiModel):
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    day_of_week: str = Field(alias="dayOfWeek")
    zone_id: str = Field(alias="zoneId")
    zone_offset: str = Field(alias="zoneOffset")
    iso8601: str


# Resolve forward references
TemplateUsage.model_rebuild()
Zone.model_rebuild()
