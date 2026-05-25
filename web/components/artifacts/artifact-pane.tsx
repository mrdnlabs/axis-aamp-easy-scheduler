"use client";

import { X, Calendar, Radar, Layers } from "lucide-react";
import { IconButton } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { ArtifactKind } from "@/lib/types";

interface ArtifactPaneProps {
  /** What kind of artifact is being shown — drives the header icon/label. */
  kind: ArtifactKind;
  /** Title shown in the header. */
  title: string;
  /** Custom actions for the header (right-aligned slot before the close button). */
  actions?: React.ReactNode;
  /** Body content — typically an Artifact component (DayTemplate, Onboarding, etc.). */
  children: React.ReactNode;
  onClose?: () => void;
}

/**
 * Right-side panel container. Opens on demand when a chat ArtifactPill is
 * clicked or when the assistant emits an artifact reference.
 *
 *   - width: 46% of the app shell, clamped to 420px ≤ w ≤ 640px
 *   - border-left: 1px slate-200
 *   - background: surface (not pure white — sits subtly distinct from
 *     the chat column which uses card-on-surface)
 *
 * Header: kind icon + "ARTIFACT · {kind}" label + title + actions + close.
 * Body: scrollable, the artifact-specific component goes here.
 */
export function ArtifactPane({
  kind,
  title,
  actions,
  children,
  onClose,
}: ArtifactPaneProps) {
  const Icon = ICONS[kind];
  const label = LABELS[kind];

  return (
    <aside
      className={cn(
        "flex flex-col h-full",
        "border-l border-slate-200 bg-surface",
        "min-w-[420px] max-w-[640px] w-[46%]",
        "animate-fade-up",
      )}
    >
      {/* Header */}
      <header className="flex items-center gap-3 px-4 h-14 bg-card border-b border-slate-200 shrink-0">
        <span
          className={cn(
            "inline-flex items-center justify-center w-[26px] h-[26px] rounded-2 shrink-0",
            "bg-accent-soft text-accent-700",
          )}
        >
          <Icon size={14} strokeWidth={1.9} />
        </span>
        <div className="flex flex-col min-w-0">
          <span className="text-[10.5px] font-semibold text-slate-500 uppercase tracking-[0.06em] leading-tight">
            Artifact · {label}
          </span>
          <span className="text-[14.5px] font-semibold text-ink truncate leading-tight">
            {title}
          </span>
        </div>
        <div className="flex-1" />
        {actions}
        {onClose && (
          <IconButton aria-label="Close artifact" onClick={onClose}>
            <X size={16} strokeWidth={1.8} />
          </IconButton>
        )}
      </header>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-[18px] pt-4 pb-6">{children}</div>
    </aside>
  );
}

const ICONS: Record<ArtifactKind, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  day_template: Calendar,
  onboarding: Layers,
  discovery: Radar,
};

const LABELS: Record<ArtifactKind, string> = {
  day_template: "Day template",
  onboarding: "Onboarding",
  discovery: "Discovery",
};
