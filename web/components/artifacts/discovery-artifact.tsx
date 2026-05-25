"use client";

import { Check, AlertCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import type {
  DiscoveryArtifact as DiscoveryArtifactData,
  DiscoveryMethodResult,
  DiscoveredDevice,
} from "@/lib/types";

interface DiscoveryArtifactProps {
  data: DiscoveryArtifactData;
}

/**
 * Result of a multi-protocol LAN-discovery sweep.
 *
 * Two stacked sections:
 *   1. Per-method tally — one row per protocol with its hit count + timing
 *   2. Merged device list grouped by classification (audio first, then
 *      audio?, then aam-pro-server, then non-audio, then unknown)
 *
 * The grouping matches the MCP tool's classification scheme (see
 * ``src/aamp/axis_models.py``). Each device row shows IP, MAC, model,
 * and the "+" delimited list of methods that found it — useful for
 * tuning which discovery methods earn their cost on a given LAN.
 */
export function DiscoveryArtifact({ data }: DiscoveryArtifactProps) {
  const grouped = groupByClass(data.devices);
  return (
    <div className="flex flex-col gap-4">
      {/* Method tally */}
      <div className="bg-card border border-slate-200 rounded-3 shadow-1 px-4 py-3.5">
        <div className="flex items-center justify-between mb-3">
          <div className="text-10 font-semibold text-slate-500 uppercase tracking-[0.06em]">
            Discovery methods
          </div>
          {typeof data.total_seconds === "number" && (
            <span className="mono text-11 text-slate-400 tabular-nums">
              total {data.total_seconds.toFixed(1)} s
            </span>
          )}
        </div>
        <ul className="flex flex-col gap-1.5">
          {data.methods.map((m) => (
            <MethodRow key={m.name} method={m} />
          ))}
        </ul>
      </div>

      {/* Devices grouped by class */}
      <div className="bg-card border border-slate-200 rounded-3 shadow-1 px-4 py-3.5">
        <div className="flex items-center justify-between mb-3">
          <div className="text-10 font-semibold text-slate-500 uppercase tracking-[0.06em]">
            Devices found
          </div>
          <span className="mono text-11 text-slate-400 tabular-nums">
            {data.devices.length} unique IP(s)
          </span>
        </div>
        {ORDER.map((cls) => {
          const rows = grouped[cls];
          if (!rows || rows.length === 0) return null;
          return (
            <DeviceGroup
              key={cls}
              label={LABELS[cls]}
              tone={TONES[cls]}
              devices={rows}
            />
          );
        })}
        {data.devices.length === 0 && (
          <div className="text-13 text-slate-500 italic py-2">
            No devices found on the swept subnet.
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal pieces
// ---------------------------------------------------------------------------

function MethodRow({ method }: { method: DiscoveryMethodResult }) {
  const ok = method.error == null;
  const empty = method.devices_found === 0;
  return (
    <li className="flex items-center gap-2.5">
      <span
        className={cn(
          "inline-flex items-center justify-center w-[18px] h-[18px] rounded-1 shrink-0",
          ok && !empty && "bg-success-soft text-success",
          ok && empty && "bg-slate-100 text-slate-500",
          !ok && "bg-critical-soft text-critical",
        )}
      >
        {ok ? <Check size={11} strokeWidth={2.4} /> : <AlertCircle size={11} strokeWidth={2} />}
      </span>
      <span className="mono text-13 text-slate-700 font-medium tabular-nums">
        {method.name}
      </span>
      <span
        className={cn(
          "text-13 tabular-nums",
          empty ? "text-slate-400" : "text-ink font-medium",
        )}
      >
        {method.devices_found}
      </span>
      <span className="text-12 text-slate-500">device{method.devices_found === 1 ? "" : "s"}</span>
      <div className="flex-1" />
      <span className="mono text-11 text-slate-400 tabular-nums">
        {method.seconds.toFixed(1)} s
      </span>
      {method.error && (
        <span className="text-11 text-critical italic truncate max-w-[160px]" title={method.error}>
          {method.error}
        </span>
      )}
    </li>
  );
}

function DeviceGroup({
  label,
  tone,
  devices,
}: {
  label: string;
  tone: "audio" | "neutral" | "secondary";
  devices: DiscoveredDevice[];
}) {
  const labelClass = {
    audio: "text-accent-700",
    secondary: "text-slate-600",
    neutral: "text-slate-500",
  }[tone];
  return (
    <div className="mt-2 first:mt-0">
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className={cn("text-11 font-semibold uppercase tracking-[0.06em]", labelClass)}>
          {label}
        </span>
        <span className="text-11 text-slate-400 tabular-nums">{devices.length}</span>
      </div>
      <ul className="flex flex-col gap-0.5">
        {devices.map((d) => (
          <li
            key={d.ip}
            className="grid grid-cols-[110px_1fr_auto] items-baseline gap-3 py-1 text-[12.5px]"
          >
            <span className="mono tabular-nums text-ink">{d.ip}</span>
            <span className="text-slate-700 truncate min-w-0">
              {d.model ?? <em className="text-slate-400">unidentified</em>}
              {d.audio_subtype && (
                <span className="ml-1.5 inline-flex items-center h-[16px] px-1 rounded-1 bg-slate-100 text-[10px] font-medium text-slate-700">
                  {d.audio_subtype}
                </span>
              )}
              {d.mac && (
                <span className="ml-1.5 mono text-11 text-slate-400 tabular-nums">
                  {d.mac}
                </span>
              )}
            </span>
            <span className="mono text-10 text-slate-400 truncate max-w-[200px]" title={d.sources}>
              {d.sources}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Classification helpers
// ---------------------------------------------------------------------------

type Cls = "audio" | "audio?" | "aam-pro-server" | "non-audio" | "unknown";

const ORDER: Cls[] = ["audio", "audio?", "aam-pro-server", "non-audio", "unknown"];

const LABELS: Record<Cls, string> = {
  audio: "Audio (confirmed)",
  "audio?": "Audio (heuristic)",
  "aam-pro-server": "AAM Pro server hardware",
  "non-audio": "Non-audio Axis",
  unknown: "Unclassified",
};

const TONES: Record<Cls, "audio" | "neutral" | "secondary"> = {
  audio: "audio",
  "audio?": "audio",
  "aam-pro-server": "secondary",
  "non-audio": "secondary",
  unknown: "neutral",
};

function groupByClass(devices: DiscoveredDevice[]): Partial<Record<Cls, DiscoveredDevice[]>> {
  const out: Partial<Record<Cls, DiscoveredDevice[]>> = {};
  for (const d of devices) {
    const cls = (ORDER as string[]).includes(d.device_class)
      ? (d.device_class as Cls)
      : "unknown";
    (out[cls] ??= []).push(d);
  }
  return out;
}
