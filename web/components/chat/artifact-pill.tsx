"use client";

import { Calendar, Radar, Layers, ArrowRight } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ArtifactKind } from "@/lib/types";

interface ArtifactPillProps {
  artifact: ArtifactKind;
  title: string;
  subtitle?: string;
  active?: boolean;
  onClick?: () => void;
}

/**
 * Inline button suggesting the user open a richer view in the right-side
 * artifact pane. Looks like a row card the user can click.
 *
 * When the artifact pointed to by this pill is currently open in the
 * pane, the pill switches to ``accent-softer`` background as a visual
 * affordance ("you're already looking at this one").
 */
export function ArtifactPill({
  artifact,
  title,
  subtitle,
  active = false,
  onClick,
}: ArtifactPillProps) {
  const Icon = ICONS[artifact];
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2.5 rounded-3 border transition-colors text-left",
        active
          ? "bg-accent-softer border-accent-soft"
          : "bg-card border-slate-200 hover:bg-slate-50",
      )}
    >
      <span
        className={cn(
          "inline-flex items-center justify-center w-[30px] h-[30px] rounded-2 shrink-0",
          active ? "bg-accent text-white" : "bg-slate-100 text-slate-700",
        )}
      >
        <Icon size={15} strokeWidth={1.8} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-[13.5px] font-semibold text-ink truncate">{title}</div>
        {subtitle && (
          <div className="text-[11.5px] text-slate-500 truncate mt-0.5">{subtitle}</div>
        )}
      </div>
      <span
        className={cn(
          "inline-flex items-center gap-1 text-12 font-medium shrink-0",
          active ? "text-accent-700" : "text-slate-500",
        )}
      >
        {active ? "Open" : "Open in side pane"}
        <ArrowRight size={12} strokeWidth={2} />
      </span>
    </button>
  );
}

// lucide stand-ins for the brand-DNA icons (Calendar for day_template,
// Radar for discovery, Layers for onboarding). Will be replaced with the
// custom chat+wave glyphs once those exist.
const ICONS: Record<ArtifactKind, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  day_template: Calendar,
  onboarding: Layers,
  discovery: Radar,
};
