"use client";

import * as React from "react";
import { getAudit, type AuditEntry, type AuditQuery } from "@/lib/api";

export interface UseAuditResult {
  entries: AuditEntry[] | null;
  isLoading: boolean;
  error: { detail: string; status?: number } | null;
  query: AuditQuery;
  /** Updates the filter; the next refresh applies it. */
  setQuery: (next: AuditQuery) => void;
  /** Manual reload. Audit refreshes intentionally are not on a timer
   *  (would self-loop on read-only inspection). */
  refresh: () => Promise<void>;
}

export function useAudit(initial: AuditQuery = { limit: 50 }): UseAuditResult {
  const [entries, setEntries] = React.useState<AuditEntry[] | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<UseAuditResult["error"]>(null);
  const [query, setQuery] = React.useState<AuditQuery>(initial);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await getAudit(query);
      setEntries(next);
      setError(null);
    } catch (e: unknown) {
      const err = e as { status?: number; detail?: string; message?: string };
      setError({ status: err.status, detail: err.detail ?? err.message ?? String(e) });
    } finally {
      setIsLoading(false);
    }
  }, [query]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { entries, isLoading, error, query, setQuery, refresh };
}
