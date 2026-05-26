"use client";

import * as React from "react";
import { getCredentials, type CredentialSlotView } from "@/lib/api";

export interface UseCredentialsResult {
  credentials: CredentialSlotView[] | null;
  isLoading: boolean;
  error: { detail: string; status?: number } | null;
  refresh: () => Promise<void>;
}

export function useCredentials(): UseCredentialsResult {
  const [credentials, setCredentials] = React.useState<CredentialSlotView[] | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<UseCredentialsResult["error"]>(null);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await getCredentials();
      setCredentials(next);
      setError(null);
    } catch (e: unknown) {
      const err = e as { status?: number; detail?: string; message?: string };
      setError({ status: err.status, detail: err.detail ?? err.message ?? String(e) });
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { credentials, isLoading, error, refresh };
}
