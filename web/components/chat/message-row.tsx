import { BrandMark } from "@/components/brand";
import { cn } from "@/lib/cn";

interface MessageRowProps {
  role: "user" | "assistant";
  timestamp: string;
  children: React.ReactNode;
}

/**
 * One conversation row in the chat column.
 *
 * Two-column grid: 36px avatar gutter + 1fr content.
 *
 *   - Assistant avatar: audio-gradient bg with the BrandMark glyph,
 *     a soft accent-tinted shadow underneath.
 *   - User avatar: a small neutral chip — ChAAMP serves the
 *     organization and authentication is handled via Windows peer
 *     identity in the TopBar, so we don't repeat identity here.
 *   - Author label + assistant pill ("ASSISTANT" in accent-soft).
 *   - Timestamp in mono 11.5px slate-400.
 *   - Body content is whatever the caller passes (text, widgets, pills).
 */
export function MessageRow({
  role,
  timestamp,
  children,
}: MessageRowProps) {
  return (
    <div className="grid grid-cols-[36px_1fr] gap-3.5 py-3 animate-fade-up">
      {/* Avatar gutter */}
      <div className="flex pt-0.5">
        {role === "assistant" ? (
          <BrandMark size={28} />
        ) : (
          // Neutral filler — the "You" label below identifies the row;
          // a name/initials would imply identity we deliberately don't
          // track per-message.
          <span
            className={cn(
              "inline-block w-7 h-7 rounded-[8px]",
              "bg-slate-100 border border-slate-200",
            )}
            aria-hidden="true"
          />
        )}
      </div>

      {/* Content column */}
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-13 font-semibold text-ink">
            {role === "assistant" ? "ChAAMP" : "You"}
          </span>
          {role === "assistant" && (
            <span
              className={cn(
                "inline-flex items-center h-[18px] px-1.5 rounded-1",
                "bg-accent-soft text-accent-700",
                "text-[10.5px] font-semibold uppercase tracking-[0.06em]",
              )}
            >
              Assistant
            </span>
          )}
          <span className="text-[11.5px] text-slate-400 mono">{timestamp}</span>
        </div>
        <div className="text-14 leading-[1.6] text-ink space-y-3">
          {children}
        </div>
      </div>
    </div>
  );
}
