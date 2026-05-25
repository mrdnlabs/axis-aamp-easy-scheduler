"use client";

import { Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { DayTemplateArtifact as DayTemplateArtifactData } from "@/lib/types";

interface DayTemplateArtifactProps {
  data: DayTemplateArtifactData;
  onApply?: () => void;
  onDiscard?: () => void;
}

/**
 * Vertical-timeline view of a day template (e.g. "Late-start Wednesday").
 *
 * Layout:
 *   - Optional staged-changes banner at the top (when pending_changes > 0)
 *   - Header card: "DAY TEMPLATE" label + title + recurrence chip
 *   - Vertical timeline with events as cards, each with:
 *     • Time stamp (mono 12.5px) on the left
 *     • Status dot (10×10, tone color border)
 *     • Event card: tone-based bg/border/fg
 *
 * Tones:
 *   - regular     — white card, slate-200 border, ink fg (standard bell)
 *   - announce    — teal-tinted (audio announcement, not a bell)
 *   - staged_new  — accent-softer bg, dashed accent outline, "new" chip
 *   - staged_shifted — accent-softer bg, dashed accent outline, "shifted" chip
 */
export function DayTemplateArtifact({
  data,
  onApply,
  onDiscard,
}: DayTemplateArtifactProps) {
  const hasStaged = (data.pending_changes ?? 0) > 0;

  return (
    <div className="flex flex-col gap-4">
      {hasStaged && (
        <div className="flex items-center gap-3 px-3.5 py-2.5 rounded-3 border border-accent-soft bg-accent-softer">
          <span className="inline-flex items-center justify-center w-[28px] h-[28px] rounded-2 bg-audio-gradient text-white shadow-1 shrink-0">
            <Wand2 size={14} strokeWidth={1.9} />
          </span>
          <div className="flex-1 text-12 text-ink">
            <span className="font-semibold">{data.pending_changes}</span> changes staged from this chat
          </div>
          <Button variant="ghost" size="sm" onClick={onDiscard}>
            Discard
          </Button>
          <Button variant="primary" size="sm" onClick={onApply}>
            Apply
          </Button>
        </div>
      )}

      {/* Header card */}
      <div className="bg-card border border-slate-200 rounded-3 shadow-1 px-4 py-3.5">
        <div className="text-10 font-semibold text-slate-500 uppercase tracking-[0.06em]">
          Day template
        </div>
        <div className="flex items-center gap-3 mt-1">
          <h2 className="text-18 font-semibold text-ink tracking-tight">{data.title}</h2>
          <span className="inline-flex items-center h-[20px] px-2 rounded-full bg-slate-100 text-[11px] font-medium text-slate-700">
            {data.recurrence}
          </span>
        </div>
      </div>

      {/* Timeline */}
      <div className="relative pl-[68px]">
        {/* vertical rail (positioned to align with status dots) */}
        <div className="absolute left-[60px] top-2 bottom-2 w-px bg-slate-200" />
        <ul className="flex flex-col gap-2">
          {data.events.map((evt, i) => (
            <li key={i} className="relative">
              {/* time stamp */}
              <span className="absolute -left-[68px] top-2.5 mono text-[12.5px] text-slate-700 font-medium tabular-nums">
                {evt.time}
              </span>
              {/* status dot */}
              <span
                className={cn(
                  "absolute -left-[16px] top-3 inline-block w-[10px] h-[10px] rounded-full border-2 bg-card",
                  evt.tone === "regular" && "border-slate-400",
                  evt.tone === "announce" && "border-teal",
                  (evt.tone === "staged_new" || evt.tone === "staged_shifted") &&
                    "border-accent shadow-[0_0_0_3px_theme(colors.accent.soft)]",
                )}
              />
              {/* event card */}
              <EventCard event={evt} />
            </li>
          ))}
        </ul>
      </div>

      {/* Footer */}
      <p className="text-12 text-slate-500 leading-relaxed mt-2">
        Recurrence rules and exception dates live in AAM Pro itself. ChAAMP
        applies templates to days — the calendar grid is in AAM Pro.
      </p>
    </div>
  );
}

function EventCard({ event }: { event: DayTemplateArtifactData["events"][0] }) {
  const isStaged = event.tone === "staged_new" || event.tone === "staged_shifted";
  return (
    <div
      className={cn(
        "rounded-2 px-3 py-2 transition-colors",
        event.tone === "regular" && "bg-card border border-slate-200",
        event.tone === "announce" && "bg-teal/[0.06] border border-teal/30",
        isStaged && "bg-accent-softer border-2 border-dashed border-accent",
      )}
    >
      <div className="flex items-baseline gap-2">
        <span className="text-[13.5px] font-medium text-ink">{event.label}</span>
        {event.tone === "staged_new" && <Chip label="new" />}
        {event.tone === "staged_shifted" && <Chip label="shifted" />}
      </div>
      {event.destination && (
        <div className="text-[11.5px] text-slate-500 mt-0.5">{event.destination}</div>
      )}
    </div>
  );
}

function Chip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center h-[16px] px-1.5 rounded-1 bg-accent-soft text-accent-700 text-[10px] font-semibold uppercase tracking-[0.06em]">
      {label}
    </span>
  );
}
