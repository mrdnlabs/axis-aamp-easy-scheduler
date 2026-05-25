import { cn } from "@/lib/cn";

type Tone = "success" | "warning" | "critical" | "accent" | "neutral";

const TONE_BG: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  critical: "bg-critical",
  accent: "bg-accent",
  neutral: "bg-slate-400",
};

const TONE_RING: Record<Tone, string> = {
  success: "shadow-[0_0_0_3px_theme(colors.success.soft)]",
  warning: "shadow-[0_0_0_3px_theme(colors.warning.soft)]",
  critical: "shadow-[0_0_0_3px_theme(colors.critical.soft)]",
  accent: "shadow-[0_0_0_3px_theme(colors.accent.soft)]",
  neutral: "shadow-[0_0_0_3px_theme(colors.slate.100)]",
};

/**
 * A small filled dot used for status indicators throughout the app.
 *
 * Tones:
 *   - success — online, captured, applied
 *   - warning — needs attention, drifted
 *   - critical — offline, failed
 *   - accent — active selection, brand emphasis
 *   - neutral — unknown or pending
 *
 * Pass ``pulse`` to add a slow pulsing ring for "live" states (e.g. an
 * ongoing tool call). The ``size`` prop is the dot diameter in px.
 */
export function StatusDot({
  tone = "neutral",
  size = 8,
  pulse = false,
  className,
}: {
  tone?: Tone;
  size?: number;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block rounded-full",
        TONE_BG[tone],
        pulse && TONE_RING[tone],
        pulse && "animate-pulse-dot text-current",
        className,
      )}
      style={{ width: size, height: size }}
    />
  );
}
