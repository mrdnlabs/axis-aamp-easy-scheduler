"use client";

import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  X,
  AlertCircle,
  Loader2,
  Filter,
  RefreshCw,
  Check,
  ShieldX,
} from "lucide-react";
import { IconButton, Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useAudit } from "@/lib/use-audit";
import type { AuditEntry } from "@/lib/api";

interface AuditLogPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Op categories worth filtering on. Free-form text input handles
// anything else if the user knows what they're looking for.
const COMMON_OPS = [
  "get",
  "set",
  "delete",
  "list",
  "capture_start",
  "capture_submit",
] as const;

const LIMIT_OPTIONS = [25, 50, 100, 200, 500] as const;

/**
 * Read-only viewer for ``~/.aamp_audit.log``.
 *
 * No auto-refresh — that would log a "audit_log_viewed" or similar
 * entry on every tick, which is both spammy and recursive. The user
 * pulls the Refresh button when they want new data.
 */
export function AuditLogPanel({ open, onOpenChange }: AuditLogPanelProps) {
  const { entries, isLoading, error, query, setQuery, refresh } = useAudit({
    limit: 50,
  });

  // Re-fetch when the panel re-opens (e.g., after a credential
  // capture that should now appear).
  React.useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  // Local form state to avoid re-fetching on every keystroke.
  const [localOp, setLocalOp] = React.useState<string>(query.op ?? "");
  const [localPrincipal, setLocalPrincipal] = React.useState<string>(
    query.principal ?? "",
  );
  const [localLimit, setLocalLimit] = React.useState<number>(query.limit ?? 50);

  function applyFilters() {
    setQuery({
      op: localOp.trim() || undefined,
      principal: localPrincipal.trim() || undefined,
      limit: localLimit,
    });
  }

  function clearFilters() {
    setLocalOp("");
    setLocalPrincipal("");
    setLocalLimit(50);
    setQuery({ limit: 50 });
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          className={cn(
            "fixed inset-0 bg-ink/40 backdrop-blur-[3px] z-[150]",
            "animate-fade-in",
          )}
        />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
            "w-[760px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-64px)]",
            "bg-card border border-slate-200 rounded-4 shadow-modal",
            "flex flex-col z-[151] animate-fade-up overflow-hidden",
          )}
        >
          <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 shrink-0">
            <Filter size={18} className="text-slate-500" strokeWidth={1.9} />
            <div className="flex-1 min-w-0">
              <Dialog.Title className="text-15 font-semibold text-ink">
                Audit log
              </Dialog.Title>
              <Dialog.Description className="text-12 text-slate-500 mt-0.5">
                Every credential read/write recorded by the local audit logger.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <IconButton aria-label="Close">
                <X size={16} strokeWidth={1.8} />
              </IconButton>
            </Dialog.Close>
          </div>

          {/* Filter bar */}
          <div className="flex flex-wrap items-end gap-3 px-5 py-3 border-b border-slate-200 bg-slate-50 shrink-0">
            <label className="flex flex-col gap-1">
              <span className="text-10 font-semibold uppercase tracking-[0.06em] text-slate-500">
                Op
              </span>
              <input
                list="audit-op-options"
                type="text"
                value={localOp}
                onChange={(e) => setLocalOp(e.target.value)}
                placeholder="any"
                className={cn(
                  "h-8 px-2.5 rounded-2 border border-slate-200 bg-card",
                  "text-13 text-ink mono w-[160px]",
                  "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20",
                )}
              />
              <datalist id="audit-op-options">
                {COMMON_OPS.map((o) => (
                  <option key={o} value={o} />
                ))}
              </datalist>
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-10 font-semibold uppercase tracking-[0.06em] text-slate-500">
                Principal
              </span>
              <input
                type="text"
                value={localPrincipal}
                onChange={(e) => setLocalPrincipal(e.target.value)}
                placeholder="any"
                className={cn(
                  "h-8 px-2.5 rounded-2 border border-slate-200 bg-card",
                  "text-13 text-ink mono w-[160px]",
                  "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20",
                )}
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-10 font-semibold uppercase tracking-[0.06em] text-slate-500">
                Limit
              </span>
              <select
                value={localLimit}
                onChange={(e) => setLocalLimit(parseInt(e.target.value, 10))}
                className={cn(
                  "h-8 px-2 rounded-2 border border-slate-200 bg-card",
                  "text-13 text-ink mono",
                  "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20",
                )}
              >
                {LIMIT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex-1" />

            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={applyFilters}
              iconLeft={<Filter size={12} strokeWidth={2} />}
            >
              Apply
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void refresh()}
              disabled={isLoading}
              iconLeft={
                isLoading ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <RefreshCw size={12} strokeWidth={2} />
                )
              }
            >
              Refresh
            </Button>
          </div>

          {/* Table */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            {error && (
              <div className="m-5 flex gap-2.5 items-start px-3 py-2.5 bg-critical-soft border border-critical/30 rounded-2">
                <AlertCircle size={16} className="text-critical mt-0.5 shrink-0" />
                <div className="flex-1 text-13 text-slate-700">
                  <div className="font-semibold text-critical">
                    Couldn&apos;t load audit log
                  </div>
                  <div className="text-12 mt-0.5">{error.detail}</div>
                </div>
              </div>
            )}

            {!entries && isLoading && (
              <div className="py-12 flex items-center justify-center text-13 text-slate-500">
                <Loader2 size={16} className="animate-spin mr-2" />
                Loading…
              </div>
            )}

            {entries && entries.length === 0 && !isLoading && (
              <div className="py-12 text-13 text-slate-500 text-center italic">
                No entries match the current filters.
              </div>
            )}

            {entries && entries.length > 0 && (
              <table className="w-full text-12">
                <thead className="bg-slate-50 sticky top-0 z-10">
                  <tr className="text-left">
                    <th className="px-5 py-2 text-10 font-semibold uppercase tracking-[0.06em] text-slate-500 w-[150px]">
                      When
                    </th>
                    <th className="px-2 py-2 text-10 font-semibold uppercase tracking-[0.06em] text-slate-500 w-[110px]">
                      Op
                    </th>
                    <th className="px-2 py-2 text-10 font-semibold uppercase tracking-[0.06em] text-slate-500">
                      Slot
                    </th>
                    <th className="px-2 py-2 text-10 font-semibold uppercase tracking-[0.06em] text-slate-500 w-[100px]">
                      Principal
                    </th>
                    <th className="px-5 py-2 text-10 font-semibold uppercase tracking-[0.06em] text-slate-500 w-[90px]">
                      Decision
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {entries.map((e, i) => (
                    <AuditRow key={i} entry={e} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const slot =
    entry.account_id || entry.field
      ? `${entry.account_id ?? "?"}/${entry.field ?? "?"}`
      : "—";
  const decisionBad = entry.decision && entry.decision !== "ok";
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-5 py-1.5 mono text-slate-500 tabular-nums">
        {formatTs(entry.ts)}
      </td>
      <td className="px-2 py-1.5 mono text-ink">{entry.op ?? "—"}</td>
      <td className="px-2 py-1.5 mono text-slate-700 truncate" title={slot}>
        {slot}
      </td>
      <td className="px-2 py-1.5 mono text-slate-500">
        {entry.principal ?? "—"}
      </td>
      <td className="px-5 py-1.5">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 px-1.5 h-[18px] rounded-1 text-11",
            decisionBad
              ? "bg-critical-soft text-critical"
              : "bg-success-soft text-success",
          )}
          title={entry.reason ?? ""}
        >
          {decisionBad ? (
            <ShieldX size={11} strokeWidth={2.2} />
          ) : (
            <Check size={11} strokeWidth={2.4} />
          )}
          {entry.decision ?? "ok"}
        </span>
      </td>
    </tr>
  );
}

function formatTs(ts: string | undefined): string {
  if (!ts) return "—";
  // The audit writer emits ISO-ish timestamps. Show date + HH:MM:SS
  // in local time so the table stays scannable.
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
  } catch {
    return ts;
  }
}
