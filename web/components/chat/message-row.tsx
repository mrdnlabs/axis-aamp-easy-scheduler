import { BrandMark } from "@/components/brand";
import { cn } from "@/lib/cn";

interface MessageRowProps {
  role: "user" | "assistant";
  userInitials?: string;
  timestamp: string;
  children: React.ReactNode;
}

/**
 * One conversation row in the chat column.
 *
 * Two-column grid: 36px avatar gutter + 1fr content.
 *
 *   - User avatar: slate-200 bg + 28×28 square + initials (slate-700)
 *   - Assistant avatar: audio-gradient bg with the BrandMark glyph,
 *     a soft accent-tinted shadow underneath
 *   - Author label + assistant pill ("ASSISTANT" in accent-soft)
 *   - Timestamp in mono 11.5px slate-400
 *   - Body content is whatever the caller passes (text, widgets, pills)
 */
export function MessageRow({
  role,
  userInitials = "—",
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
          <span
            className={cn(
              "inline-flex items-center justify-center w-7 h-7 rounded-[8px]",
              "bg-slate-200 text-slate-700 font-semibold text-[10.5px]",
            )}
            aria-hidden="true"
          >
            {userInitials}
          </span>
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
