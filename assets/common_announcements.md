# Common school announcements

Curated list of phrases the chat can generate on demand once the ElevenLabs
integration is wired up. These are general-purpose templates — actual schools
should personalize names, times, etc.

## Daily routine

| Slug | Suggested text | When |
|---|---|---|
| `good_morning` | "Good morning, [School Name]. Today is [day]. Please stand for the Pledge of Allegiance." | Morning, start of day |
| `morning_announcements` | "Good morning. This is your morning announcement." | Morning bulletin |
| `lunch_dismissal_grade1` | "First-grade students, please proceed to the cafeteria for lunch." | Lunch waves |
| `lunch_dismissal_grade2` | "Second-grade students, please proceed to the cafeteria for lunch." | Lunch waves |
| `recess_start` | "Recess begins now. Please proceed safely to the playground." | Recess |
| `recess_end` | "Recess is over. Please return to your classrooms." | Recess end |
| `dismissal` | "School is dismissed. Please walk safely to your bus or pickup area." | End of day |
| `late_bell_warning` | "The bell will ring in two minutes. Please head to your next class." | Two-minute warning |

## Safety / drills

| Slug | Suggested text | When |
|---|---|---|
| `fire_drill_start` | "This is a fire drill. Please exit the building calmly via the nearest fire exit and proceed to your assembly point." | Drill (NOT for real fire — real fire uses the alarm system, not the announcement system) |
| `fire_drill_end` | "The fire drill is over. Please return to your classrooms in an orderly manner." | After drill |
| `lockdown_drill` | "This is a lockdown drill. Please follow lockdown procedures. Teachers, secure your classrooms." | Drill only |
| `severe_weather` | "Severe weather has been detected. Please move away from windows and follow your shelter-in-place procedures." | Weather event |
| `early_dismissal_weather` | "Due to weather conditions, school will dismiss [N] minutes early today. Buses will be available at [time]." | Snow / weather closure |
| `school_closed_tomorrow` | "School will be closed tomorrow due to [reason]. Please check the district website for updates." | Closure announcement |

## Events / special schedules

| Slug | Suggested text | When |
|---|---|---|
| `assembly_today` | "All students will report to the gymnasium at [time] today for the assembly." | Day of assembly |
| `pep_rally` | "Pep rally begins at [time]. All students please report to the gymnasium." | Day of pep rally |
| `early_release_reminder` | "Reminder: today is an early-release day. School dismisses at [time]." | Day-of |
| `picture_day` | "Today is picture day. Please proceed to the [location] when called." | Day-of |
| `field_trip_reminder` | "Field trip students, please gather at [location] at [time] with all permission slips." | Day-of |
| `parent_pickup` | "Parent pickup is now happening at the [location] entrance. Please proceed safely." | Pickup time |

## Visitor / staff

| Slug | Suggested text | When |
|---|---|---|
| `visitor_checkin` | "All visitors must check in at the main office before proceeding to classrooms." | Building entry reminder |
| `staff_meeting` | "Staff meeting at [time] in [location]. All staff are expected to attend." | Staff schedule |
| `substitute_alert` | "Will the substitute teacher for [class/teacher] please report to the office." | Office call |

## Transitions / passing periods

| Slug | Suggested text | When |
|---|---|---|
| `passing_period_warning` | "One minute remaining in the passing period." | Transitions |
| `period_change` | "Period [N] has ended. Please proceed to your next class." | Bell adjuncts (typically paired with a chime) |

## Generation guidelines

When the chat generates these via ElevenLabs:
1. **Pick a voice once per school** and reuse it for consistency (settings in
   `assets/voice/voice_config.json` once we wire that up).
2. **Bell-style brief**: announcements should be short (5-15 seconds typically),
   clear, and end with a downward inflection so they feel finished.
3. **Avoid filler**. Schools play these many times a day; "Um", "OK so", etc.
   become grating fast.
4. **Test before deploying**. Listen back through the actual AAM Pro speakers
   before scheduling — playback quality depends on the speaker setup.
5. **Name the file with the slug** above (e.g., `lunch_dismissal_grade1.mp3`)
   so the library is browsable later.

## Future: dynamic announcement templates

Once ElevenLabs is wired up and we have a Python tool to generate audio on
demand, the chat could:

- Accept user text directly: "Generate an announcement saying 'School will
  dismiss 30 minutes early today due to weather.'"
- Use slugs for stored versions: "Play the standard early-dismissal warning
  with 30 minutes substituted."
- Bulk-generate the entire above table at session start so the school has a
  baseline library available.
