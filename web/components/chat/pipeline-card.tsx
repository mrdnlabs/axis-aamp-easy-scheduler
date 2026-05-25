"use client";

import * as React from "react";
import { Check, AlertCircle, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import type { PipelineStep, ToolStatus } from "@/lib/types";

interface PipelineCardProps {
  title: string;
  steps: PipelineStep[];
  defaultOpen?: boolean;
}

/**
 * Multi-step trace as a single expandable card.
 *
 * Renders one card per multi-step pipeline (e.g. the 4-step
 * onboard_axis_device run) — NOT N separate ToolCallCards. The header
 * summarizes the rolled-up state ("Step 3 of 4" while running,
 * "4 of 4 steps complete" on success). The body is a vertical timeline
 * with 14×14 status dots on a left rail.
 */
export function PipelineCard({ title, steps, defaultOpen = true }: PipelineCardProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  const done = steps.filter((s) => s.status === "success").length;
  const failed = steps.some((s) => s.status === "failed");
  const runningIdx = steps.findIndex((s) => s.status === "running");
  const isRunning = runningIdx >= 0;

  let headerStatus: ToolStatus;
  let headerText: string;
  if (failed) {
    headerStatus = "failed";
    headerText = `Failed at step ${steps.findIndex((s) => s.status === "failed") + 1} of ${steps.length}`;
  } else if (isRunning) {
    headerStatus = "running";
    headerText = `Step ${runningIdx + 1} of ${steps.length}`;
  } else {
    headerStatus = "success";
    headerText = `${done} of ${steps.length} steps complete`;
  }

  return (
    <div className="border border-slate-200 rounded-2 bg-card shadow-1 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left cursor-pointer hover:bg-slate-50 transition-colors"
        aria-expanded={open}
      >
        <HeaderChip status={headerStatus} />
        <span className="text-[13.5px] font-medium text-ink">{title}</span>
        <span className="text-12 text-slate-500 ml-1">{headerText}</span>
        <span className="flex-1" />
        <ChevronDown
          size={14}
          strokeWidth={1.8}
          className={cn(
            "text-slate-400 shrink-0 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="px-3 pb-3 pl-3">
          <div className="relative pl-7">
            {/* vertical rail */}
            <div className="absolute left-[13px] top-1.5 bottom-1.5 w-px bg-slate-200" />
            {steps.map((step, i) => (
              <StepRow key={i} step={step} index={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function HeaderChip({ status }: { status: ToolStatus }) {
  const cfg = {
    success: { bg: "bg-success-soft", fg: "text-success" },
    running: { bg: "bg-accent-soft", fg: "text-accent" },
    failed: { bg: "bg-critical-soft", fg: "text-critical" },
  }[status];
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center w-[20px] h-[20px] rounded-1 shrink-0",
        cfg.bg,
        cfg.fg,
      )}
    >
      {status === "success" && <Check size={13} strokeWidth={2.4} />}
      {status === "running" && (
        <span className="block w-[11px] h-[11px] rounded-full border-[1.5px] border-current border-t-transparent animate-spin" />
      )}
      {status === "failed" && <AlertCircle size={13} strokeWidth={2} />}
    </span>
  );
}

function StepRow({ step }: { step: PipelineStep; index: number }) {
  const { status } = step;
  return (
    <div className="relative flex items-start gap-3 py-1.5 first:pt-0 last:pb-0">
      {/* Status dot, positioned over the rail */}
      <span
        className={cn(
          "absolute -left-7 top-2 inline-flex items-center justify-center w-[14px] h-[14px] rounded-full",
          status === "success" && "bg-success-soft text-success ring-2 ring-card",
          status === "running" && "bg-accent-soft text-accent ring-2 ring-card",
          status === "failed" && "bg-critical-soft text-critical ring-2 ring-card",
          status === "pending" && "bg-slate-100 text-slate-400 ring-2 ring-card",
        )}
      >
        {status === "success" && <Check size={9} strokeWidth={2.6} />}
        {status === "running" && (
          <span className="block w-[7px] h-[7px] rounded-full border-[1.2px] border-current border-t-transparent animate-spin" />
        )}
        {status === "failed" && <AlertCircle size={9} strokeWidth={2.2} />}
        {status === "pending" && (
          <span className="block w-[5px] h-[5px] rounded-full bg-current" />
        )}
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span
            className={cn(
              "text-13 font-medium",
              status === "pending" ? "text-slate-400" : "text-ink",
            )}
          >
            {step.name}
          </span>
          {typeof step.duration_ms === "number" && (
            <span className="mono text-11 text-slate-400">
              {step.duration_ms < 1000
                ? `${step.duration_ms} ms`
                : `${(step.duration_ms / 1000).toFixed(1)} s`}
            </span>
          )}
        </div>
        {step.detail && (
          <div
            className={cn(
              "text-12 mt-0.5",
              status === "failed" ? "text-critical" : "text-slate-500",
            )}
          >
            {step.detail}
          </div>
        )}
      </div>
    </div>
  );
}
