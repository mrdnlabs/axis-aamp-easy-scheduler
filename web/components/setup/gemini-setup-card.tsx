"use client";

import { Lock, KeyRound, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface GeminiSetupCardProps {
  /** Click handler for the primary "Set up securely" button. */
  onSetUp: () => void;
}

/**
 * One-shot setup card shown at the top of the chat column when the
 * server reports ``gemini_configured: false``.
 *
 * Designed to be self-contained: it tells the user *why* they're seeing
 * this card (no key configured), *what* it does (gates chat), and *how*
 * to fix it (two options — secure modal or CLI). The composer below is
 * disabled until a key lands.
 */
export function GeminiSetupCard({ onSetUp }: GeminiSetupCardProps) {
  return (
    <div
      className={cn(
        "my-4 rounded-3 border border-accent/30 bg-card shadow-1",
        "overflow-hidden",
      )}
    >
      {/* Top stripe — same gradient as the secure-capture modal so the
          two surfaces read as siblings of the same trust boundary. */}
      <div
        className="h-1.5 w-full"
        style={{
          background:
            "linear-gradient(90deg, #1a2540 0%, #2a3b6e 50%, #1a2540 100%)",
        }}
      />

      <div className="px-5 py-4">
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "shrink-0 inline-flex items-center justify-center",
              "w-9 h-9 rounded-2 bg-accent/10 text-accent",
            )}
          >
            <KeyRound size={18} strokeWidth={1.9} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-15 font-semibold text-ink">
              Set up Gemini to start chatting
            </div>
            <p className="mt-1 text-13 text-slate-600 leading-relaxed">
              ChAAMP uses Google&apos;s Gemini API as its chat brain. Your key
              is stored in Windows Credential Manager and never enters the
              chat or the LLM&apos;s context.
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-2.5">
              <Button onClick={onSetUp} size="md">
                <Lock size={14} strokeWidth={1.9} className="mr-1.5" />
                Set up Gemini securely
              </Button>
              <a
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "inline-flex items-center gap-1 text-13 text-accent hover:text-accent-700",
                  "font-medium",
                )}
              >
                Get a key
                <ExternalLink size={12} strokeWidth={2} />
              </a>
            </div>

            <div className="mt-3 pt-3 border-t border-slate-100">
              <div className="text-11 uppercase tracking-[0.06em] font-semibold text-slate-500">
                Prefer the terminal?
              </div>
              <div className="mt-1 text-12 text-slate-600">
                Run{" "}
                <code className="mono bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 text-[12px]">
                  aamp-set-credential gemini/api_key
                </code>{" "}
                and refresh this page.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
