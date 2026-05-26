"use client";

import { ShieldX, ExternalLink } from "lucide-react";
import { cn } from "@/lib/cn";
import type { CurrentUser } from "@/lib/api";

interface AccessDeniedScreenProps {
  user: CurrentUser | null;
}

/**
 * Full-screen hero rendered when the connecting Windows user isn't a
 * member of the configured admin group — or when peer identification
 * failed entirely.
 *
 * We deliberately show the user's actual Windows username + SID so
 * they can:
 *   - confirm they're signed into the right account (vs. a
 *     stale RDP session under someone else's name)
 *   - report the SID to whoever administers the AAM Pro install
 *
 * There's no "Sign in as another user" button because we can't
 * trigger that from a web page on Windows — the user has to switch
 * Windows users, restart the browser as a different account via
 * ``runas``, or RDP in differently.
 */
export function AccessDeniedScreen({ user }: AccessDeniedScreenProps) {
  // Three message variants depending on what we know:
  //  - We identified the user but they're not admin  → primary case
  //  - We couldn't identify them at all              → race / connection-reset case
  //  - The hook hasn't loaded yet                    → loading sentinel; rare
  const identified = user?.username != null;
  const requiredGroup = user?.required_group_sid ?? "S-1-5-32-544";
  const adminBuiltin = requiredGroup === "S-1-5-32-544";

  return (
    <div className="h-screen flex items-center justify-center px-6 py-12 bg-surface">
      <div
        className={cn(
          "w-full max-w-[640px] rounded-3 border border-critical/30",
          "bg-card shadow-2 overflow-hidden",
        )}
      >
        <div
          className="h-2 w-full"
          style={{
            background:
              "linear-gradient(90deg, #b91c1c 0%, #dc2626 50%, #b91c1c 100%)",
          }}
        />
        <div className="px-8 py-8">
          <div className="flex flex-col items-start gap-5">
            <span
              className={cn(
                "inline-flex items-center justify-center w-14 h-14 rounded-3",
                "bg-critical-soft text-critical",
              )}
            >
              <ShieldX size={28} strokeWidth={1.9} />
            </span>

            <div className="inline-flex items-center gap-1.5 px-2 h-[20px] rounded-full bg-critical-soft text-critical border border-critical/30 text-11 font-semibold uppercase tracking-[0.06em]">
              <ShieldX size={11} strokeWidth={2.2} />
              Access denied
            </div>

            <h1 className="text-[22px] font-semibold text-ink leading-tight">
              {identified
                ? "Your Windows account doesn't have access to ChAAMP"
                : "We couldn't identify your Windows account"}
            </h1>

            {identified ? (
              <p className="text-14 text-slate-600 leading-relaxed max-w-[520px]">
                Signed in as{" "}
                <span className="mono font-semibold text-ink">
                  {user!.username}
                </span>
                . ChAAMP requires membership in{" "}
                {adminBuiltin ? (
                  <>
                    the local{" "}
                    <span className="mono">BUILTIN\Administrators</span> group
                  </>
                ) : (
                  <>
                    the Windows group with SID{" "}
                    <span className="mono">{requiredGroup}</span>
                  </>
                )}
                . Sign in as an administrator to use the app.
              </p>
            ) : (
              <p className="text-14 text-slate-600 leading-relaxed max-w-[520px]">
                ChAAMP authenticates by checking which Windows user opened the
                TCP connection to the local sidecar. We couldn&apos;t resolve
                that — usually a transient race during page reload. Refresh to
                try again.
              </p>
            )}

            {identified && (
              <div className="w-full mt-2 rounded-2 border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-10 font-semibold uppercase tracking-[0.06em] text-slate-500 mb-1.5">
                  Signed-in account
                </div>
                <div className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-12">
                  <div className="text-slate-500">Username</div>
                  <div className="mono text-ink">{user!.username}</div>
                  <div className="text-slate-500">SID</div>
                  <div className="mono text-slate-700 break-all">{user!.sid}</div>
                  <div className="text-slate-500">Required group</div>
                  <div className="mono text-slate-700">{requiredGroup}</div>
                </div>
              </div>
            )}

            <div className="mt-2 pt-4 border-t border-slate-100 w-full">
              <div className="text-11 uppercase tracking-[0.06em] font-semibold text-slate-500">
                What to do
              </div>
              <ul className="mt-2 space-y-1.5 text-13 text-slate-700 leading-relaxed">
                <li className="flex gap-2">
                  <span className="text-slate-400">·</span>
                  Sign out of Windows and back in as an administrator account,
                  then reload this page.
                </li>
                <li className="flex gap-2">
                  <span className="text-slate-400">·</span>
                  Or have your administrator add your account to{" "}
                  <span className="mono">BUILTIN\Administrators</span> (or the
                  configured ChAAMP-access group).
                </li>
                <li className="flex gap-2">
                  <span className="text-slate-400">·</span>
                  If you&apos;re trying to test with a different account, launch
                  the browser via{" "}
                  <span className="mono">runas /user:name chrome.exe</span>.
                </li>
              </ul>
            </div>

            <a
              href="https://learn.microsoft.com/windows/security/identity-protection/access-control/local-accounts"
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-13 text-accent hover:text-accent-700 font-medium"
            >
              About Windows local-accounts and groups
              <ExternalLink size={12} strokeWidth={2} />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
