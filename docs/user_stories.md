# User stories

Pulls intent from [`user_personas.md`](user_personas.md). Each story names
the persona, the goal in their words, and the *system behaviors* the
integration test suite asserts on. Stories are deliberately scoped small
so each one corresponds to one to three turns of chat.

Stories marked **[TESTED]** have an automated equivalent in
[`tests/test_chat_integration.py`](../tests/test_chat_integration.py).
Stories marked **[MANUAL]** require human judgment or external state
(e.g., real Axis hardware) and are not part of the automated suite.

---

## Maya — K-12 administrator

### M1 [TESTED] Plain greeting must work
> *"hi"*

System must respond with a friendly hello + offer to help — even though
the user input is one word against a 14.5K-token prefix. This is the
canonical test for the empty-STOP retry: bare greetings used to fail
~57% of the time before the round-0 retry-with-nudge fix.

**Assertions.**
- Response text is non-empty.
- `finish_reason == "STOP"` (not `SAFETY`, not `OTHER`).
- No `empty_info` in the final `done` event.
- Round count ≤ 3 (allows model to fetch site/date context).

### M2 [TESTED] What zones do I have?
> *"List the physical zones at this site."*

System must call the appropriate read-tool and produce a human-readable
list. Maya must not need to know what "zone" means in the database
sense.

**Assertions.**
- At least one tool call to a read-side tool (`list_physical_zones`,
  `describe_site`, or `list_sites`).
- Response mentions at least one real zone (the seeded fixture has
  classrooms, gym, cafeteria, lounge).
- No `TOOL_ERROR` returns from any call.

### M3 [TESTED] What's on today's schedule?
> *"What's scheduled to play today?"*

The model should ground "today" against `get_local_date_time` and then
pull the day's schedule via a read tool.

**Assertions.**
- Calls `get_local_date_time` somewhere in the loop.
- Calls at least one of: `describe_site`, `list_schedule_events`.
- Response is non-empty markdown.

### M4 [TESTED] Multi-turn context: greeting then follow-up
> *Turn 1: "hi"*
> *Turn 2: "what zones are at this site?"*

The second turn must use the conversation history (passed in the API
call) and answer about zones, not loop back to greetings.

**Assertions.**
- Both turns finish with `STOP`.
- Turn 2 calls a read-side tool.
- Turn 2's response mentions zones.

### M5 [MANUAL] Stage and apply a schedule change
> *"Add a fire drill at 2 PM next Tuesday."*

This involves the staging-diff workflow which currently has unwired Apply
buttons in the web UI. Listed here so it appears in the backlog; not
asserted automatically because we don't want to leave staging-table
debris from CI runs.

### M6 [MANUAL] One-off early dismissal
> *"Wednesday is an early dismissal — shift everything after 11 AM 90
> minutes earlier."*

Same reason as M5: staging changes; not asserted in the automated suite.

---

## Tom — IT director

### T1 [TESTED, network-permitting] Discover devices
> *"Discover Axis speakers on the network."*

Asserts that the model calls a discovery tool. The actual hit count
depends on the LAN — the test passes whether 0 or N devices come back,
as long as the tool runs cleanly.

**Assertions.**
- Calls one of: `discover_axis_devices`, `test_axis_discovery_methods`.
- No `TOOL_ERROR`.
- Response is non-empty.

### T2 [MANUAL] Onboard a specific device
> *"Onboard the speaker at 192.168.1.123."*

Requires real hardware. Listed for backlog visibility.

### T3 [MANUAL] Bulk fleet onboarding
> *"Onboard all the unconfigured Axis speakers you can find on 192.168.1.0/24."*

Requires real hardware.

---

## Sarah — front-office manager

### S1 [TESTED] What do you offer? (capability discovery)
> *"What can you help me with?"*

A first-time user should get a clear, non-jargon answer. The model
should mention scheduling, audio, and announcements in some form.

**Assertions.**
- Response is non-empty.
- Response mentions at least two of: schedule, audio, announcement,
  device, zone (model has latitude on exact phrasing).
- `finish_reason == "STOP"`.

### S2 [MANUAL] Add a one-off announcement
> *"Play the welcome chime in the lobby at 9 AM next Monday."*

Staging-write path; deferred per M5.

---

## David — AV integrator

### D1 [TESTED] Describe a new site
> *"Tell me about this site — what's already configured?"*

The starting move on a new install. The model should walk the
read-side and produce an overview.

**Assertions.**
- Calls `describe_site`.
- Response mentions multiple of: zones, destinations, sources,
  schedule, templates.
- No `TOOL_ERROR`.

### D2 [MANUAL] Re-running setup is idempotent
> *"Onboard 192.168.1.123."* (run twice)

Requires hardware; tested via `scripts/test_device_*` in the dev loop.

---

## Cross-cutting (not tied to a single persona)

### X1 [TESTED] No hallucinated tool calls
> Any of the prompts above.

If any tool call returns a string starting with `TOOL_ERROR: Unknown
tool: ...` the model has invented a tool. This was a real regression
(`get_local_date_time` was being hallucinated until we added the real
tool). Asserted on every integration test as a shared invariant.

### X2 [TESTED] No safety blocks during normal use
> Any of the prompts above.

The `empty_info` event captures both prompt-side and response-side
safety blocks. The integration tests assert this field is absent on a
clean run. (If a future system-prompt edit accidentally trips a
classifier, we'll see it here first.)

### X3 [TESTED] Response is finite
> Any of the prompts above.

`MAX_TOOL_ROUNDS` (chat.py) caps the tool-call loop. The tests assert
no test ends with the loop-cap exhaustion message.

---

## How a story becomes a test

Each `[TESTED]` story corresponds to one `test_<id>_<short_name>`
function. The shared `chat_helper` fixture in `tests/conftest.py`
provides a thin wrapper around the chat endpoint plus cross-cutting
invariants (X1, X2, X3) applied automatically.
