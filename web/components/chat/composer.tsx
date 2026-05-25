"use client";

import * as React from "react";
import { Paperclip, Command as CommandIcon, ArrowUp } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface ComposerProps {
  /** Context chips above the textarea — e.g. ["Lincoln MS", "This week", "12 devices · 4 zones"]. */
  contextChips?: string[];
  /** Suggested prompts that appear when the textarea is empty. */
  suggestions?: string[];
  /** Send callback. */
  onSend?: (text: string) => void;
  /**
   * When true, the composer is non-interactive — textarea, buttons,
   * and suggestion chips are all disabled. Use ``disabledReason`` to
   * tell the user why (rendered in the footer in place of the usual
   * helper text).
   */
  disabled?: boolean;
  /** One-line explanation shown in the footer when ``disabled`` is set. */
  disabledReason?: string;
}

/**
 * The chat composer — sticky to the bottom of the chat column.
 *
 * Layout per the handoff README:
 *   ┌──────────────────────────────────────────────────┐
 *   │ CONTEXT  [Lincoln MS] [This week] [12 dev]  Adjust│ <- slate-50 header
 *   ├──────────────────────────────────────────────────┤
 *   │ <textarea, 2 rows min>                            │
 *   │                                                   │
 *   ├──────────────────────────────────────────────────┤
 *   │ 📎 ⌘  Changes confirm before apply…   ⌘↵  [Send] │ <- footer
 *   └──────────────────────────────────────────────────┘
 *
 * Submit on Cmd/Ctrl+Enter. Suggestion strip above when empty.
 */
export function Composer({
  contextChips = [],
  suggestions = [],
  onSend,
  disabled = false,
  disabledReason,
}: ComposerProps) {
  const [value, setValue] = React.useState("");
  const taRef = React.useRef<HTMLTextAreaElement | null>(null);

  function handleSend() {
    if (disabled) return;
    const text = value.trim();
    if (!text) return;
    onSend?.(text);
    setValue("");
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (disabled) return;
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="w-full max-w-[820px] mx-auto px-6 pb-6 pt-2">
      {/* Suggestion strip — visible only when textarea is empty AND
          the composer is interactive. Hidden when disabled so the
          user isn't tempted to click chips that go nowhere. */}
      {!value && !disabled && suggestions.length > 0 && (
        <div className="flex gap-2 mb-2.5 overflow-x-auto pb-1 -mx-1 px-1">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => {
                setValue(s);
                taRef.current?.focus();
              }}
              className={cn(
                "whitespace-nowrap text-13 text-slate-700 h-8 px-3 rounded-full",
                "border border-slate-200 bg-card hover:bg-slate-50 transition-colors shrink-0",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div
        className={cn(
          "bg-card border border-slate-200 rounded-3 shadow-2 overflow-hidden",
          disabled && "opacity-70",
        )}
      >
        {/* Context header */}
        <div
          className={cn(
            "flex items-center gap-2.5 px-3.5 h-[34px]",
            "bg-slate-50 border-b border-slate-100",
            "text-11 uppercase tracking-[0.06em] text-slate-500 font-semibold",
          )}
        >
          <span>Context</span>
          <div className="flex items-center gap-1.5">
            {contextChips.map((c) => (
              <span
                key={c}
                className={cn(
                  "inline-flex items-center h-[22px] px-2 rounded-full",
                  "bg-card border border-slate-200",
                  "text-11 font-medium tracking-normal text-slate-700 normal-case",
                )}
              >
                {c}
              </span>
            ))}
          </div>
          <div className="flex-1" />
          <button
            disabled={disabled}
            className={cn(
              "text-11 tracking-normal normal-case font-medium",
              "text-accent hover:text-accent-700",
              "disabled:text-slate-400 disabled:hover:text-slate-400 disabled:cursor-not-allowed",
            )}
          >
            Adjust
          </button>
        </div>

        {/* Textarea */}
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          disabled={disabled}
          placeholder={
            disabled
              ? "Composer locked — finish setup above to start chatting."
              : "Describe what you want — e.g. ‘Move next Wednesday’s schedule 30 minutes later for the assembly.’"
          }
          rows={3}
          className={cn(
            "block w-full resize-none border-0 px-4 py-3.5",
            "font-ui text-[15px] leading-[1.5] text-ink placeholder:text-slate-400",
            "focus:outline-none bg-card",
            "disabled:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-500",
          )}
        />

        {/* Footer */}
        <div
          className={cn(
            "flex items-center gap-2 px-2.5 py-2",
            "border-t border-slate-100",
          )}
        >
          <IconButton aria-label="Attach file" size={30} disabled={disabled}>
            <Paperclip size={15} strokeWidth={1.8} />
          </IconButton>
          <IconButton aria-label="Quick command" size={30} disabled={disabled}>
            <CommandIcon size={15} strokeWidth={1.8} />
          </IconButton>
          <span className="text-12 text-slate-500 truncate">
            {disabled
              ? disabledReason ?? "Composer locked."
              : "Changes confirm before apply · passwords never enter chat."}
          </span>
          <div className="flex-1" />
          <span className="hidden sm:inline text-11 text-slate-400 mono">⌘ ↵ to send</span>
          <Button
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            iconRight={<ArrowUp size={14} strokeWidth={1.8} />}
            size="md"
          >
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}
