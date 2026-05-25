"use client";

import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Lock, Check, X, Copy, AlertCircle } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { startCapture, submitCapture, ApiError } from "@/lib/api";

interface SecureCaptureModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Two ways to drive the modal:
   *   (a) Pass ``credentialKey`` — the modal mints a fresh capture token
   *       on open by calling ``/api/credential-capture/start``.
   *   (b) Pass ``token`` — the modal uses an existing token (typical when
   *       the LLM has already called ``request_credential_capture``).
   * If both are supplied, ``token`` wins.
   */
  credentialKey?: string;
  token?: string;
  /** Optional description override (shown on the lock chip). */
  description?: string;
  /** Callback fired after the keyring write succeeds. */
  onCaptured?: (info: { account_id: string; field: string }) => void;
}

type Phase = "loading" | "input" | "working" | "captured" | "error";

/**
 * The full-page credential capture modal.
 *
 * This is the most security-critical surface in ChAAMP. The modal is
 * visually framed as **isolated from the chat** — warm cream background,
 * 6px gradient stripe, dark lock chip, OUT-OF-CONTEXT badge with a
 * pulsing live dot. The user types here; the value POSTs directly to
 * the local capture endpoint at /api/credential-capture (proxied to the
 * Python sidecar at localhost:7331); the LLM only ever receives a
 * yes/no confirmation.
 *
 * Hard rules enforced visually:
 *   - No reveal-password toggle anywhere.
 *   - No "show last character" affordance.
 *   - Always-present CLI fallback at the bottom so power users can skip
 *     the modal entirely.
 *
 * The four phases:
 *   - input    — entering + confirming the password
 *   - working  — POSTing to the capture endpoint (~1s spinner)
 *   - captured — success banner; auto-dismisses after a moment
 *
 * For the demo, this component simulates the working+captured states
 * with timers; in production the submit handler will fetch() the
 * capture endpoint and resolve on its response.
 */
export function SecureCaptureModal({
  open,
  onOpenChange,
  credentialKey,
  token: tokenProp,
  description: descOverride,
  onCaptured,
}: SecureCaptureModalProps) {
  const [phase, setPhase] = React.useState<Phase>("loading");
  const [pwd, setPwd] = React.useState("");
  const [pwd2, setPwd2] = React.useState("");
  const [token, setToken] = React.useState<string | null>(tokenProp ?? null);
  const [slot, setSlot] = React.useState<{
    account_id: string;
    field: string;
    description: string;
    expires_in_seconds: number;
  } | null>(null);
  const [error, setError] = React.useState<{ status?: number; detail: string } | null>(null);
  // When the password doesn't meet the recommended strength, clicking
  // "Capture and store" shows an inline confirmation rather than blocking
  // outright. Two clicks for weak passwords; one click for strong.
  const [confirmingWeak, setConfirmingWeak] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // On open: mint a token (or fetch one if provided), then transition to input.
  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPhase("loading");
    setPwd("");
    setPwd2("");
    setError(null);
    setConfirmingWeak(false);

    (async () => {
      try {
        if (tokenProp) {
          // Caller provided a token — we trust them and use it as-is.
          setToken(tokenProp);
          // Status fetch would go here in a future revision so the modal
          // shows the live countdown. For now we use defaults.
          setSlot({
            account_id: parseCredentialKey(credentialKey ?? "").account_id,
            field: parseCredentialKey(credentialKey ?? "").field,
            description: descOverride ?? "",
            expires_in_seconds: 600,
          });
        } else if (credentialKey) {
          const { account_id, field } = parseCredentialKey(credentialKey);
          const res = await startCapture({ account_id, field });
          if (cancelled) return;
          setToken(res.token);
          setSlot({
            account_id: res.account_id,
            field: res.field,
            description: descOverride ?? res.description,
            expires_in_seconds: res.expires_in_seconds,
          });
        } else {
          throw new Error("SecureCaptureModal requires credentialKey or token");
        }
        if (cancelled) return;
        setPhase("input");
        setTimeout(() => inputRef.current?.focus(), 80);
      } catch (e) {
        if (cancelled) return;
        setPhase("error");
        setError(
          e instanceof ApiError
            ? { status: e.status, detail: e.detail }
            : { detail: String(e) },
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, credentialKey, tokenProp, descOverride]);

  const strong = pwd.length >= 12 && /[A-Z]/.test(pwd) && /[0-9]/.test(pwd);
  // Server-side validation enforces >= 4 chars (capture.MIN_VALUE_LENGTH).
  // We mirror that floor here so the button isn't enabled for values the
  // server will reject. Anything 4+ chars that matches can submit; weak
  // values trigger the confirmation dialog first.
  const matches = pwd.length >= 4 && pwd === pwd2;
  const canSubmit = matches && phase === "input";

  const cli = `aamp-set-credential ${
    slot ? `${slot.account_id}/${slot.field}` : credentialKey ?? ""
  }`;

  /**
   * Click handler for the primary submit button. If the password is
   * strong (or the user has already confirmed they want to proceed with
   * a weak one), submit directly. Otherwise show the inline warning
   * and wait for the user's explicit "Save anyway".
   */
  function handlePrimaryClick() {
    if (strong || confirmingWeak) {
      void submit();
    } else {
      setConfirmingWeak(true);
    }
  }

  async function submit() {
    if (!token) return;
    setPhase("working");
    try {
      const res = await submitCapture(token, pwd);
      setPhase("captured");
      setPwd("");
      setPwd2("");
      setTimeout(() => {
        onCaptured?.({ account_id: res.account_id, field: res.field });
        onOpenChange(false);
      }, 1400);
    } catch (e) {
      setPhase("error");
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          className={cn(
            "fixed inset-0 bg-ink/40 backdrop-blur-[3px] z-[200]",
            "animate-fade-in",
          )}
        />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
            "w-[540px] max-w-[calc(100vw-32px)] bg-[#FFFCF8] border border-[#F0E5D0]",
            "rounded-4 shadow-modal overflow-hidden z-[201]",
            "animate-fade-up",
          )}
          aria-describedby={undefined}
        >
          <Dialog.Title className="sr-only">Set credential securely</Dialog.Title>

          {/* gradient stripe */}
          <div className="h-1.5 w-full bg-audio-gradient" aria-hidden="true" />

          {/* Header */}
          <div className="px-[26px] pt-[22px] pb-4 border-b border-ink/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full",
                  "bg-ink/[0.88] text-white",
                  "text-[10.5px] font-semibold uppercase tracking-[0.08em]",
                )}
              >
                <span
                  className={cn(
                    "block w-1.5 h-1.5 rounded-full bg-emerald-400",
                    "shadow-[0_0_0_3px_rgba(74,222,128,0.25)]",
                    "animate-pulse-dot text-emerald-400",
                  )}
                />
                Out-of-context capture
              </span>
              <Dialog.Close asChild>
                <IconButton aria-label="Close">
                  <X size={16} strokeWidth={1.8} />
                </IconButton>
              </Dialog.Close>
            </div>

            <div className="flex items-start gap-3.5">
              <span
                className={cn(
                  "inline-flex items-center justify-center w-[44px] h-[44px] rounded-3 shrink-0",
                  "bg-ink text-white",
                  "shadow-[0_6px_20px_-8px_rgba(15,23,42,0.5)]",
                )}
              >
                <Lock size={20} strokeWidth={1.9} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-11 font-semibold text-slate-500 uppercase tracking-[0.06em]">
                  Set credential
                </div>
                <div className="mono text-18 font-semibold text-ink mt-0.5">
                  {slot ? `${slot.account_id}/${slot.field}` : credentialKey ?? "…"}
                </div>
                <div className="text-13 text-slate-600 mt-1 leading-relaxed">
                  {slot?.description ?? descOverride ?? "Loading…"}
                </div>
              </div>
            </div>
          </div>

          {/* Body */}
          <div className="px-[26px] pt-4 pb-5">
            {/* Trust-model panel */}
            <div className="flex gap-3 items-start px-3.5 py-3 bg-ink/[0.04] border border-ink/[0.06] rounded-2 mb-4">
              <Lock size={16} strokeWidth={1.8} className="text-slate-600 mt-0.5 shrink-0" />
              <div className="text-[12.5px] leading-[1.55] text-slate-700">
                This window is <strong>isolated from ChAAMP</strong>. What you
                type goes through a one-time URL straight into{" "}
                <span className="mono">Windows Credential Manager</span>. The
                assistant only receives a yes/no confirmation — never the value.
                <div className="text-[11.5px] text-slate-500 mt-1">
                  Session token{" "}
                  <span className="mono bg-card px-1.5 py-px rounded-1 border border-slate-200">
                    {token ? `${token.slice(0, 8)}…${token.slice(-4)}` : "minting…"}
                  </span>{" "}
                  · expires in {formatExpiry(slot?.expires_in_seconds ?? 600)}
                </div>
              </div>
            </div>

            {phase === "loading" && (
              <div className="py-6 flex flex-col items-center gap-2.5">
                <span className="block w-6 h-6 rounded-full border-[2px] border-accent border-t-transparent animate-spin" />
                <div className="text-13 text-slate-600">Preparing secure capture…</div>
              </div>
            )}

            {phase === "error" && (
              <div className="flex gap-3 items-start px-4 py-3.5 bg-critical-soft border border-critical/30 rounded-3">
                <AlertCircle size={18} strokeWidth={2} className="text-critical shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="text-13 font-semibold text-critical">
                    Capture failed
                    {error?.status !== undefined && (
                      <span className="mono ml-2 text-12 font-medium text-slate-500">
                        HTTP {error.status}
                      </span>
                    )}
                  </div>
                  <div className="text-[12.5px] text-slate-700 mt-0.5">
                    {error?.detail ?? "Unknown error."}
                  </div>
                  <div className="text-[12.5px] text-slate-500 mt-2 leading-relaxed">
                    {errorHint(error)} Use the terminal fallback below, or close
                    and retry.
                  </div>
                </div>
              </div>
            )}

            {phase === "input" && (
              <>
                <FieldLabel>Password</FieldLabel>
                <SecureInput ref={inputRef} value={pwd} onChange={setPwd} />
                <PwdStrength value={pwd} />

                <div className="mt-3">
                  <FieldLabel>Confirm</FieldLabel>
                  <SecureInput
                    value={pwd2}
                    onChange={setPwd2}
                    matchHint={pwd && pwd2 ? (matches ? "match" : "no-match") : null}
                  />
                </div>

                {/* Inline confirm prompt for weak passwords */}
                {confirmingWeak && !strong && (
                  <div className="mt-3 flex gap-3 items-start px-3.5 py-3 bg-warning-soft border border-warning/30 rounded-2">
                    <AlertCircle size={16} strokeWidth={2} className="text-warning shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="text-13 font-semibold text-warning">
                        This password is below recommended strength.
                      </div>
                      <div className="text-[12.5px] text-slate-700 mt-0.5 leading-relaxed">
                        Strong passwords use 12+ characters with mixed case and a
                        digit. Axis devices often accept weaker values, so we
                        let you proceed — but production fleets should use
                        stronger ones.
                      </div>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between pt-3 mt-1 gap-2">
                  <Button
                    variant="ghost"
                    size="md"
                    onClick={() => {
                      if (confirmingWeak) {
                        // Back out of the warning without closing the modal.
                        setConfirmingWeak(false);
                      } else {
                        onOpenChange(false);
                      }
                    }}
                  >
                    {confirmingWeak ? "Back" : "Cancel"}
                  </Button>
                  <Button
                    variant="primary"
                    size="md"
                    onClick={handlePrimaryClick}
                    disabled={!canSubmit}
                    iconLeft={<Lock size={14} strokeWidth={1.9} />}
                  >
                    {confirmingWeak && !strong ? "Save anyway" : "Capture and store"}
                  </Button>
                </div>
              </>
            )}

            {phase === "working" && (
              <div className="py-6 flex flex-col items-center gap-2.5">
                <span className="block w-6 h-6 rounded-full border-[2px] border-accent border-t-transparent animate-spin" />
                <div className="text-13 text-slate-600">
                  Writing to Windows Credential Manager…
                </div>
              </div>
            )}

            {phase === "captured" && (
              <div className="flex gap-3.5 items-center px-4 py-3.5 bg-success-soft border border-success/30 rounded-3">
                <span className="inline-flex items-center justify-center w-9 h-9 rounded-2 bg-success text-white shrink-0">
                  <Check size={18} strokeWidth={2.4} />
                </span>
                <div className="flex-1">
                  <div className="text-14 font-semibold text-emerald-900">
                    Credential captured
                  </div>
                  <div className="text-[12.5px] text-emerald-700 mt-0.5">
                    ChAAMP can now use{" "}
                    <span className="mono">
                      {slot ? `${slot.account_id}/${slot.field}` : credentialKey}
                    </span>{" "}
                    for its next tool call. The value never entered this
                    conversation.
                  </div>
                </div>
              </div>
            )}

            {/* CLI fallback — always present */}
            <div className="mt-[18px] pt-[18px] border-t border-dashed border-ink/10">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11.5px] font-semibold text-slate-500 uppercase tracking-[0.06em]">
                  Prefer terminal?
                </div>
                <span className="text-11 text-slate-400">Same outcome.</span>
              </div>
              <CliBlock command={cli} />
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ---------------------------------------------------------------------------
// Internal pieces
// ---------------------------------------------------------------------------

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-12 font-semibold text-slate-500 uppercase tracking-[0.06em] mb-1.5">
      {children}
    </div>
  );
}

interface SecureInputProps {
  value: string;
  onChange: (v: string) => void;
  matchHint?: "match" | "no-match" | null;
}

/**
 * The masked password input. INTENTIONALLY does not expose a reveal-password
 * toggle. The border color shifts when the confirm field matches / doesn't
 * match (the only signal the user gets that they typed correctly without
 * us actually showing the value).
 */
const SecureInput = React.forwardRef<HTMLInputElement, SecureInputProps>(
  ({ value, onChange, matchHint }, ref) => {
    const borderClass =
      matchHint === "match"
        ? "border-success"
        : matchHint === "no-match"
          ? "border-critical"
          : "border-slate-200";
    return (
      <div
        className={cn(
          "flex items-center gap-2.5 px-3 h-[42px] bg-card border-[1.5px] rounded-2 transition-colors",
          borderClass,
        )}
      >
        <Lock size={15} strokeWidth={1.8} className="text-slate-400 shrink-0" />
        <input
          ref={ref}
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="new-password"
          spellCheck={false}
          className={cn(
            "flex-1 bg-transparent outline-none border-0 p-0",
            "mono text-[14px] tracking-[0.04em] text-ink",
            "placeholder:text-slate-400",
          )}
          placeholder="••••••••••••"
        />
      </div>
    );
  },
);
SecureInput.displayName = "SecureInput";

interface PwdStrengthProps {
  value: string;
}

/** 5-segment password-strength meter. Length-driven; complexity adds boost. */
function PwdStrength({ value }: PwdStrengthProps) {
  const score = scorePassword(value);
  const labels = ["Add 12+", "Weak", "Fair", "Good", "Strong"];
  const colors = ["bg-slate-200", "bg-critical", "bg-warning", "bg-success", "bg-success"];
  return (
    <div className="flex items-center gap-2 mt-2">
      <div className="flex flex-1 gap-1">
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className={cn(
              "h-1.5 flex-1 rounded-full transition-colors",
              i < score ? colors[score - 1] : "bg-slate-200",
            )}
          />
        ))}
      </div>
      <span className="text-11 text-slate-500 w-[60px] text-right shrink-0">
        {labels[Math.max(0, Math.min(4, score))]}
      </span>
    </div>
  );
}

function scorePassword(v: string): 0 | 1 | 2 | 3 | 4 | 5 {
  if (!v) return 0;
  if (v.length < 8) return 1;
  let score = 0;
  if (v.length >= 8) score++;
  if (v.length >= 12) score++;
  if (/[A-Z]/.test(v) && /[a-z]/.test(v)) score++;
  if (/[0-9]/.test(v) && /[^A-Za-z0-9]/.test(v)) score++;
  return Math.min(5, score + 1) as 1 | 2 | 3 | 4 | 5;
}

/** Compact dark CodeBlock with a copy-to-clipboard button. */
function CliBlock({ command }: { command: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-ink rounded-2 group">
      <code className="flex-1 mono text-[12.5px] text-slate-100 truncate">{command}</code>
      <button
        onClick={() => {
          navigator.clipboard?.writeText(command);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
        className={cn(
          "inline-flex items-center gap-1 px-2 py-1 rounded-1",
          "text-[11px] font-medium",
          copied ? "text-success" : "text-slate-300 hover:text-white",
        )}
        aria-label="Copy command"
      >
        {copied ? <Check size={12} strokeWidth={2.4} /> : <Copy size={12} strokeWidth={2} />}
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function formatExpiry(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Translate an ApiError into a one-sentence hint for the user.
 *
 * The most common failure in dev is "backend not running" — the Next.js
 * dev server rewrites /api/credential-capture/* to localhost:7331, and if
 * nothing's listening there the rewrite produces a 5xx with a vague body.
 * Surface that case clearly.
 */
function errorHint(err: { status?: number; detail: string } | null): string {
  if (!err) return "";
  if (err.status === undefined || err.status === 0) {
    return "Looks like the backend isn't reachable. Start it with `aamp-server` in a terminal, then retry.";
  }
  if (err.status === 404) {
    return "The capture endpoint returned 404. The Python sidecar may be running with stale code — restart `aamp-server`.";
  }
  if (err.status >= 500) {
    return "The Python sidecar hit an internal error. Check its terminal log for a traceback, or restart it.";
  }
  return "";
}

/** Split ``"device/default_password"`` into ``{account_id, field}``. */
function parseCredentialKey(key: string): { account_id: string; field: string } {
  const ix = key.indexOf("/");
  if (ix < 0) return { account_id: key, field: "" };
  return { account_id: key.slice(0, ix), field: key.slice(ix + 1) };
}
