# Claude Design prompt — AampEasyScheduler

Below is the prompt to paste into Claude Design as the kickoff message. Attach `BRIEF.md` and `SCREENS.md` from this directory as supporting documents. Optionally also attach `README.md`, `docs/credential_handling.md`, and `src/aamp/system_prompt.md`.

---

## Prompt (paste this verbatim)

I want to design a desktop web app called **AampEasyScheduler** — a natural-language scheduler for AXIS Audio Manager Pro that also handles automated onboarding of Axis network audio devices. I've attached a full brief (`BRIEF.md`) and a per-screen functional spec (`SCREENS.md`). Please read both end-to-end before generating anything — the visual direction in `BRIEF.md` (section 5) and the hard constraints (section 9) are both important.

**One-paragraph summary so you have it in context as you work:** a school administrator or facility manager types in plain English what they want their bell schedule to do (or describes their audio scheduling needs more broadly), and the app translates that into AAM Pro's data model. A separate, occasional workflow handles onboarding new Axis network audio speakers — discovery on the LAN, classifying them, installing the AAM Pro ACAP, and pointing them at the server. The chat interface is the primary surface; everything else is a way of visualizing and editing what the chat does.

**Visual direction (recap):** take design cues from Axis Communications' enterprise-modern aesthetic — sans-serif, type-driven hierarchy, restrained use of photography, card-based layouts, high contrast — but push toward something **more modern, more minimal, and warmer**. Use a confident indigo accent (`#4F46E5`) over an off-white background (`#FAFAF7`) with white cards; generous corner radii (12–16px); subtle layered shadows over hard borders; tabular monospace digits for time displays; Inter for everything else. Avoid literal speaker / bell / megaphone iconography. The audio identity comes through subtle gradient accents (indigo → teal) and a tasteful time-axis motif, not cartoon speakers.

**What to design, in priority order:**

1. **The Chat workspace** (home view). Two-column layout — conversation panel on the left (~62%), "day at a glance" timeline on the right (~38%). This is where the user lives. Lean toward calm and spacious. Tool calls from the assistant collapse into compact summary cards inline; multi-step traces (like a 4-step device-onboarding pipeline) get a single expandable card per assistant turn, not eight separate messages.

2. **The Schedule view** — week / month / day calendar editor for the audio events. Recurring vs one-off events are visually distinct. Filter rail on the left. A "pending changes" banner with apply/discard when the chat has staged but not applied edits.

3. **The Devices fleet view** — a status table of every onboarded Axis device, with a discovery panel that shows live per-protocol breakdowns as they run.

4. **The Onboarding flow** for a new device — multi-step modal (Identify → Authenticate → ACAP install → Server pointer → Success). The Authenticate step has a yellow callout for factory-default devices that need a fleet password — and the callout must instruct the user to run a CLI command in their terminal rather than prompting for a password in the UI. (See `BRIEF.md` section 9 — no passwords in the UI ever.)

5. **The Credentials & audit view** — a masked table of stored credentials (always `********`, no reveal, no copy-the-value, ever) plus an audit log of access events.

If time permits, also: **Library** (audio assets browser), **Destinations** (zone groups), **Settings**, and a **first-time setup wizard**.

**A few things I want you to avoid:**

- **Don't** mimic AXIS Audio Manager Pro's actual SPA layout. We sit on top of AAM Pro but are deliberately differentiated — AAM Pro is the equipment room; we are the friendly front desk.
- **Don't** add a "show password" toggle anywhere. The architecture forbids passwords appearing in the UI.
- **Don't** lean into K-12 / school imagery. Schools are the primary use case but the app also serves offices, retail, hospitals, and transit hubs. Stay neutral.
- **Don't** use sound-wave / speaker / megaphone illustrations as primary decoration. Subtle motifs only.
- **Don't** scope mobile layouts — desktop first, tablet graceful, phone deferred.

**Output I'd like back:**

- A coherent design system: color tokens, typography scale, component primitives (button, input, card, table row, chip, status dot, modal, drawer, tab pill).
- Hi-fidelity mockups of the priority screens above.
- A small icon set used across the app — abstract and geometric, not skeuomorphic.
- A simple logo / wordmark proposal. Workmark-only is fine; if you propose a mark, see `BRIEF.md` section 7.
- A handoff bundle for Claude Code so I can move directly into implementation.

When you have a first pass, focus the iteration on the Chat workspace first — that's where 80% of the time will be spent, and the rest of the design system flows from getting it right.

---

## Tips for refining inside Claude Design

After the first round of mockups comes back:

- **If the indigo feels too tech-startup**, ask Claude Design to explore a deeper blue-violet (closer to `#3730A3`) or a desaturated steel-blue. Avoid sliding toward Axis's exact corporate blue.
- **If the chat surface feels chatbot-y** (avatar bubbles, sales-floor pastels), push toward a more workspace-document feel — flatter rows, more horizontal space, less rounded chat-bubble framing.
- **If the schedule grid feels too dense**, increase row spacing, soften the grid lines, and lean harder on the monospaced time chips.
- **If the device fleet feels enterprise-cold**, soften with row hover states, a kinder empty state, and chip-style status indicators rather than colored backgrounds.
- **For the audit log**: explicitly ask for "non-scary security tone" — operators read this log routinely and shouldn't feel like they're staring at a SIEM dashboard.

## After Claude Design — handoff to Claude Code

When the design system + screens are settled:

1. Export the handoff bundle from Claude Design.
2. In Claude Code (this repo): `Implement the attached Claude Design bundle as a SvelteKit (or Next.js — pick what matches the bundle) app under a new `web/` directory. Wire it to the existing MCP server via the same tool surface the chat client uses. Implement the priority screens first; stub the lower-priority ones.`
3. Iterate: the design and the implementation can both keep evolving in their own loops.
