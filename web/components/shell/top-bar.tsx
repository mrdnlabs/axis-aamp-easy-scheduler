"use client";

import * as React from "react";
import {
  ChevronDown,
  History,
  Plus,
  ClipboardCheck,
  Settings as SettingsIcon,
  LogOut,
} from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Logo } from "@/components/brand";
import { StatusDot } from "@/components/ui/status-dot";
import { IconButton } from "@/components/ui/button";
import { TokenUsagePill } from "@/components/shell/token-usage-pill";
import { cn } from "@/lib/cn";
import type { TokenTotals } from "@/lib/use-chat";

interface TopBarProps {
  /** Friendly site name from the intent doc (e.g. "Lincoln Middle School"). */
  siteName: string;
  /** AAM Pro server reachability. */
  serverStatus: "reachable" | "degraded" | "offline";
  /** Initials shown in the user avatar (2-3 chars). */
  userInitials: string;
  /** Full name + role line in the user dropdown. */
  userName: string;
  userRole: string;
  /** Running session token totals; hidden when ``turns === 0``. */
  tokenTotals?: TokenTotals;
  onNewChat?: () => void;
  onOpenHistory?: () => void;
  onNavigate?: (route: "audit" | "settings") => void;
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
 *   - thin vertical divider
 *   - New chat button (plus icon)
 *   - History icon button
 *   - User menu (avatar + name + chevron, opens dropdown with Audit/Settings)
 */
export function TopBar({
  siteName,
  serverStatus,
  userInitials,
  userName,
  userRole,
  tokenTotals,
  onNewChat,
  onOpenHistory,
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

      <SiteStatusPill siteName={siteName} status={serverStatus} />

      {tokenTotals && <TokenUsagePill totals={tokenTotals} />}

      <div className="w-px h-[22px] bg-slate-200" />

      <IconButton aria-label="New chat" onClick={onNewChat}>
        <Plus size={17} strokeWidth={1.8} />
      </IconButton>

      <IconButton aria-label="History" onClick={onOpenHistory}>
        <History size={17} strokeWidth={1.8} />
      </IconButton>

      <UserMenu
        initials={userInitials}
        userName={userName}
        userRole={userRole}
        onNavigate={onNavigate}
      />
    </header>
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

function UserMenu({
  initials,
  userName,
  userRole,
  onNavigate,
}: {
  initials: string;
  userName: string;
  userRole: string;
  onNavigate?: (route: "audit" | "settings") => void;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className={cn(
            "inline-flex items-center gap-1.5 h-8 px-2.5 rounded-2 cursor-pointer",
            "bg-transparent text-slate-700 text-[13.5px] font-medium",
            "hover:bg-slate-100 transition-colors",
            "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
          )}
        >
          <span
            className={cn(
              "inline-flex items-center justify-center w-[22px] h-[22px] rounded-[7px]",
              "bg-audio-gradient text-white font-semibold text-[10px]",
            )}
          >
            {initials}
          </span>
          {userName.split(" ")[0]}
          <ChevronDown size={14} className="text-slate-400" strokeWidth={1.8} />
        </button>
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
          <div className="px-2.5 py-2 pb-1.5 border-b border-slate-100 mb-1">
            <div className="text-[12.5px] font-semibold text-ink">{userName}</div>
            <div className="text-11 text-slate-500">{userRole}</div>
          </div>

          <DropdownMenu.Item
            onSelect={() => onNavigate?.("audit")}
            className={cn(
              "flex items-center gap-2 h-9 px-2.5 rounded-2 text-13 text-slate-700 cursor-pointer",
              "outline-none focus:bg-slate-100 data-[highlighted]:bg-slate-100",
            )}
          >
            <ClipboardCheck size={15} strokeWidth={1.8} className="text-slate-500" />
            Audit & credentials
          </DropdownMenu.Item>

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

          <DropdownMenu.Separator className="h-px bg-slate-100 my-1 -mx-1.5" />

          <DropdownMenu.Item
            className={cn(
              "flex items-center gap-2 h-9 px-2.5 rounded-2 text-13 text-slate-700 cursor-pointer",
              "outline-none focus:bg-slate-100 data-[highlighted]:bg-slate-100",
            )}
          >
            <LogOut size={15} strokeWidth={1.8} className="text-slate-500" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
