# ChAAMP — design system

The canonical reference for ChAAMP's visual language. The implementation lives in [`web/tailwind.config.ts`](../../web/tailwind.config.ts) and [`web/app/globals.css`](../../web/app/globals.css); this doc explains *why* those values are what they are. If you need to change a token, update both this doc and the Tailwind config in the same commit.

The companion docs in this directory are:
- [`BRIEF.md`](BRIEF.md) — the product / visual brief Claude Design was given
- [`SCREENS.md`](SCREENS.md) — per-screen functional specifications
- [`PROMPT.md`](PROMPT.md) — the verbatim Claude Design kickoff prompt

## Product name

**ChAAMP** — pronounced *champ*. Reads as "Chat with AAMP". The "Ch" is rendered in slate-500, "AAMP" in ink, so the brain reads "AAMP" first and "Ch" snaps into place after. It's the chat *with* AXIS Audio Manager Pro, not a replacement for it.

## Design principles

1. **Chat-first.** The conversation is the primary surface. ChAAMP doesn't duplicate AAM Pro's own views — the full schedule grid, fleet table, library, and destination management all already exist in AAM Pro. ChAAMP's job is the conversation and the inline visualization of *the thing we're currently talking about*.
2. **Inline widgets for common actions.** Tool-call summaries, multi-step pipeline traces, schedule diffs, apply/discard confirmations, and secure credential capture all render *inside* chat messages rather than as separate pages or modals.
3. **Contextual artifact pane.** When a chat references something that benefits from a richer view (a day template, an onboarding run), it surfaces an `ArtifactPill` the user can click to open a right-side panel. The pane closes back to chat-full-width when no longer needed.
4. **Passwords never enter the LLM context.** The `SecureCaptureCard` + `SecureCaptureModal` flow goes through a local capture endpoint that writes directly to the OS credential vault. The assistant only ever sees a `captured` / `cancelled` confirmation.
5. **Confirmations before applies.** Any mutation of AAM Pro state is staged and shown as a diff before being written. The user types `apply` or clicks Apply; until then nothing has changed.

## Brand

### Logo / wordmark

`web/components/brand.tsx`:
- **`BrandMark`** — 28×28 rounded-square (`r ≈ 8px`, computed from `size × 0.28`) filled with the audio gradient. Contains a white speech-bubble outline with a 3-bump sine wave inside it. Conveys "chat + audio."
- **`Logo`** — the full lockup: `BrandMark` + "**Ch**AAMP" wordmark. "Ch" in slate-500, "AAMP" in ink. Both Inter 700, 16px, `-0.015em` letter-spacing.

The same glyph at 16px inside a 28×28 rounded square is used as the **assistant avatar** in every chat message. Never use the wordmark as the assistant avatar.

### Iconography

Geometric 20×20 line icons drawn with 1.6 stroke, round caps/joins. We use `lucide-react` as the source for most icons; a small number of icons that carry the **chat+wave DNA** are custom SVG (planned — see open work in `web/components/brand.tsx`):

- `IconChat` — speech bubble with a small wave inside (same shape as the `BrandMark`)
- `IconFleet` — stacked device chips with waves running through them
- `IconRadar` — concentric ripples (audio waves expanding)

**Never use** literal speaker, bell, megaphone, or musical-note icons. The audio identity comes through the gradient and the wave motifs, not skeuomorphic imagery.

## Color

Tokens are defined in `web/tailwind.config.ts` under `theme.extend.colors`.

| Token | Hex | Usage |
|---|---|---|
| `ink` | `#0F172A` | Primary text |
| `slate-{50…900}` | … | Standard grayscale ramp |
| `surface` | `#FAFAF7` | App background — **warm off-white, not pure white** |
| `surface-2` | `#F4F3EE` | Section dividers, info chips |
| `card` | `#FFFFFF` | Card surfaces |
| `accent` | `#4F46E5` | Primary brand — indigo |
| `accent-700` | `#4338CA` | Hover for accent buttons |
| `accent-soft` | `#EEF2FF` | Accent badge bg, selected-nav bg |
| `accent-softer` | `#F5F6FF` | Tinted card backgrounds for staged content |
| `teal` | `#06B6D4` | **Reserved for the audio gradient only** |
| `success` / `success-soft` | `#059669` / `#ECFDF5` | Online, captured, applied |
| `warning` / `warning-soft` | `#D97706` / `#FFFBEB` | Drift, factory-default callout |
| `critical` / `critical-soft` | `#DC2626` / `#FEF2F2` | Offline, failed, factory-reset-required |

### Gradients

| Token | Definition |
|---|---|
| `bg-audio-gradient` | `linear-gradient(90deg, #4F46E5 0%, #06B6D4 100%)` — brand gradient. Used for the logo, assistant avatar, accent rails, modal stripes. |
| `bg-audio-gradient-soft` | `linear-gradient(90deg, rgba(79,70,229,.10) 0%, rgba(6,182,212,.10) 100%)` — tinted backgrounds. |

**Do not introduce new colors.** All accents derive from indigo, with the teal pairing reserved for the gradient.

## Typography

Two faces:
- **`font-ui`** — Inter (Google Fonts). Weights 400, 500, 600, 700.
- **`font-mono`** — JetBrains Mono. Weights 400, 500, 600. Used for time-of-day, IP/MAC/firmware values, tool-call names, file paths, inline code, credential keys.

Globally enabled Inter features: `'cv11', 'ss01', 'ss03'` — slightly more geometric digits, applied on `body` in `globals.css`.

Numeric data (time displays, IP addresses, counts) carry `font-feature-settings: 'tnum' 1` via the `.tnum` / `.mono` utility classes so columns align.

### Scale

Tailwind defaults supplement the project-specific sizes below. All values are `px`.

| Size | Weight | Usage |
|---|---|---|
| 10–10.5 | 600 | Small uppercase labels (`tracking-label-caps`) |
| 11–11.5 | 500–600 | Captions, chip labels, kbd |
| 12–12.5 | 400–500 | Helper text, metadata |
| 13–13.5 | 400–500 | Body small (table cells, chat metadata) |
| **14** | 400–500 | **Body default** — message text |
| 15–16 | 500–600 | Card titles, composer input |
| 17–18 | 600 | Modal titles, screen titles |
| 20–22 | 600 | Stat values, destination headers |
| 28 | 600 | Hero numbers (stat cards) — uses `-0.01em` letter-spacing |

Letter-spacing tighter (`-0.01em` to `-0.02em`) on titles 15px+.

## Radii

| Token | Value | Usage |
|---|---|---|
| `rounded-1` | 6px | Small chips, kbd, tight controls |
| `rounded-2` | 10px | Inputs, buttons, small tiles |
| `rounded-3` | 14px | Cards, panels |
| `rounded-4` | 20px | Modals, hero containers |

## Shadows

| Token | Value | Usage |
|---|---|---|
| `shadow-1` | `0 1px 2px rgba(15,23,42,.04)` | Subtle rest state |
| `shadow-2` | `0 1px 2px rgba(15,23,42,.04), 0 8px 24px -8px rgba(15,23,42,.08)` | Standard card shadow |
| `shadow-3` | `0 1px 2px rgba(15,23,42,.04), 0 12px 40px -12px rgba(15,23,42,.16)` | Hovered card / popovers |
| `shadow-modal` | `0 24px 64px -12px rgba(15,23,42,.24), 0 4px 12px rgba(15,23,42,.08)` | Modal dialog |

Prefer **layered soft shadows over hard borders**. Cards use both: a 1px slate-200 border AND a soft shadow.

## Motion

| Animation | Use |
|---|---|
| `animate-fade-up` | New message rows, modal mounts, dropdown reveals (.2–.25s) |
| `animate-fade-in` | Overlay backdrops (.15s) |
| `animate-pulse-dot` | "Live" pulsing rings on status dots (e.g. "OUT-OF-CONTEXT" badge in secure capture) |
| `animate-spin` | Running-state spinners |

Keep motion **minimal and purposeful**. No bouncy or attention-grabbing animations.

## Time-axis motif

A subtle hairline-with-ticks background pattern that hints at "time / frequency / a passage of moments" without being a literal waveform. Available as the `.time-axis` utility class in `globals.css`. Use sparingly — section dividers, accent rails. Not as decoration.

## Layout architecture

```
┌───────────────────────────────────────────────────────────┐
│ TOPBAR (56px) — Logo | site-status pill | history | menu  │
├──────────────────────────────────┬────────────────────────┤
│                                  │                        │
│         CHAT COLUMN              │   ARTIFACT PANE        │
│         (full width when no      │   (~46%, max 640px,    │
│          artifact open;          │   min 420px)           │
│          820px max-width         │                        │
│          centered content)       │   opens contextually   │
│                                  │   when chat references │
│                                  │   a day template,      │
│                                  │   onboarding run, etc. │
│                                  │                        │
├──────────────────────────────────┘                        │
│ COMPOSER (sticky bottom, 820px max-width)                 │
└───────────────────────────────────────────────────────────┘
```

**There is no persistent left navigation.** Audit + Settings are tucked into the user menu (top-right). History is a single icon-button.

## Components

The implementation lives in `web/components/`. This list captures the design contract; recreate the actual component in code, don't copy this doc.

### Primitives (`components/ui/`)

| Component | Notes |
|---|---|
| **Button** | Variants: `primary` / `secondary` / `ghost` / `danger` / `quiet`. Sizes: `sm` 28h, `md` 34h, `lg` 40h. Optional `iconLeft` / `iconRight`. `fullWidth` prop. |
| **IconButton** | Square icon-only button, 32px default. `active` state uses `accent-soft` bg + `accent-700` fg. |
| **StatusDot** | Tones: `success` / `warning` / `critical` / `accent` / `neutral`. Optional pulsing ring. |
| **Input** | (planned) 36h, white bg, slate-200 border, optional left icon. |
| **Chip** | (planned) Tones: neutral / accent / success / warning / critical / outline / ghost. Sizes sm/md/lg. Optional icon. `active` flips bg to accent + fg to white. |
| **Card** | (planned) White, slate-200 border, `rounded-3`, `shadow-2`, optional `padded`. |
| **TabPill** | (planned) Segmented control in slate-100 inset bg. Active pill is white with shadow. |
| **Modal** | (planned) Overlay + centered dialog. Escape closes. fadeUp animation. |
| **Drawer** | (planned) Right-side panel. |
| **Banner** | (planned) Tones: accent / warning / success / critical / info. Title + body + optional actions. |
| **CodeBlock** | (planned) Dark `#0F172A` bg, mono 12.5px, copy button right. |
| **Kbd** | (planned) Light keyboard key visual (white bg, 2px bottom border). |
| **SectionHeader** | (planned) Title + subtitle + action slot. |
| **StatCard** | (planned) Stat tile — label, large 28px tnum value, optional hint and gradient accent rail. |

### Brand (`components/brand.tsx`)

| Component | Notes |
|---|---|
| **BrandMark** | The audio-gradient chat-bubble glyph. Sized by `size` prop. Used as the assistant avatar. |
| **Logo** | BrandMark + ChAAMP wordmark. Used in the TopBar. |

### Shell (`components/shell/`)

| Component | Notes |
|---|---|
| **TopBar** | Logo · site-status pill · `New chat` · `History` · user menu. 56px tall. Replaces a persistent left nav entirely. |
| **SessionList** | (planned) Left-side overlay (320px wide), grouped by recency. Opens from the History icon-button. |

### Chat (`components/chat/`)

| Component | Notes |
|---|---|
| **MessageRow** | One conversation row. 36px avatar gutter + 1fr content, `gap-3.5`, `py-3`. User avatar = slate-200 square + initials; assistant avatar = `BrandMark`. |
| **Composer** | The sticky-bottom message composer. Context-chips header, textarea, footer with attach / quick-command / send. `Cmd/Ctrl+Enter` to send. |
| **ToolCallCard** | (planned) Collapsed-by-default summary of a single tool call. `[status-icon] tool_name — summary`. |
| **PipelineCard** | (planned) Multi-step trace as one expandable card. Vertical timeline rail with dots, step labels, durations. |
| **ScheduleDiffCard** | (planned) Diff of pending schedule changes. Per-change rows with `[add]` / `[shift]` / `[delete]` mini-badges. Apply / Discard buttons. |
| **ApplyConfirmCard** | (planned) Single-line callout when changes are ready to apply. |
| **SecureCaptureCard** | (planned) Inline-chat warm-tinted card requesting a credential. "Set securely" opens the modal. |
| **ArtifactPill** | (planned) Inline button suggesting the user open a richer view in the artifact pane. |

### Artifacts (`components/artifacts/`, planned)

| Component | Notes |
|---|---|
| **ArtifactPane** | Right-side panel container. 46% width, 420–640px range. Header with kind icon + title + close. |
| **DayTemplateArtifact** | Vertical timeline of a day template (e.g. "Late-start Wednesday"). Staged-changes banner. |
| **OnboardingArtifact** | Live device-onboarding view. Device facts card + pipeline card. |
| **SecureCaptureModal** | Full-page modal for credential capture. Visually framed as isolated from ChAAMP — warm cream bg, gradient stripe, no reveal toggle, password strength meter, always-present CLI fallback. POSTs to `/api/credential-capture/*`. |

## Accessibility

- All `IconButton`s have a required `aria-label`.
- Inputs have proper `autoComplete` (`new-password` on `SecureInput`).
- Modals trap Escape to close.
- Visible focus ring: `outline: 2px solid var(--accent); outline-offset: 2px;` — set globally in `globals.css`.
- Selection color is `accent-soft` bg + `accent-700` fg — never the harsh default blue.

## Hard constraints (architecture-enforced; never relax)

These reflect security or product decisions already shipped — they are **not visual choices**:

- **Passwords NEVER appear in the UI.** No `*****` reveal, no "show password" toggle, no copy-the-value control. The `SecureCaptureModal` is the only surface that takes password input, and it does not display what was typed.
- **The chat is real chat, not a wizard.** No scripted-button flows pretending to be a chat. The user types; the agent responds.
- **Tool calls are auditable.** Every assistant message that called tools has a collapsible details view showing the tool name and (post-scrub) args + result.
- **Schedule changes are staged and confirmed before apply.** No direct-mutation paths in the UI.

## File-by-file source of truth

| Concern | File |
|---|---|
| Color, radius, shadow, font tokens | `web/tailwind.config.ts` |
| Time-axis motif, base styles, scrollbar, focus ring | `web/app/globals.css` |
| Brand glyph + wordmark | `web/components/brand.tsx` |
| Buttons + icon buttons | `web/components/ui/button.tsx` |
| Status dot | `web/components/ui/status-dot.tsx` |
| Top bar | `web/components/shell/top-bar.tsx` |
| Composer | `web/components/chat/composer.tsx` |
| Message row | `web/components/chat/message-row.tsx` |
