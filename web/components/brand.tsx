import { cn } from "@/lib/cn";

/**
 * The ChAAMP brand glyph — a chat bubble with a 3-bump sine wave inside,
 * white-on-audio-gradient. Used as the assistant avatar in chat messages
 * (sized 16px inside a 28px rounded square) and inside the Logo component
 * (sized 16px inside a 28px rounded square at the topbar).
 *
 * The brand intent: "chat + audio" without resorting to a literal speaker.
 */
export function BrandMark({
  size = 28,
  className,
}: {
  size?: number;
  className?: string;
}) {
  const glyphSize = Math.round(size * 0.55);
  const radius = Math.round(size * 0.28);
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center bg-audio-gradient shadow-1",
        className,
      )}
      style={{
        width: size,
        height: size,
        borderRadius: radius,
      }}
      aria-hidden="true"
    >
      <svg
        width={glyphSize}
        height={glyphSize}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* speech bubble outline */}
        <path d="M4 6.5a2.5 2.5 0 0 1 2.5-2.5h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4 3.5v-3.5H6.5A2.5 2.5 0 0 1 4 13.5z" />
        {/* sine wave inside — three bumps, slightly more subtle than the outline */}
        <path
          d="M8 10.5q1.2 -1.5 2.4 0 t2.4 0 t2.4 0"
          strokeWidth="1.4"
          opacity=".85"
        />
      </svg>
    </span>
  );
}

/**
 * The full ChAAMP wordmark — brand glyph + the "ChAAMP" lockup.
 *
 * Read: "Chat with AAMP". "Ch" is slate-500 (deliberately quieted)
 * so the brain reads "AAMP" first and "Ch" snaps into place after.
 */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <BrandMark size={size} />
      <span
        className="font-ui font-bold text-[16px] leading-none -tracking-[0.015em]"
        aria-label="ChAAMP"
      >
        <span className="text-slate-500">Ch</span>
        <span className="text-ink">AAMP</span>
      </span>
    </span>
  );
}
