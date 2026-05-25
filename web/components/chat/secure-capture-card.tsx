"use client";

import { Lock, Check, AlertTriangle, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { SecureCapturePart } from "@/lib/types";

interface SecureCaptureCardProps extends Omit<SecureCapturePart, "kind"> {
  onSetSecurely?: () => void;
  onCopyCli?: () => void;
}

/**
 * Inline-chat card requesting a credential. Critical security pattern:
 * passwords MUST NEVER enter the LLM context. This card directs the user
 * to either the secure modal (which posts to a local capture endpoint) or
 * the CLI fallback. Neither path round-trips the value through the chat.
 *
 * Visual identity is deliberately distinct from other chat widgets:
 *   - Warm cream background (#FFFCF8) — signals "this is not a normal card"
 *   - 3px gradient stripe across the top — brand continuity
 *   - Dark slate lock chip on the left — security signal
 *
 * Three states:
 *   - normal: shows the request + Set securely / Copy CLI buttons
 *   - captured: shows a green check + "value is in Windows Credential Manager"
 *   - denied: user pasted a value in chat — show a warning to redirect them
 */
export function SecureCaptureCard({
  key: credentialKey,
  description,
  captured,
  denied_because_value_offered,
  onSetSecurely,
  onCopyCli,
}: SecureCaptureCardProps) {
  // --- captured state ---
  if (captured) {
    return (
      <div className="rounded-3 border border-success-soft bg-success-soft overflow-hidden">
        <GradientStripe />
        <div className="flex items-center gap-3 px-4 py-3">
          <span className="inline-flex items-center justify-center w-[34px] h-[34px] rounded-2 bg-success text-white shadow-1 shrink-0">
            <Check size={17} strokeWidth={2.4} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="mono text-[13px] font-semibold text-ink">
                {credentialKey}
              </span>
              <span
                className={cn(
                  "inline-flex items-center h-[18px] px-1.5 rounded-1",
                  "bg-success text-white text-[10.5px] font-semibold uppercase tracking-[0.06em]",
                )}
              >
                Captured
              </span>
            </div>
            <div className="text-12 text-slate-700 mt-0.5">
              Value is in Windows Credential Manager. ChAAMP never saw it.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-3 border border-[#F0E5D0] bg-[#FFFCF8] overflow-hidden">
      <GradientStripe />

      {/* "you accidentally typed a value in chat" warning */}
      {denied_because_value_offered && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-critical-soft border-b border-critical/20 text-13 text-critical">
          <AlertTriangle size={15} strokeWidth={2} className="shrink-0" />
          <span>
            You pasted a value in chat. I didn&apos;t read it — please use the
            secure capture below or the CLI instead.
          </span>
        </div>
      )}

      <div className="flex items-start gap-3.5 px-4 py-3.5">
        <span className="inline-flex items-center justify-center w-[34px] h-[34px] rounded-2 bg-ink text-white shadow-1 shrink-0">
          <Lock size={16} strokeWidth={1.9} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="mono text-[13px] font-semibold text-ink">
              {credentialKey}
            </span>
            <span
              className={cn(
                "inline-flex items-center h-[18px] px-1.5 rounded-1",
                "bg-slate-100 text-slate-700",
                "text-[10.5px] font-semibold uppercase tracking-[0.06em]",
              )}
            >
              Out-of-context
            </span>
          </div>
          <p className="text-13 text-slate-700 mt-1.5 mb-3 leading-[1.55]">
            {description} The value goes straight to your OS credential vault
            — it never enters this conversation.
          </p>

          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant="primary"
              size="sm"
              iconLeft={<Lock size={13} strokeWidth={1.9} />}
              onClick={onSetSecurely}
            >
              Set securely
            </Button>
            <Button
              variant="ghost"
              size="sm"
              iconLeft={<Terminal size={13} strokeWidth={1.9} />}
              onClick={onCopyCli}
            >
              Copy CLI command
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function GradientStripe() {
  return <div className="h-[3px] bg-audio-gradient" aria-hidden="true" />;
}
