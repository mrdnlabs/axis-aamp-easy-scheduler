"use client";

import { Lock, KeyRound, ExternalLink, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface GeminiSetupCardProps {
  /** Click handler for the primary "Set up securely" button. */
  onSetUp: () => void;
}

/**
 * Setup card shown when the server reports ``gemini_configured: false``.
 *
 * Hero-style: occupies the whole chat column, the headline is large,
 * the primary action is the only coloured button on screen. The
 * composer is hidden in this state — there's nothing to type into
 * until the key lands.
 *
 * Trust-boundary visual cues (top gradient stripe, lock icon, "stored
 * in Credential Manager" copy) intentionally mirror SecureCaptureModal
 * so the two surfaces read as one workflow.
 */
export function GeminiSetupCard({ onSetUp }: GeminiSetupCardProps) {
  return (
    <div className="rounded-3 border border-accent/30 bg-card shadow-2 overflow-hidden w-full">
      {/* Top stripe — same gradient as the secure-capture modal so the
          two surfaces read as siblings of the same trust boundary. */}
      <div
        className="h-2 w-full"
        style={{
          background:
            "linear-gradient(90deg, #1a2540 0%, #2a3b6e 50%, #1a2540 100%)",
        }}
      />

      <div className="px-8 py-8">
        <div className="flex flex-col items-start gap-5">
          {/* Icon chip */}
          <span
            className={cn(
              "shrink-0 inline-flex items-center justify-center rounded-3",
              "bg-accent/10 text-accent w-14 h-14",
            )}
          >
            <KeyRound size={28} strokeWidth={1.9} />
          </span>

          <div className="flex-1 min-w-0">
            {/* Eyebrow chip — draws the eye fast */}
            <div className="inline-flex items-center gap-1.5 mb-2 px-2 h-[20px] rounded-full bg-warning-soft text-warning border border-warning/30 text-11 font-semibold uppercase tracking-[0.06em]">
              <ShieldCheck size={11} strokeWidth={2.2} />
              Setup required
            </div>

            <h1 className="font-semibold text-ink text-[22px] leading-tight">
              Add your Gemini API key to start using ChAAMP
            </h1>

            <p className="text-slate-600 leading-relaxed mt-2 text-14 max-w-[520px]">
              ChAAMP uses Google&apos;s Gemini API as its chat brain. Your key
              is stored in Windows Credential Manager — it never enters chat
              history or the LLM&apos;s context.
            </p>

            <div className="flex flex-wrap items-center gap-3 mt-5">
              <Button onClick={onSetUp} size="lg">
                <Lock size={16} strokeWidth={1.9} className="mr-1.5" />
                Set up Gemini securely
              </Button>
              <a
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "inline-flex items-center gap-1 font-medium",
                  "text-accent hover:text-accent-700 text-14",
                )}
              >
                I need a key
                <ExternalLink size={14} strokeWidth={2} />
              </a>
            </div>

            {/* CLI fallback */}
            <div className="border-t border-slate-100 mt-6 pt-5">
              <div className="text-11 uppercase tracking-[0.06em] font-semibold text-slate-500">
                Prefer the terminal?
              </div>
              <div className="mt-1 text-slate-600 text-13">
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
