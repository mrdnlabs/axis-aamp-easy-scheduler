"use client";

import * as React from "react";
import { Check, AlertCircle, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ToolCallPart, ToolStatus } from "@/lib/types";

interface ToolCallCardProps extends Omit<ToolCallPart, "kind"> {
  defaultOpen?: boolean;
}

/**
 * Single-tool-call summary card.
 *
 * Collapsed by default — single horizontal line:
 *   [status-icon-chip]  tool_name (mono)  · summary (truncated)  ▼
 *
 * Expanded body shows args + result on slate-50 mono blocks.
 *
 * Status colors:
 *   - success: success-soft chip, green check
 *   - running: accent-soft chip, spinner
 *   - failed:  critical-soft chip, alert
 */
export function ToolCallCard({
  name,
  summary,
  args,
  result,
  status,
  duration_ms,
  defaultOpen = false,
}: ToolCallCardProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="border border-slate-200 rounded-2 bg-card shadow-1 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left cursor-pointer hover:bg-slate-50 transition-colors"
        aria-expanded={open}
      >
        <StatusChip status={status} />
        <span className="mono text-12 text-slate-700 font-medium">{name}</span>
        <span className="flex-1 text-[12.5px] text-slate-500 truncate min-w-0">
          {summary}
        </span>
        {typeof duration_ms === "number" && (
          <span className="mono text-11 text-slate-400 shrink-0">
            {formatDuration(duration_ms)}
          </span>
        )}
        <ChevronDown
          size={14}
          strokeWidth={1.8}
          className={cn(
            "text-slate-400 shrink-0 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (args || result) && (
        <div className="px-3 pb-3 pl-10 flex flex-col gap-2">
          {args && <CodeBlock label="Args" content={args} />}
          {result && <CodeBlock label="Result" content={result} />}
        </div>
      )}
    </div>
  );
}

function StatusChip({ status }: { status: ToolStatus }) {
  const cfg = {
    success: { bg: "bg-success-soft", fg: "text-success" },
    running: { bg: "bg-accent-soft", fg: "text-accent" },
    failed: { bg: "bg-critical-soft", fg: "text-critical" },
  }[status];
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center w-[18px] h-[18px] rounded-1 shrink-0",
        cfg.bg,
        cfg.fg,
      )}
    >
      {status === "success" && <Check size={12} strokeWidth={2.4} />}
      {status === "running" && (
        <span
          className="block w-[10px] h-[10px] rounded-full border-[1.5px] border-current border-t-transparent animate-spin"
          aria-label="Running"
        />
      )}
      {status === "failed" && <AlertCircle size={12} strokeWidth={2} />}
    </span>
  );
}

function CodeBlock({ label, content }: { label: string; content: string }) {
  return (
    <div>
      <div className="text-[10.5px] text-slate-400 uppercase tracking-[0.06em] mb-1 font-semibold">
        {label}
      </div>
      <pre className="m-0 mono text-[11.5px] text-slate-700 bg-slate-50 px-2.5 py-2 rounded-1 whitespace-pre-wrap border border-slate-100">
        {content}
      </pre>
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60000).toFixed(1)} m`;
}
