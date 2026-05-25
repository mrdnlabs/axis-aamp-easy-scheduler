# ChAAMP — web client

The Next.js web app for ChAAMP. Implements the design system documented in [`../docs/design/DESIGN_SYSTEM.md`](../docs/design/DESIGN_SYSTEM.md). Wraps the MCP server in [`../src/aamp/`](../src/aamp/) as a chat-first interface.

## Prerequisites

- Node.js 20+ (LTS)
- npm 10+ (ships with Node)
- The AampEasyScheduler Python backend running locally (`aamp-mcp` from the project root)

## Setup

```powershell
# In one terminal — the Python sidecar (credential capture + chat SSE)
aamp-server                   # binds 127.0.0.1:7331

# In another terminal — the Next.js dev server
cd web
npm install                   # first time only
npm run dev                   # binds localhost:7330
```

Open [http://localhost:7330](http://localhost:7330).

The `/api/*` routes in the web client proxy to `http://127.0.0.1:7331/api/*` via the rewrite in `next.config.js`. The sidecar must be running before triggering the secure-capture flow or the chat stream.

## Layout

```
web/
├── app/                    # Next.js App Router routes
│   ├── layout.tsx          # root layout, font imports
│   ├── page.tsx            # / — chat workspace (the home view)
│   └── globals.css         # Tailwind imports + base styles + time-axis motif
├── components/
│   ├── brand.tsx           # BrandMark + Logo (gradient chat-bubble glyph)
│   ├── shell/
│   │   └── top-bar.tsx     # TopBar — site status, history, user menu
│   ├── chat/
│   │   ├── composer.tsx    # The sticky-bottom message composer
│   │   └── message-row.tsx # One conversation row (user or assistant)
│   └── ui/                 # primitives — button, status-dot, ...
├── lib/
│   └── cn.ts               # className combiner (clsx + tailwind-merge)
├── tailwind.config.ts      # ChAAMP design tokens → Tailwind theme
├── next.config.js
├── tsconfig.json
└── package.json
```

## Stack

- **Next.js 15** App Router, React 19
- **Tailwind CSS** for everything — theme tokens in `tailwind.config.ts`
- **Radix UI primitives** (Dialog, DropdownMenu, Popover, Tabs, Tooltip) for accessibility
- **lucide-react** for icon stand-ins (we'll replace the few "chat+wave DNA" icons with custom SVG over time — see the brand notes in the design docs)
- **TypeScript strict**, **ESLint** with the Next config

## Implementation roadmap

Per the Claude Design handoff's recommended order:

1. ✅ Shell — TopBar + chat column + Composer with static demo content.
2. ⬜ Wire one MCP tool call end-to-end so `ToolCallCard` renders from real data.
3. ⬜ Build the secure-credential capture loop:
   - `SecureCaptureCard` (inline in chat)
   - `SecureCaptureModal` (visually isolated full-page dialog)
   - Local capture endpoint sidecar at `localhost:7331`
4. ⬜ Build `PipelineCard` and the streaming onboarding tool.
5. ⬜ Add the artifact pane with `DayTemplateArtifact`.
6. ⬜ Add `ScheduleDiffCard` + `ApplyConfirmCard` + the stage/apply/discard tool loop.
7. ⬜ Add other artifact types + Credentials/Audit/Settings sub-views.

## Backend tools needed (Python side)

The web client assumes these MCP tools exist on the backend; some are not yet implemented:

| Tool | Status |
|---|---|
| `discover_axis_devices`, `inspect_axis_device`, `onboard_axis_device` | ✅ Implemented |
| `prepare_credential_capture` | ✅ Implemented (returns CLI command) |
| `request_credential_capture` | ✅ Implemented — mints a token + URL for the modal |
| `list_credentials` | ✅ Implemented — returns masked metadata |
| `audit_log` | ✅ Implemented — reads `~/.aamp_audit.log` |
| `stage_schedule_change`, `apply_staged_changes`, `discard_staged_changes` | ⬜ TODO — diff-based mutations |

See the design system docs for the visual contract these tools' results should match.
