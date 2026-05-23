# AampEasyScheduler — Design brief

Use this as the master attachment to Claude Design. The companion prompt is in `PROMPT.md` and per-screen specs in `SCREENS.md`.

## 1. What the product is

A natural-language scheduler for AXIS Audio Manager Pro. End users describe their audio schedule in plain English — *"play the warning bell at 8:25 and the period-start bell at 8:30, Monday through Friday, until June 15th"* — and the app translates that into AAM Pro's data model and applies it. It also handles the operational headache of onboarding Axis network audio devices: discovering them on the LAN, installing the AAM Pro ACAP, and pointing them at the server.

Two distinct workflows live in the app:

1. **Scheduling** — the primary, day-to-day use case. A school administrator (or other facility owner) describes the bell schedule conversationally; the app applies it to AAM Pro and visualizes the result.
2. **Device onboarding** — the occasional but important use case. IT staff add new speakers to the network. The app discovers them, classifies them as Axis audio devices, and provisions them.

## 2. Why it exists

AXIS Audio Manager Pro is powerful but operator-centric — destinations, templates, schedulers, zones, day-of-week bitmasks. A school principal who knows exactly when their bells should ring doesn't want to learn that data model. They want to *say what they mean* and have the system do it.

The wedge:
- **Conversational by default.** The chat surface is first-class, not a help bot bolted onto a forms-driven app.
- **Schedule-centric, not device-centric.** AAM Pro shows you zones and destinations; we show you the week ahead.
- **Plain English over jargon.** "Block day Tuesday" instead of "scheduler #983040 with day-mask 0b00010100".
- **Onboarding that just works.** Click a device on the discovery list, type a password into a TTY (never chat), watch it appear in AAM Pro 30 seconds later.

## 3. Audience

Primary persona: **school administrator / principal**
- Knows bells, periods, dismissal, fire drills, snow days.
- Doesn't know — and shouldn't need to know — what a "template" or "scheduler" is.
- Uses the app from a desktop browser, occasionally on tablet.
- Edits schedules a few times per quarter (start of year, mid-year adjustments).
- Reads the dashboard often. Tweaks settings rarely.

Secondary persona: **facility manager** (office, retail, transit, hospital)
- Different vocabulary — opening chimes, lunch announcement, all-call paging.
- Same shape of workflow — recurring schedule + occasional one-offs.

Tertiary persona: **IT/AV technician**
- Adds new speakers when they arrive. Diagnoses bad ones.
- Comfortable in a terminal for one-off password capture; doesn't want a terminal for everyday tasks.
- Needs the device fleet view, the audit log, and the discovery breakdown.

## 4. Tone & feel

- **Approachable, not childish.** The K-12 use case skews toward warm and human — but a hospital or office deployment can't feel like a kindergarten classroom. Confident, clear, calm.
- **Conversation-first interface, but not gimmicky.** The chat isn't a chatbot widget in the corner; it's the primary surface, sized like a real workspace.
- **Information-dense where it earns it.** The schedule calendar, the device fleet — these are operational tools and should feel like it. The chat and the dashboard get more breathing room.
- **Trust signals.** Onboarding hardware and managing credentials means the user must trust us. Visual choices should reinforce: "this is a tool that takes security seriously without making it scary."

## 5. Visual direction

### Cues to take from AXIS Communications
- **Sans-serif, type-driven hierarchy.** Axis is austere and confident — no decorative type, no flourishes. We follow.
- **High contrast for legibility.** Heavy black on near-white. Useful for accessibility too.
- **Photographic restraint.** Axis uses photography sparingly; product images, not lifestyle illustrations. We follow — when we show audio devices, show the device, not a stock photo of a happy classroom.
- **Card-based content layout** with generous whitespace between regions.
- **Mega-menu / sidebar navigation** for the operational sections.

### Where to diverge — "more modern and minimalistic"
- **Warmer accent color.** Axis is corporate blue → we use a deeper, more confident accent (suggest: a slightly desaturated indigo / blue-violet in the 240° range — feels "audio" without being literal, distinct from Axis's flatter blue).
- **Off-white backgrounds with a subtle warm tint** instead of pure white. Less clinical.
- **Generous corner radii** (12–16px on cards, 8–10px on inputs). Axis is more square; we're more soft-modern.
- **Layered shadows over hard borders.** Axis tends to use 1px hairline borders; we lean on subtle elevation.
- **Larger, more confident type at the top of the hierarchy.** Headings 28–40px, comfortable line-heights, leading air.
- **Audio identity, subtle.** Avoid literal speaker icons. Hint at time / frequency / waveforms through abstract motifs — maybe a subtle horizontal time-axis pattern in section dividers, never as decoration.
- **Motion: minimal, purposeful.** Schedule transitions when a day is selected. Soft slide-in for chat messages. No bouncy or attention-grabbing animations.

### Color palette (proposed — refine in design)

- **Ink** `#0F172A` — primary text, dense data
- **Slate-700** `#334155` — secondary text
- **Slate-300** `#CBD5E1` — borders, dividers
- **Surface** `#FAFAF7` — page background (off-white with warm cast)
- **Card** `#FFFFFF` — elevated surfaces
- **Accent** `#4F46E5` — primary actions, links, "the brand color" (indigo-500-ish)
- **Accent-soft** `#EEF2FF` — accent backgrounds, hover states
- **Success** `#059669` — onboarded device, schedule applied
- **Warning** `#D97706` — needs attention (device offline, drift detected)
- **Critical** `#DC2626` — errors, factory-default required
- **Audio gradient (use sparingly)** — a horizontal gradient from `#4F46E5` to a teal `#06B6D4` for the splash/hero. Suggests sound traveling across space.

### Typography (proposed)

- **Display + UI**: `Inter` — battle-tested, neutral, excellent at all sizes.
- **Numerics / time displays**: `JetBrains Mono` or `IBM Plex Mono` for the schedule grid — tabular figures, locked column widths. Adds an "operational dashboard" feel without breaking the calm.
- **Sizes**: 14px body, 16px lists, 20px section headings, 28px page headings, 40px display.

## 6. Distinct identity vs. AAM Pro itself

AAM Pro is the user's *system*. AampEasyScheduler is the user's *assistant*. The visual relationship should mirror that:
- AAM Pro has Axis's blue + structured dense forms. We have indigo + conversational + space.
- AAM Pro's main metaphor is "configuration." Ours is "schedule + conversation."
- Where AAM Pro shows you a settings page, we show you a chat. Where AAM Pro shows you a device list, we show you a fleet *map of status* with the list as a secondary view.

The visual differentiation matters because users will often have both open. AampEasyScheduler should feel like the friendly front desk; AAM Pro is the equipment room down the hall.

## 7. Brand mark suggestion (optional — Claude Design can propose)

Workmark only is fine. If a mark is wanted, something subtle: a stylized "a" with a soft wave through the crossbar, suggesting sound. Avoid speakers, megaphones, bells — too on-the-nose for a tool that's about *scheduling* sound, not about being a speaker.

## 8. Key product moments to design

Listed in priority order. See `SCREENS.md` for the per-screen functional spec.

1. **Chat workspace (the home view).** Where the user spends most of their time. A big conversation panel + the day's schedule at a glance on the side.
2. **Schedule overview.** Week / month / day views of the audio calendar. Editable inline. The "did the bells ring correctly today?" surface.
3. **Device fleet.** Status of every onboarded Axis device — speakers + amplifiers + paging consoles. Health, last contact, model, MAC, audio zone assignment.
4. **Device onboarding flow.** Discovery → classify → confirm → provision. Multi-step, but each step is a single decision.
5. **Library.** Browse bells / effects / music / voice-generated announcements with playback.
6. **Destinations & zones.** Group management (which speakers are "Elementary" vs "Gym" vs "Lobby").
7. **Credentials & audit.** A masked list of stored credentials + the audit log. No reveal in UI — operator goes to a terminal to set new ones.
8. **Onboarding (first-time user).** Welcome → site identity → first schedule. Should feel like a 5-minute setup.

## 9. Hard constraints from the existing implementation

These are NOT negotiable design choices — they reflect security or product decisions already shipped:

- **Passwords NEVER appear in the UI.** Not as `*****` reveal, not as a "show password" toggle. Setting a credential happens in a terminal via `aamp-set-credential` today; the future web flow uses a one-time URL with an HTML form that the LLM cannot read. The UI surfaces *that credentials exist* (a list with `********`) but never the values.
- **The chat is real chat, not a wizard.** The user types, the agent responds, sometimes calls tools. Tool calls are visible but collapsed by default. No scripted-button flows pretending to be a chat.
- **Tool calls are auditable.** A "details" view per assistant message that shows which MCP tool was called, with what args (post-scrub), and what the result was.
- **Schedule changes are confirmed before apply.** Plan first, apply on confirmation. The UI must show the diff (what's being added / changed / removed) before commit.

## 10. Supporting materials available

To attach alongside this brief in Claude Design:

- `README.md` — public project overview
- `docs/credential_handling.md` — the password / security architecture
- `docs/axis_device_onboarding.md` — empirical reference for the device side
- `src/aamp/system_prompt.md` — the chat agent's instructions (gives you a sense of voice + behavior)
- `docs/design/SCREENS.md` — per-screen functional + interaction spec
- Optionally: a few real screenshots of AAM Pro's SPA (for "what we're sitting on top of" context — we are NOT trying to look like it)
