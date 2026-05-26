# User personas

The personas below drive what ChAAMP needs to do well, what jargon it must
*never* require, and which workflows the integration test suite exercises.
Each persona is paired with a set of user stories in
[`user_stories.md`](user_stories.md).

> *Note.* These are composite personas synthesized from school-bell-system,
> corporate paging, and house-of-worship AV install conversations. They are
> not real people. The site fixture used in tests is "Lincoln Middle School".

---

## Maya Rivera — K-12 administrator (primary)

**Title.** Assistant principal / operations lead, Lincoln Middle School (grades 6-8, ~750 students).

**Demographics.** 38, ten years in K-12 admin. Comfortable with email, Google
Workspace, and Excel; has never opened a network configuration tool. Has
heard of AAM Pro because it was installed during the last building
renovation; has touched it twice in the past year.

**What she knows cold.** First bell, passing periods, lunch waves, dismissal,
which days are early release, what the announcement chime should sound
like, when the spring concert is. She *runs* the bell schedule.

**What she does not know.** What a "destination" is, what a "template" is,
how a "scheduler" differs from a "schedule". She has never typed
`192.168.1.123` into anything and would not know whether her speakers run
ACAP.

**Top pains.**
- Setting up a new bell schedule in AAM Pro's GUI takes ~45 minutes of
  clicking, with several places where one wrong click silently breaks the
  whole day.
- One-off changes (e.g., "early dismissal Wednesday because of the
  assembly") require her to either edit the schedule in a way she'll have
  to manually undo, or skip the system and announce verbally.
- She cannot tell what is scheduled to play tomorrow without opening the
  GUI and clicking through six screens.

**What success looks like for her.**
- She types in English, the system reads back her intent in English, she
  confirms, the change applies.
- She can ask "what's on for Friday?" and get a one-paragraph answer.
- She never sees the words "scheduler", "destination", or "template" unless
  she opts into the technical view.

**Where ChAAMP must NOT compromise.**
- A wrong bell time during a fire drill is a safety issue. The Apply
  step must be explicit and always show a diff first.
- Maya should never be asked for an IP, MAC, or password in chat.

---

## Tom Becerra — IT director, school district

**Title.** Director of Technology, Maple Grove School District (3 schools,
~150 staff, ~2200 students).

**Demographics.** 52, twenty years in district IT. Comfortable with Windows
Server, mid-comfortable with Linux, knows enough networking to read a
packet capture but not deeply. Has owned the AAM Pro deployment for two
years and knows it grudgingly.

**What he knows cold.** VLAN layout, DHCP scopes, which switch ports feed
which rooms. The phrase "192.168.1.0/24" makes sense to him. He knows
that Axis devices ship with a factory-default password he has to change
on first boot.

**What he does not know.** The internals of AAM Pro's scheduling model.
He delegates that to whoever owns the schedule at each school.

**Top pains.**
- Onboarding a new speaker or amp requires roughly 8 manual steps in the
  Axis web UI per device. Multiply by 12 devices = an afternoon.
- When a device drops off the network he has to log into the device,
  AAM Pro, *and* the switch port to figure out where the fault is.
- Fleet-wide password rotation across 60 devices is a nightmare he keeps
  postponing.

**What success looks like for him.**
- "Discover speakers on the 192.168.1 subnet" returns a one-screen list.
- "Onboard 192.168.1.123" walks the device from factory-default to
  registered-with-AAM-Pro without him touching a browser.
- Bulk operations have a clear dry-run mode.

**Where ChAAMP must NOT compromise.**
- Credentials must never enter chat or the LLM context window.
- Tools that modify a device must say so up front — no surprise writes.

---

## Sarah Khoury — front-office manager, corporate HQ

**Title.** Office manager, Northpoint Holdings (single floor, ~120 staff,
one open-plan area + four conference rooms).

**Demographics.** 28, two years in this role. Lives in Slack and Google
Calendar. The IT contractor handles anything network-shaped.

**What she knows cold.** When the all-hands plays the welcome chime, when
the lunch reminder plays, what tone the executive team prefers, when the
office is closed.

**What she does not know.** Anything past "we have speakers in the
ceiling". She did not install AAM Pro and does not know it exists by
name — to her it's "the building audio system".

**Top pains.**
- Adding a one-time announcement for a visiting customer is currently a
  "ask IT, IT does it next Tuesday" workflow.
- She has no way to see what's already scheduled — she has to remember.

**What success looks like for her.**
- A single screen with the upcoming day's audio events listed in plain
  English.
- She can stage a one-off ("play the welcome chime in the lobby at 9 AM
  Friday") and either apply it herself or hand a link to IT.

**Where ChAAMP must NOT compromise.**
- The interface must be self-explanatory for a non-technical user.
- Nothing should ever "just play" without her confirming.

---

## David Park — AV systems integrator (vendor)

**Title.** Owner / lead installer, ClearTone AV.

**Demographics.** 45, fifteen years in commercial AV. Comfortable with
network gear, OEM tooling, and reading vendor spec sheets. Bills time by
the hour.

**What he knows cold.** Axis device families, the ACAP installer flow,
what "AAM Pro client_id / client_secret" means, what good cable looks
like.

**What he does not know.** Each customer's preferred bell schedule or
business hours. He's the install crew, not the daily operator.

**Top pains.**
- Standing up a new site means duplicating the same setup workflow across
  many customers — usually with slightly different naming conventions and
  zone layouts each time.
- After the install, customers call him back for "small" tweaks that take
  20 minutes of GUI clicking each.

**What success looks like for him.**
- A reusable workflow: "describe this site" reveals what's there;
  "onboard the four devices on this subnet" finishes most of the install;
  "set up a default Monday-Friday bell schedule" produces a starting
  point Maya can edit.
- Once the site is alive, the customer can self-serve the small tweaks
  via chat — fewer callbacks.

**Where ChAAMP must NOT compromise.**
- Idempotent operations: re-running "onboard 192.168.1.123" on an
  already-onboarded device must not break it.
- A clear audit trail of every change he or the customer makes.

---

## How these drive the test suite

The integration tests in [`tests/test_chat_integration.py`](../tests/test_chat_integration.py)
exercise the chat backend (POST `/api/chat/message`) with prompts each
persona is plausibly typing, then assert that:

- The chat returns a non-empty, finite response (no empty-STOP, no
  safety block).
- The model invokes the *category* of MCP tool the persona's intent
  demands (e.g., a "what are my zones" question must touch a read-tool,
  not a write-tool).
- The model never hallucinates tool names (no `TOOL_ERROR: Unknown tool`).
- Write-class operations always go through staging and never apply
  silently.

This is integration-shaped, not unit-shaped, because the surface we care
about is the model's behavior given our real prompt + real tools. The
tests cost ~$0.01 each at current Gemini Pro pricing.
