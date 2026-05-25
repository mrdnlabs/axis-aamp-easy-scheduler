"use client";

import * as React from "react";
import { getConfigStatus, type ConfigStatus } from "@/lib/api";

/**
 * Snapshot of the server's credential configuration.
 *
 * The frontend calls this on mount and after a successful credential
 * capture so the composer-gate state stays in sync. We deliberately do
 * NOT poll on a timer: status only changes through user action (capture
 * modal submit / CLI run), and refresh() can be called explicitly when
 * those happen.
 */
export interface UseConfigStatusResult {
  /** Latest status fetch; ``null`` until the first request resolves. */
  status: ConfigStatus | null;
  /** True while a fetch is in flight (first load OR refresh). */
  isLoading: boolean;
  /** Error from the most recent fetch, ``null`` after a successful one. */
  error: { detail: string; status?: number } | null;
  /** Force a re-fetch — call this after a credential is captured. */
  refresh: () => Promise<void>;
}

export function useConfigStatus(): UseConfigStatusResult {
  const [status, setStatus] = React.useState<ConfigStatus | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<UseConfigStatusResult["error"]>(null);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await getConfigStatus();
      setStatus(next);
      setError(null);
    } catch (e: unknown) {
      const err = e as { status?: number; detail?: string; message?: string };
      setError({
        status: err.status,
        detail: err.detail ?? err.message ?? String(e),
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { status, isLoading, error, refresh };
}
