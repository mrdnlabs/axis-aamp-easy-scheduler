"use client";

import * as React from "react";
import { getCurrentUser, type CurrentUser } from "@/lib/api";

export interface UseCurrentUserResult {
  user: CurrentUser | null;
  isLoading: boolean;
  error: { detail: string; status?: number } | null;
  /** Manual re-fetch — used when Settings change the required-group SID. */
  refresh: () => Promise<void>;
}

/**
 * Identify the connecting Windows user via ``/api/auth/me``.
 *
 * Mirrors :func:`useConfigStatus` shape. Called once at the top of
 * the app; the user object decides whether to render the chat
 * workspace or the access-denied screen.
 *
 * No auto-refresh on a timer: identity is stable for the life of a
 * browser tab. The only state-change paths are (a) admin edits the
 * required-group SID via Settings — we ``refresh()`` after that
 * mutation lands, and (b) the tab gets closed.
 */
export function useCurrentUser(): UseCurrentUserResult {
  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<UseCurrentUserResult["error"]>(null);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await getCurrentUser();
      setUser(next);
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

  return { user, isLoading, error, refresh };
}
