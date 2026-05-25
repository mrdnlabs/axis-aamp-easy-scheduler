"use client";

import { Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ApplyConfirmCardProps {
  /** Number of staged changes. */
  count: number;
  /** Single-line summary — "Late-start Wednesdays through June 11". */
  summary: string;
  onApply?: () => void;
  onDiscard?: () => void;
}

/**
 * Simpler than ScheduleDiffCard — a single-line callout when changes are
 * ready to apply and the user can choose to do it now.
 *
 * Accent-softer bg, 30×30 gradient chip with wand icon, count + summary,
 * Discard + Apply buttons.
 */
export function ApplyConfirmCard({
  count,
  summary,
  onApply,
  onDiscard,
}: ApplyConfirmCardProps) {
  return (
    <div className="flex items-center gap-3 px-3.5 py-2.5 rounded-3 border border-accent-soft bg-accent-softer">
      <span className="inline-flex items-center justify-center w-[30px] h-[30px] rounded-2 bg-audio-gradient text-white shadow-1 shrink-0">
        <Wand2 size={15} strokeWidth={1.9} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-13 text-ink truncate">
          <span className="font-semibold">{count}</span> changes ready ·{" "}
          <span className="text-slate-600">{summary}</span>
        </div>
      </div>
      <Button variant="ghost" size="sm" onClick={onDiscard}>
        Discard
      </Button>
      <Button variant="primary" size="sm" onClick={onApply}>
        Apply
      </Button>
    </div>
  );
}
