"use client";

import * as React from "react";
import * as Popover from "@radix-ui/react-popover";
import { cn } from "@/lib/cn";
import type { TokenTotals } from "@/lib/use-chat";

/**
 * Compact running-token-usage pill for the topbar.
 *
 * Default state: shows the session totals as a single mono number.
 * Hover/click to open a popover with the per-category breakdown.
 *
 * Hidden when the session has no completed turns yet — until then there's
 * nothing useful to display, and the empty pill is just noise.
 */
export function TokenUsagePill({ totals }: { totals: TokenTotals }) {
  if (totals.turns === 0) return null;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          className={cn(
            "inline-flex items-center gap-1.5 px-2.5 h-[26px] rounded-full",
            "bg-slate-100 hover:bg-slate-200 transition-colors",
            "text-11 font-medium text-slate-700 mono tabular-nums",
            "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
          )}
          aria-label="Token usage"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-accent" />
          {compact(totals.total_tokens)} tok
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          className={cn(
            "min-w-[260px] bg-card border border-slate-200 rounded-3 shadow-3 p-3 z-50",
            "animate-fade-up",
          )}
        >
          <div className="text-10 font-semibold text-slate-500 uppercase tracking-[0.06em] mb-2">
            Session usage · {totals.turns} turn{totals.turns === 1 ? "" : "s"}
          </div>
          <div className="flex flex-col gap-1.5 text-13">
            <Row label="Input" value={totals.prompt_tokens} primary />
            <Row label="Output" value={totals.candidates_tokens} primary />
            {totals.cached_tokens > 0 && (
              <Row label="Cached" value={totals.cached_tokens} muted />
            )}
            {totals.thoughts_tokens > 0 && (
              <Row label="Thinking" value={totals.thoughts_tokens} muted />
            )}
            {totals.tool_use_prompt_tokens > 0 && (
              <Row label="Tool overhead" value={totals.tool_use_prompt_tokens} muted />
            )}
            <div className="border-t border-slate-100 mt-1 pt-1.5" />
            <Row label="Total" value={totals.total_tokens} bold />
          </div>
          <Popover.Arrow className="fill-card" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Row({
  label,
  value,
  primary,
  muted,
  bold,
}: {
  label: string;
  value: number;
  primary?: boolean;
  muted?: boolean;
  bold?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <span
        className={cn(
          "text-12",
          muted ? "text-slate-500" : "text-slate-700",
          bold && "font-semibold text-ink",
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "mono tabular-nums",
          primary ? "text-13 text-ink font-medium" : "text-13",
          muted && "text-slate-500",
          bold && "text-14 font-semibold text-ink",
        )}
      >
        {value.toLocaleString()}
      </span>
    </div>
  );
}

/** Format a token count compactly: 1234 → "1.2K", 12345 → "12K". */
function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1)}K`;
  if (n < 1_000_000) return `${Math.round(n / 1000)}K`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
