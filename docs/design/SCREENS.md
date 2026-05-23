# AampEasyScheduler — Screen specifications

Per-screen functional + interaction notes for Claude Design. Companion to `BRIEF.md` and `PROMPT.md`.

## Information architecture (sidebar nav)

Left sidebar, persistent. Collapsible to icons-only on narrow widths. From top to bottom:

- Logo / wordmark
- **Chat** (home — the primary surface)
- **Schedule** (calendar / timeline editor)
- **Devices** (fleet status + onboarding)
- **Library** (audio assets: bells, effects, music, voice)
- **Destinations** (zone groups)
- *(spacer)*
- **Audit** (credential-access log, recent system actions)
- **Settings** (credentials list, server config, account)
- User avatar / dropdown

The Chat surface is always one click away. Tool-call results from the chat often deep-link into one of the other surfaces ("View the schedule" → Schedule tab).

---

## 1. Chat workspace (home)

The user's home view. Two-column layout on a wide screen:

**Left column (~62% width): conversation panel**
- Big, comfortable chat scrollback. Assistant and user messages distinguishable but both feel like equal participants.
- Assistant messages can contain inline summaries of tool calls. By default these are collapsed cards (single line: tool name + status icon + 1-line outcome). Expand for full args + result.
- Multi-step tool sequences (like a 4-step `onboard_axis_device` run) get a single "expandable step trace" card per assistant turn, not 8 separate messages.
- Code-like content (JSON, the system prompt) is in a monospaced, dimmed block.
- The input box has: text area, file attach (PDF/CSV/image), and a context indicator showing "what site / which devices currently in scope."
- Keyboard-driven: ⌘+Enter sends, ⌘+/ focuses the input, ⌘+K opens a quick command palette.

**Right column (~38% width): the day at a glance**
- "Today, Friday, May 22" header.
- A vertical time-axis from earliest event to latest, showing the events as compact rows.
- Each row: time chip (08:25, monospaced) + label ("warning bell, all classrooms") + a small status dot (scheduled / fired / failed).
- Below: "Next change" callout if the user has staged-but-not-applied changes ("3 changes pending — type 'apply' to confirm").
- Click any event to jump to it in the Schedule view.

**Header**
- Site name (e.g. "Lincoln Middle School") with a small status pill (green = AAM Pro reachable, amber = degraded, red = offline). NEVER show the AAM Pro server's hostname/IP — that's noise.
- A compact "today's date" display so the user knows what reference frame the assistant is using.

**Empty state**
- For a brand-new site, the chat starts with the assistant introducing itself, asking the site-identity question (per `system_prompt.md` Step 0).
- Right column shows "No schedule yet" with a hint: "Tell me about your bell schedule on the left."

---

## 2. Schedule (calendar / timeline editor)

The audio calendar — the operational view of "what plays when, where."

**View modes** (pill toggle, top of view): **Week** (default), **Month**, **Day**.

**Week view**
- Mon–Sun across the top; time-of-day down the left (06:00–18:00 default range).
- Each scheduled event is a chip: time, label, destination, color-coded by template (regular_day = neutral, block_day = accent, fire_drill = warning, music = soft secondary).
- Recurring vs one-off: recurring events have a small "loop" icon; one-offs have a "•" marker.
- Click a chip → detail drawer (right side) with: time, what plays (source from library), which destination, recurrence rule, exception dates, last actually-fired timestamp.
- Top-right: "+" button → "Add bell" dialog. Defaults to a template if the user has one selected.

**Month view**
- Standard month grid. Each day cell shows a compact event count and a colored dot per active template.
- Hover a day → tooltip with the day's events listed compactly.

**Day view**
- Vertical timeline, full width. Used for the day-of view ("what's about to happen at 14:30?") and for deep editing of a single day.

**Side rail**
- Filter by destination (multi-check). "Show only: Elementary classrooms."
- Filter by template ("Show only block_day events").
- Toggle to overlay AAM Pro's own scheduler view in greyed-out behind ours (rare; for power users diagnosing drift).

**Diff state**
- When the user has staged changes (via chat), the view shows a banner: "3 changes pending — review and apply." Click → drawer showing each change as a before/after card. Two buttons: "Apply" / "Discard."

---

## 3. Devices (fleet)

Status of every onboarded Axis device.

**Top: stats row** (4 compact stat cards)
- Total devices
- Online
- Needs attention (offline > 30s, ACAP stopped, drifted from intended config)
- Pending onboarding (in discovery but not yet provisioned)

**Main: device table**
Columns:
- Status dot (green/amber/red)
- Model + audio subtype chip ("C1110-E" + small "speaker" tag)
- Friendly name (editable inline; this matters — operators name speakers by physical room)
- IP address
- MAC
- Firmware version
- Destination/zone assignment
- Last contact
- Actions (kebab menu: ping, factory-reset, remove)

Table is sortable, filterable, paginated. The whole table is keyboard-navigable.

**Side rail: discovery panel**
- "Discover devices" button — kicks off the multi-protocol scan in the background.
- Per-protocol breakdown shows live as it runs (mDNS: 9 found, http-sweep: 5 found, etc.).
- Devices found but not yet onboarded appear in a "Found, not onboarded" section below the main table — one-click to start the onboard flow per device.

**Device detail drawer** (click a row)
- Tabs: Overview, Schedule (events firing on this device), Logs (last 50 audit entries for this device), Diagnostics (LED-flash button, beep button, restart, factory-reset with confirm).
- Overview shows everything in the row plus: serial, hardware id, architecture, ACAP version + status, server pointer value, latest health probe.

---

## 4. Onboarding flow (device)

A dialog/modal launched from the Devices view ("Onboard 192.168.1.123" button).

**Step 1: Identify**
- Shows what we know pre-auth: IP, MAC, mDNS service tags, classification ("audio:speaker" via the audiosite mDNS signal).
- Big confirmation: "This looks like an Axis network audio device. Proceed?"

**Step 2: Authenticate**
- One of three branches based on `try_authenticate`:
  - **Factory-default device** (needs root creation): shows a yellow callout — "This device has no admin user yet. We'll set the fleet default password on it. To set or change that password, run `aamp-set-credential device/default_password` in your terminal." If no fleet password is set, the Continue button is disabled and a "Capture password" link opens a help drawer with the CLI command (and, in the future, a one-time-URL flow).
  - **Already provisioned, candidate worked**: green check — "Authenticated with the fleet password."
  - **Unknown password**: red callout — "None of the configured passwords worked. Add this device's password to the candidates list with `aamp-set-credential device/password_candidates`, or factory-reset the device."

**Step 3: ACAP install**
- A progress bar with sub-steps: upload (~5s), start (~2s), verify (~1s).
- Shows the .eap filename + size, and the device's self-reported architecture.

**Step 4: Server pointer**
- Shows what we're telling the device: "This device should connect to AAM Pro at 192.168.1.127." (The interface-inferred IP.)
- After confirm: writes the param, then polls for the device to appear in `aam_dev` (max 30s with a soft animation indicating "waiting for the device to call home").

**Success state**
- Green checkmark. Device's friendly name + suggested zone assignment.
- "Assign to a destination" inline action.

**Failure state**
- Red callout with the step that failed + the actionable error from the tool. Includes a "Retry" button and a "Copy diagnostic info" button.

---

## 5. Library

Audio assets organized by category.

**Tabs at top**: Bells • Effects • Music • Voice (generated) • All

**Grid view (default)**
- 4 columns at desktop width. Each card: small waveform thumbnail (auto-generated), title, duration, category, license badge (CC0 / CC-BY / Custom / Generated).
- Play button overlaid on hover. Spacebar plays/pauses the focused card.

**List view toggle**
- Switch to a denser table when the user has hundreds of assets.

**Detail drawer**
- Title, full waveform, "Used in" (which templates / events use this file), license + attribution text, file format/size, upload date.

**Upload action (top-right)**
- Drop zone for new audio files.

**Voice generation panel** (visible on the Voice tab)
- Text area: "What should this announcement say?"
- Voice picker: dropdown of preset voices.
- Generate button → progress → new card appears in the grid.

---

## 6. Destinations & zones

A grouping view: "what speakers play together."

**Two-pane layout**

**Left pane — destinations list**
- Card per destination: name, count of speakers in it, count of physical zones, primary use ("Bell announcements" / "Background music" / "Paging").
- "+ New destination" at the top.

**Right pane — selected destination detail**
- Speakers in this destination (list with status dots).
- Physical zones included.
- "Add device" / "Remove device" actions.
- "Used by" section — which scheduled events route to this destination.

---

## 7. Credentials & audit

Two-tab view: Credentials (top) / Audit log (bottom), or a single page with both.

**Credentials section**
- A table of stored credentials. Columns: account_id/field, description (from canonical table), backend ("Windows Credential Manager" / ".aamp_credentials"), last accessed.
- Value column: always `********`. **No reveal control. No copy button. No edit-in-place.**
- Each row has a kebab menu: "Show capture instructions" (opens a drawer with the `aamp-set-credential` CLI command and a copy-to-clipboard for the COMMAND, not the value) and "Delete" (with a confirmation dialog requiring the user to type DELETE).
- A banner at top: "Passwords are stored in Windows Credential Manager and never appear in this UI. To set or rotate, run the command shown for each row in your terminal."

**Audit log section**
- A virtualized table of recent credential access events.
- Columns: timestamp, op (get/set/delete/list), account/field, principal, decision.
- Filterable by op / principal / decision / time range.
- Export to JSONL.

---

## 8. Settings

A simple page with several cards:

- **Site identity** — the name + organization type captured during onboarding. Edit inline.
- **AAM Pro connection** — host, username (username is OK to show), connection-status pill, "Test connection" button.
- **Device fleet defaults** — default device user (usually `root`), advanced fleet behaviors (probe timeouts, retry counts).
- **Discovery preferences** — which discovery protocols are enabled by default (mDNS / http-sweep / ARP / SSDP / WS-Discovery).
- **About** — version, repo link, license, opening for "send feedback."

---

## 9. First-time setup wizard

Triggered when site identity is unset.

- Welcome card: "AampEasyScheduler manages audio schedules and Axis network audio devices for your site. Three questions before we start."
- Step 1: site name + organization type (school / office / retail / hospital / transit / other).
- Step 2: brief description, with examples from `system_prompt.md` (or accept "I'll add this later").
- Step 3: "Are there Axis network audio devices on this LAN already? We'll discover them now if you'd like — no changes will be made." → discovery breakdown + simple "yes onboard / no skip."
- Done card: drop the user into the Chat workspace with a friendly first message.

---

## Out-of-scope screens (deferred)

These exist conceptually but are not in this first-design batch:
- Multi-site management (one user, multiple AAM Pro deployments).
- Mobile-native layout (desktop-first; tablet should work, phones can wait).
- Public-facing screens (login / signup) — we're internal-tool-first.
- Embed / widget mode.
- Theme switching beyond a single dark-mode pass.

---

## Responsive expectations

- Designed for **1280×800 minimum**, optimized for **1440×900**, scales gracefully to 4K.
- Tablet (768–1024): the right-column "day at a glance" collapses into a top drawer; sidebar becomes a hamburger.
- Mobile is out of scope for v1 (the core workflows assume desktop).
