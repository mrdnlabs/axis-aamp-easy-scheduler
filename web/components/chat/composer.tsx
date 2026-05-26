"use client";

import * as React from "react";
import { Paperclip, Command as CommandIcon, ArrowUp, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface ComposerProps {
  /** Context chips above the textarea — e.g. ["Lincoln MS", "This week", "12 devices · 4 zones"]. */
  contextChips?: string[];
  /** Suggested prompts that appear when the textarea is empty. */
  suggestions?: string[];
  /** Send callback. Receives the text and any queued attachments. */
  onSend?: (text: string, files?: File[]) => void;
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

// Accepted MIME types for chat attachments — matches what Gemini's
// inline-data path supports and what aamp.chat's CLI uploader accepts.
// Browsers translate this into the file picker's filter.
const ACCEPTED_FILE_TYPES = [
  ".pdf",
  ".csv",
  ".txt",
  ".md",
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
].join(",");

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
  const [files, setFiles] = React.useState<File[]>([]);
  const taRef = React.useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  function handleSend() {
    if (disabled) return;
    const text = value.trim();
    if (!text) return;
    onSend?.(text, files.length > 0 ? files : undefined);
    setValue("");
    setFiles([]);
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (disabled) return;
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  }

  function handleAttachClick() {
    if (disabled) return;
    fileInputRef.current?.click();
  }

  function handleFilesPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length === 0) return;
    setFiles((prev) => [...prev, ...picked]);
    // Reset the input so the same file can be picked again later.
    e.target.value = "";
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
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

      {/* Attached-files chip strip — only when there are queued files. */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {files.map((f, i) => (
            <span
              key={`${f.name}_${i}`}
              className={cn(
                "inline-flex items-center gap-1.5 h-7 pl-2.5 pr-1.5 rounded-full",
                "bg-accent-soft text-accent-700 border border-accent/20",
                "text-12 max-w-[260px]",
              )}
              title={`${f.name} (${formatFileSize(f.size)})`}
            >
              <Paperclip size={11} strokeWidth={2} className="shrink-0" />
              <span className="truncate">{f.name}</span>
              <span className="text-accent/70 mono text-[10.5px] shrink-0">
                {formatFileSize(f.size)}
              </span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                className={cn(
                  "inline-flex items-center justify-center w-4 h-4 rounded-full",
                  "hover:bg-accent/10 shrink-0",
                )}
                aria-label={`Remove ${f.name}`}
              >
                <X size={11} strokeWidth={2.2} />
              </button>
            </span>
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
          <IconButton
            aria-label="Attach file"
            size={30}
            disabled={disabled}
            onClick={handleAttachClick}
          >
            <Paperclip size={15} strokeWidth={1.8} />
          </IconButton>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_TYPES}
            className="hidden"
            onChange={handleFilesPicked}
          />
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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
