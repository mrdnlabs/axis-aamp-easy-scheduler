"use client";

import * as React from "react";
import { getSettings, putSetting, type SettingView } from "@/lib/api";

export interface UseSettingsResult {
  settings: SettingView[] | null;
  isLoading: boolean;
  error: { detail: string; status?: number } | null;
  refresh: () => Promise<void>;
  /** Write a single setting; the local cache is patched on success.
   *  Pass ``null`` to reset to default. */
  update: (key: string, value: unknown) => Promise<SettingView>;
}

export function useSettings(): UseSettingsResult {
  const [settings, setSettings] = React.useState<SettingView[] | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<UseSettingsResult["error"]>(null);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await getSettings();
      setSettings(next);
      setError(null);
    } catch (e: unknown) {
      const err = e as { status?: number; detail?: string; message?: string };
      setError({ status: err.status, detail: err.detail ?? err.message ?? String(e) });
    } finally {
      setIsLoading(false);
    }
  }, []);

  const update = React.useCallback(async (key: string, value: unknown) => {
    const updated = await putSetting(key, value);
    setSettings((prev) =>
      prev ? prev.map((s) => (s.key === key ? updated : s)) : prev,
    );
    return updated;
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { settings, isLoading, error, refresh, update };
}
