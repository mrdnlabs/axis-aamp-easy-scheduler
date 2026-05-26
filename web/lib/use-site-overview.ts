"use client";

import * as React from "react";
import { getSiteOverview, type SiteOverview } from "@/lib/api";

export interface UseSiteOverviewResult {
  overview: SiteOverview | null;
  isLoading: boolean;
  error: { detail: string; status?: number } | null;
  refresh: () => Promise<void>;
}

export function useSiteOverview(siteId: number = 1): UseSiteOverviewResult {
  const [overview, setOverview] = React.useState<SiteOverview | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<UseSiteOverviewResult["error"]>(null);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await getSiteOverview(siteId);
      setOverview(next);
      setError(null);
    } catch (e: unknown) {
      const err = e as { status?: number; detail?: string; message?: string };
      setError({ status: err.status, detail: err.detail ?? err.message ?? String(e) });
    } finally {
      setIsLoading(false);
    }
  }, [siteId]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { overview, isLoading, error, refresh };
}
