"use client";

import * as React from "react";
import {
  History,
  Plus,
  ClipboardCheck,
  Settings as SettingsIcon,
} from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Logo } from "@/components/brand";
import { StatusDot } from "@/components/ui/status-dot";
import { IconButton } from "@/components/ui/button";
import { TokenUsagePill } from "@/components/shell/token-usage-pill";
import { cn } from "@/lib/cn";
import type { TokenTotals } from "@/lib/use-chat";

interface TopBarProps {
  /** Friendly site name from the intent doc (e.g. "Lincoln Middle School").
   *  Pass ``null`` when the org-intake hasn't completed yet — the UI
   *  falls back to a generic "ChAAMP" label. */
  siteName: string | null;
  /** AAM Pro server reachability. */
  serverStatus: "reachable" | "degraded" | "offline";
  /** Running session token totals; hidden when ``turns === 0``. */
  tokenTotals?: TokenTotals;
  /**
   * The signed-in Windows user — ``DOMAIN\\username``. Pass ``null``
   * if not yet known. We show this so the operator can see at a
   * glance which Windows account is acting.
   */
  username?: string | null;
  /** Clear the message log + reset the session token totals. */
  onNewChat?: () => void;
  /**
   * Open one of the side panels. ``credentials`` is mapped to the
   * "Audit & credentials" menu item visually but is a separate panel
   * under the hood — see the page-level openPanel state.
   */
  onNavigate?: (route: "audit" | "credentials" | "settings") => void;
}

/**
 * ChAAMP top bar. Replaces the persistent left navigation entirely —
 * see docs/design/BRIEF.md and the handoff README for the rationale
 * ("ChAAMP is chat-first; AAM Pro is the equipment room").
 *
 * Contents, left → right:
 *   - Logo (brand glyph + ChAAMP wordmark)
 *   - flex spacer
 *   - Site / AAM-Pro status pill
 *   - Token usage pill (when there are tokens to show)
 *   - thin vertical divider
 *   - New chat button (plus icon — clears the session)
 *   - App menu (settings gear, opens Credentials / Audit log / Settings)
 *   - User chip (Windows identity, only when known)
 */
export function TopBar({
  siteName,
  serverStatus,
  tokenTotals,
  username,
  onNewChat,
  onNavigate,
}: TopBarProps) {
  return (
    <header
      className={cn(
        "flex items-center gap-3.5 px-[22px] h-14 shrink-0",
        "bg-surface border-b border-slate-200",
      )}
    >
      <Logo />

      <div className="flex-1" />

      <SiteStatusPill siteName={siteName ?? "ChAAMP"} status={serverStatus} />

      {tokenTotals && <TokenUsagePill totals={tokenTotals} />}

      <div className="w-px h-[22px] bg-slate-200" />

      <IconButton aria-label="New chat" onClick={onNewChat} title="Start a new chat (clear the current session)">
        <Plus size={17} strokeWidth={1.8} />
      </IconButton>

      <AppMenu onNavigate={onNavigate} />

      {username && <UserChip username={username} />}
    </header>
  );
}

/**
 * Minimal "you are signed in as X" indicator. We deliberately don't
 * show role/title — ChAAMP serves the organization. Just enough to
 * confirm which Windows account is acting.
 */
function UserChip({ username }: { username: string }) {
  // Drop the DOMAIN\ prefix in the visible label — the tooltip keeps
  // the full form for forensics.
  const display = username.includes("\\")
    ? username.split("\\").pop() ?? username
    : username;
  // Two initials from the visible-name segment.
  const initials = display
    .split(/[._\-\s]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0].toUpperCase())
    .join("") || display.slice(0, 2).toUpperCase();
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 h-8 pl-1 pr-2.5 rounded-2",
        "bg-card border border-slate-200 cursor-default",
      )}
      title={`Signed in via Windows: ${username}. Restart your browser as a different user to switch identity.`}
    >
      <span
        className={cn(
          "inline-flex items-center justify-center w-[22px] h-[22px] rounded-[7px]",
          "bg-audio-gradient text-white font-semibold text-[10px]",
        )}
      >
        {initials}
      </span>
      <span className="text-12 font-medium text-slate-700">{display}</span>
    </div>
  );
}

function SiteStatusPill({
  siteName,
  status,
}: {
  siteName: string;
  status: "reachable" | "degraded" | "offline";
}) {
  const tone =
    status === "reachable" ? "success" : status === "degraded" ? "warning" : "critical";
  const label =
    status === "reachable"
      ? "AAM Pro reachable"
      : status === "degraded"
        ? "AAM Pro degraded"
        : "AAM Pro offline";
  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 h-[30px] rounded-full",
        "bg-card border border-slate-200",
        "text-[12.5px] text-slate-700",
      )}
    >
      <StatusDot tone={tone} size={7} />
      <span className="font-medium">{siteName}</span>
      <span className="text-slate-400">·</span>
      <span className="text-slate-500">{label}</span>
    </div>
  );
}

/**
 * App-level dropdown menu. ChAAMP serves the *organization*, not a
 * specific user — so this menu intentionally has no avatar / name /
 * role line. It's a tools-and-data hatch, not a profile menu.
 *
 * Items split into two groups by purpose:
 *   - inspect:  Audit log, Credentials manager
 *   - configure: Settings
 */
function AppMenu({
  onNavigate,
}: {
  onNavigate?: (route: "audit" | "credentials" | "settings") => void;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton aria-label="Menu">
          <SettingsIcon size={17} strokeWidth={1.8} />
        </IconButton>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className={cn(
            "min-w-[220px] bg-card border border-slate-200 rounded-3 shadow-3 p-1.5",
            "animate-fade-up",
            "z-50",
          )}
        >
          <DropdownMenu.Item
            onSelect={() => onNavigate?.("credentials")}
            className={cn(
              "flex items-center gap-2 h-9 px-2.5 rounded-2 text-13 text-slate-700 cursor-pointer",
              "outline-none focus:bg-slate-100 data-[highlighted]:bg-slate-100",
            )}
          >
            <ClipboardCheck size={15} strokeWidth={1.8} className="text-slate-500" />
            Credentials
          </DropdownMenu.Item>

          <DropdownMenu.Item
            onSelect={() => onNavigate?.("audit")}
            className={cn(
              "flex items-center gap-2 h-9 px-2.5 rounded-2 text-13 text-slate-700 cursor-pointer",
              "outline-none focus:bg-slate-100 data-[highlighted]:bg-slate-100",
            )}
          >
            <History size={15} strokeWidth={1.8} className="text-slate-500" />
            Audit log
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="h-px bg-slate-100 my-1 -mx-1.5" />

          <DropdownMenu.Item
            onSelect={() => onNavigate?.("settings")}
            className={cn(
              "flex items-center gap-2 h-9 px-2.5 rounded-2 text-13 text-slate-700 cursor-pointer",
              "outline-none focus:bg-slate-100 data-[highlighted]:bg-slate-100",
            )}
          >
            <SettingsIcon size={15} strokeWidth={1.8} className="text-slate-500" />
            Settings
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
