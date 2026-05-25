"use client";

import { Check, AlertCircle, Cpu, Network } from "lucide-react";
import { cn } from "@/lib/cn";
import { BrandMark } from "@/components/brand";
import type { OnboardingArtifact as OnboardingArtifactData } from "@/lib/types";

interface OnboardingArtifactProps {
  data: OnboardingArtifactData;
}

/**
 * Live device-onboarding view for the right-side artifact pane.
 *
 * Two cards:
 *   1. Device-facts grid (IP, model, MAC, arch, firmware, classification).
 *      Fields populate as the pipeline runs — initially most are blank
 *      because we don't know yet.
 *   2. Vertical-timeline pipeline mirroring PipelineCard. Each step has
 *      a tone-coded status dot and an optional inline detail.
 *
 * Status comes from the same PipelineStep union the chat-inline
 * PipelineCard uses — pending / running / success / failed.
 */
export function OnboardingArtifact({ data }: OnboardingArtifactProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* Device facts */}
      <div className="bg-card border border-slate-200 rounded-3 shadow-1 px-4 py-3.5">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-10 font-semibold text-slate-500 uppercase tracking-[0.06em]">
            Device
          </span>
          {data.model ? (
            <StatusChip tone="success" label="Identified" />
          ) : (
            <StatusChip tone="neutral" label="Inspecting…" />
          )}
        </div>
        <div className="flex items-baseline gap-2 mb-3">
          <h2 className="text-18 font-semibold text-ink tracking-tight">
            {data.model ?? "Unknown model"}
            {data.ip && (
              <span className="mono text-13 text-slate-500 ml-2 tabular-nums">
                · {data.ip}
              </span>
            )}
          </h2>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <Fact icon={Network} label="MAC" value={data.mac} />
          <Fact icon={Cpu} label="Architecture" value={data.arch} />
          <Fact label="Firmware" value={data.firmware} mono />
          <Fact label="Classification" value={data.classification} />
        </dl>
      </div>

      {/* Pipeline */}
      <div className="bg-card border border-slate-200 rounded-3 shadow-1 px-4 py-3.5">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-10 font-semibold text-slate-500 uppercase tracking-[0.06em]">
            Provisioning pipeline
          </span>
          <PipelineSummary steps={data.steps} />
        </div>
        <div className="relative pl-7">
          <div className="absolute left-[13px] top-1.5 bottom-1.5 w-px bg-slate-200" />
          {data.steps.map((step, i) => (
            <Step key={i} step={step} isLast={i === data.steps.length - 1} />
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="px-3.5 py-2.5 bg-surface-2 rounded-2 flex gap-3 items-start">
        <BrandMark size={22} />
        <div className="text-[12.5px] text-slate-700 leading-relaxed">
          When provisioning completes, the device dials the AAM Pro server
          over TLS 6998 and registers in the <span className="mono">aam_dev</span>{" "}
          table — usually within 30 seconds. Reload the AAM Pro SPA to see it
          listed there.
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal pieces
// ---------------------------------------------------------------------------

function Fact({
  icon: Icon,
  label,
  value,
  mono,
}: {
  icon?: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  label: string;
  value?: string;
  mono?: boolean;
}) {
  const placeholder = !value;
  return (
    <>
      <dt className="flex items-center gap-1.5 text-11 font-medium text-slate-500 uppercase tracking-[0.04em] py-1">
        {Icon && <Icon size={11} strokeWidth={1.8} className="text-slate-400 shrink-0" />}
        {label}
      </dt>
      <dd
        className={cn(
          "text-[13.5px] py-1",
          mono && "mono tabular-nums",
          placeholder ? "text-slate-400 italic" : "text-ink",
        )}
      >
        {value || "—"}
      </dd>
    </>
  );
}

type Step = OnboardingArtifactData["steps"][number];

function Step({ step, isLast }: { step: Step; isLast: boolean }) {
  return (
    <div className="relative flex items-start gap-3 py-1.5 first:pt-0">
      <span
        className={cn(
          "absolute -left-7 top-2 inline-flex items-center justify-center w-[14px] h-[14px] rounded-full ring-2 ring-card",
          step.status === "success" && "bg-success-soft text-success",
          step.status === "running" && "bg-accent-soft text-accent",
          step.status === "failed" && "bg-critical-soft text-critical",
          step.status === "pending" && "bg-slate-100 text-slate-400",
        )}
      >
        {step.status === "success" && <Check size={9} strokeWidth={2.6} />}
        {step.status === "running" && (
          <span className="block w-[7px] h-[7px] rounded-full border-[1.2px] border-current border-t-transparent animate-spin" />
        )}
        {step.status === "failed" && <AlertCircle size={9} strokeWidth={2.2} />}
        {step.status === "pending" && (
          <span className="block w-[5px] h-[5px] rounded-full bg-current" />
        )}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span
            className={cn(
              "text-13 font-medium",
              step.status === "pending" ? "text-slate-400" : "text-ink",
            )}
          >
            {step.name}
          </span>
          {typeof step.duration_ms === "number" && (
            <span className="mono text-11 text-slate-400 tabular-nums">
              {step.duration_ms < 1000
                ? `${step.duration_ms} ms`
                : `${(step.duration_ms / 1000).toFixed(1)} s`}
            </span>
          )}
        </div>
        {step.detail && (
          <div
            className={cn(
              "text-[12.5px] mt-0.5",
              step.status === "failed" ? "text-critical" : "text-slate-500",
            )}
          >
            {step.detail}
          </div>
        )}
      </div>
    </div>
  );
}

function PipelineSummary({ steps }: { steps: Step[] }) {
  const done = steps.filter((s) => s.status === "success").length;
  const failed = steps.some((s) => s.status === "failed");
  const running = steps.findIndex((s) => s.status === "running");

  if (failed) {
    return <StatusChip tone="critical" label={`Failed at step ${steps.findIndex((s) => s.status === "failed") + 1}`} />;
  }
  if (running >= 0) {
    return <StatusChip tone="accent" label={`Step ${running + 1} of ${steps.length}`} />;
  }
  if (done === steps.length) {
    return <StatusChip tone="success" label="Complete" />;
  }
  return <StatusChip tone="neutral" label={`${done} / ${steps.length} steps`} />;
}

function StatusChip({
  tone,
  label,
}: {
  tone: "neutral" | "success" | "warning" | "critical" | "accent";
  label: string;
}) {
  const toneClass = {
    neutral: "bg-slate-100 text-slate-700",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
    critical: "bg-critical-soft text-critical",
    accent: "bg-accent-soft text-accent-700",
  }[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center h-[18px] px-1.5 rounded-1",
        toneClass,
        "text-[10.5px] font-semibold uppercase tracking-[0.06em]",
      )}
    >
      {label}
    </span>
  );
}
