"use client";

import { Lock, KeyRound, ExternalLink, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface GeminiSetupCardProps {
  /** Click handler for the primary "Set up securely" button. */
  onSetUp: () => void;
  /**
   * Layout density.
   *
   *   - ``"hero"`` — full-bleed centered card. Used when the missing
   *     key is the *only* thing on screen so it can't be missed.
   *   - ``"compact"`` — inline card variant for cases where the setup
   *     state appears next to other content (none today, kept for
   *     future flexibility).
   *
   * Defaults to ``"hero"``.
   */
  size?: "hero" | "compact";
}

/**
 * Setup card shown when the server reports ``gemini_configured: false``.
 *
 * Designed to be unmissable in hero mode: it occupies the whole chat
 * column, the headline is large, the primary action is the only
 * coloured button on screen. The composer is hidden in this state —
 * there is nothing to type into until the key lands.
 *
 * Trust-boundary visual cues (top gradient stripe, lock icon, "stored
 * in Credential Manager" copy) intentionally mirror SecureCaptureModal
 * so the two surfaces read as one workflow.
 */
export function GeminiSetupCard({ onSetUp, size = "hero" }: GeminiSetupCardProps) {
  const hero = size === "hero";
  return (
    <div
      className={cn(
        "rounded-3 border border-accent/30 bg-card shadow-2",
        "overflow-hidden",
        hero ? "w-full" : "my-4",
      )}
    >
      {/* Top stripe — same gradient as the secure-capture modal so the
          two surfaces read as siblings of the same trust boundary. */}
      <div
        className={cn("w-full", hero ? "h-2" : "h-1.5")}
        style={{
          background:
            "linear-gradient(90deg, #1a2540 0%, #2a3b6e 50%, #1a2540 100%)",
        }}
      />

      <div className={hero ? "px-8 py-8" : "px-5 py-4"}>
        <div className={cn("flex", hero ? "flex-col items-start gap-5" : "items-start gap-3")}>
          {/* Icon chip */}
          <span
            className={cn(
              "shrink-0 inline-flex items-center justify-center rounded-3",
              "bg-accent/10 text-accent",
              hero ? "w-14 h-14" : "w-9 h-9 rounded-2",
            )}
          >
            <KeyRound size={hero ? 28 : 18} strokeWidth={1.9} />
          </span>

          <div className="flex-1 min-w-0">
            {/* Eyebrow chip — only in hero mode, draws the eye fast */}
            {hero && (
              <div className="inline-flex items-center gap-1.5 mb-2 px-2 h-[20px] rounded-full bg-warning-soft text-warning border border-warning/30 text-11 font-semibold uppercase tracking-[0.06em]">
                <ShieldCheck size={11} strokeWidth={2.2} />
                Setup required
              </div>
            )}

            <h1
              className={cn(
                "font-semibold text-ink",
                hero ? "text-[22px] leading-tight" : "text-15",
              )}
            >
              {hero
                ? "Add your Gemini API key to start using ChAAMP"
                : "Set up Gemini to start chatting"}
            </h1>

            <p
              className={cn(
                "text-slate-600 leading-relaxed",
                hero ? "mt-2 text-14 max-w-[520px]" : "mt-1 text-13",
              )}
            >
              ChAAMP uses Google&apos;s Gemini API as its chat brain.{" "}
              {hero ? (
                <>
                  Your key is stored in Windows Credential Manager — it never
                  enters chat history or the LLM&apos;s context.
                </>
              ) : (
                <>
                  Your key is stored in Windows Credential Manager and never
                  enters chat or the LLM&apos;s context.
                </>
              )}
            </p>

            <div
              className={cn(
                "flex flex-wrap items-center gap-3",
                hero ? "mt-5" : "mt-3",
              )}
            >
              <Button onClick={onSetUp} size={hero ? "lg" : "md"}>
                <Lock size={hero ? 16 : 14} strokeWidth={1.9} className="mr-1.5" />
                Set up Gemini securely
              </Button>
              <a
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "inline-flex items-center gap-1 font-medium",
                  "text-accent hover:text-accent-700",
                  hero ? "text-14" : "text-13",
                )}
              >
                I need a key
                <ExternalLink size={hero ? 14 : 12} strokeWidth={2} />
              </a>
            </div>

            {/* CLI fallback */}
            <div
              className={cn(
                "border-t border-slate-100",
                hero ? "mt-6 pt-5" : "mt-3 pt-3",
              )}
            >
              <div className="text-11 uppercase tracking-[0.06em] font-semibold text-slate-500">
                Prefer the terminal?
              </div>
              <div
                className={cn(
                  "mt-1 text-slate-600",
                  hero ? "text-13" : "text-12",
                )}
              >
                Run{" "}
                <code className="mono bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 text-[12.5px]">
                  aamp-set-credential gemini/api_key
                </code>{" "}
                and reload this page.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
