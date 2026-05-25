"use client";

import * as React from "react";
import { Wand2, Plus, Move, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { ScheduleChange, ChangeKind } from "@/lib/types";

interface ScheduleDiffCardProps {
  title: string;
  effective: string;
  changes: ScheduleChange[];
  onApply?: () => void;
  onDiscard?: () => void;
}

/**
 * The full schedule-diff card — used when the assistant has staged a
 * multi-line set of schedule changes. The user reviews each change
 * (add / shift / delete badges, per-change details), then commits via
 * Apply or drops via Discard.
 *
 * Layout:
 *   ┌────────────────────────────────────────────────┐
 *   │ wand  Late-start Wednesdays  · 4 changes · …  │   <- header
 *   ├────────────────────────────────────────────────┤
 *   │ [add]  Period 1 bell …          08:00  Elem.   │
 *   │ [shift] Warning bell …          08:25  Elem.   │
 *   │ [delete] Old assembly bell …    13:00  Gym     │
 *   ├────────────────────────────────────────────────┤
 *   │ Type `apply` or click to confirm  [Discard] [Apply] │
 *   └────────────────────────────────────────────────┘
 */
export function ScheduleDiffCard({
  title,
  effective,
  changes,
  onApply,
  onDiscard,
}: ScheduleDiffCardProps) {
  return (
    <div className="border border-slate-200 rounded-3 bg-card shadow-1 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-100 bg-accent-softer">
        <span className="inline-flex items-center justify-center w-[30px] h-[30px] rounded-2 bg-audio-gradient text-white shadow-1 shrink-0">
          <Wand2 size={15} strokeWidth={1.9} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[14px] font-semibold text-ink">{title}</span>
            <span className="inline-flex items-center h-[18px] px-1.5 rounded-1 bg-accent-soft text-accent-700 text-[10.5px] font-semibold uppercase tracking-[0.06em] shrink-0">
              Staged
            </span>
          </div>
          <div className="text-12 text-slate-500 mt-0.5">
            <span className="font-medium text-slate-700">{changes.length}</span>{" "}
            changes · effective {effective}
          </div>
        </div>
      </div>

      {/* Changes */}
      <ul className="divide-y divide-slate-100">
        {changes.map((c, i) => (
          <ChangeRow key={i} change={c} />
        ))}
      </ul>

      {/* Footer */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-surface border-t border-slate-100">
        <span className="text-12 text-slate-500">
          Type <span className="mono text-slate-700 bg-slate-100 px-1 rounded-1">apply</span>{" "}
          or click to confirm.
        </span>
        <div className="flex-1" />
        <Button variant="ghost" size="sm" onClick={onDiscard}>
          Discard
        </Button>
        <Button variant="primary" size="sm" onClick={onApply}>
          Apply
        </Button>
      </div>
    </div>
  );
}

function ChangeRow({ change }: { change: ScheduleChange }) {
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <KindBadge kind={change.kind} />
      <div className="flex-1 min-w-0">
        <div className="text-13 text-ink truncate">{change.label}</div>
        <div className="text-[11.5px] text-slate-500 truncate">{change.detail}</div>
      </div>
      {change.time && (
        <span className="mono text-12 text-slate-700 shrink-0">{change.time}</span>
      )}
      {change.destination && (
        <span
          className="inline-flex items-center h-[20px] px-1.5 rounded-1 bg-slate-100 text-[10.5px] text-slate-700 font-medium shrink-0"
          title={change.destination}
        >
          {change.destination}
        </span>
      )}
    </li>
  );
}

function KindBadge({ kind }: { kind: ChangeKind }) {
  const cfg = {
    add: { bg: "bg-success-soft", fg: "text-success", icon: Plus, label: "add" },
    shift: { bg: "bg-accent-soft", fg: "text-accent-700", icon: Move, label: "shift" },
    delete: { bg: "bg-critical-soft", fg: "text-critical", icon: X, label: "delete" },
  }[kind];
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 h-[20px] px-1.5 rounded-1 shrink-0",
        cfg.bg,
        cfg.fg,
        "text-[10.5px] font-semibold uppercase tracking-[0.04em]",
      )}
    >
      <Icon size={10} strokeWidth={2.4} />
      {cfg.label}
    </span>
  );
}
