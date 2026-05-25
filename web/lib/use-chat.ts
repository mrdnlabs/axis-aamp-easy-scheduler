"use client";

import * as React from "react";
import { streamChatMessage, ApiError, type HistoryMessage } from "@/lib/api";
import type { ChatMessage, MessagePart, ToolCallPart } from "@/lib/types";

/**
 * Chat state + send-message hook.
 *
 * - Holds the message array (user + assistant turns).
 * - Posts to ``/api/chat/message`` and consumes the SSE stream.
 * - Merges streaming parts into the latest assistant message in real time.
 * - Replaces tool-call ``running`` parts with their ``success``/``failed``
 *   updates so cards render in place instead of duplicating.
 *
 * Stateless on the wire — the server gets the full history each send.
 */
export interface UseChatResult {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: { detail: string; status?: number } | null;
  send: (text: string) => Promise<void>;
  reset: () => void;
}

const SESSION_ID =
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `s_${Math.random().toString(36).slice(2)}`;

export function useChat(initialAssistantText?: string): UseChatResult {
  const [messages, setMessages] = React.useState<ChatMessage[]>(() =>
    initialAssistantText
      ? [
          {
            id: `m_${Date.now()}`,
            role: "assistant",
            ts: new Date().toISOString(),
            parts: [{ kind: "text", body: initialAssistantText }],
          },
        ]
      : [],
  );
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [error, setError] = React.useState<UseChatResult["error"]>(null);

  const reset = React.useCallback(() => {
    setMessages(
      initialAssistantText
        ? [
            {
              id: `m_${Date.now()}`,
              role: "assistant",
              ts: new Date().toISOString(),
              parts: [{ kind: "text", body: initialAssistantText }],
            },
          ]
        : [],
    );
    setError(null);
    setIsStreaming(false);
  }, [initialAssistantText]);

  const send = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      setError(null);

      // Snapshot the current message list, then append the user message
      // and a fresh empty assistant message that parts will stream into.
      const now = new Date().toISOString();
      const userMsg: ChatMessage = {
        id: `m_${Date.now()}_u`,
        role: "user",
        ts: now,
        parts: [{ kind: "text", body: trimmed }],
      };
      const asstMsg: ChatMessage = {
        id: `m_${Date.now()}_a`,
        role: "assistant",
        ts: now,
        parts: [],
      };
      const history = messagesToHistory(messages);
      setMessages((prev) => [...prev, userMsg, asstMsg]);
      setIsStreaming(true);

      try {
        for await (const ev of streamChatMessage({
          text: trimmed,
          history,
          session_id: SESSION_ID,
        })) {
          if (ev.event === "part") {
            const part = ev.data as MessagePart;
            setMessages((prev) => appendPart(prev, asstMsg.id, part));
          } else if (ev.event === "error") {
            const d = ev.data as { detail?: string; stage?: string };
            setError({ detail: d.detail ?? "Server error" });
            setMessages((prev) =>
              appendPart(prev, asstMsg.id, {
                kind: "text",
                body: `_Error: ${d.detail ?? "Server error"}${
                  d.stage ? ` (${d.stage})` : ""
                }_`,
              }),
            );
            break;
          } else if (ev.event === "done") {
            break;
          }
        }
      } catch (e) {
        if (e instanceof ApiError) {
          setError({ status: e.status, detail: e.detail });
        } else {
          setError({ detail: String(e) });
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [messages, isStreaming],
  );

  return { messages, isStreaming, error, send, reset };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Append (or merge) ``part`` into the assistant message identified by
 * ``messageId``.
 *
 * Special handling for ``tool_call`` parts: when a part arrives with the
 * same ``call_id`` as an existing one (the typical running → success/
 * failed update), we REPLACE the existing entry instead of appending.
 * That way one tool call shows as one ToolCallCard that updates in
 * place, instead of two cards (one running, one done).
 */
function appendPart(
  messages: ChatMessage[],
  messageId: string,
  part: MessagePart,
): ChatMessage[] {
  return messages.map((m) => {
    if (m.id !== messageId) return m;
    if (part.kind === "tool_call") {
      const incoming = part as ToolCallPart;
      const idx = m.parts.findIndex(
        (p) => p.kind === "tool_call" && (p as ToolCallPart).call_id === incoming.call_id,
      );
      if (idx >= 0) {
        const next = m.parts.slice();
        next[idx] = incoming;
        return { ...m, parts: next };
      }
    }
    return { ...m, parts: [...m.parts, part] };
  });
}

/**
 * Flatten the rendered message log to the wire-format history the
 * backend expects. Only ``text`` parts are sent — tool-call parts are
 * the model's own scratchpad and reconstructing them from prior turns
 * isn't useful (Gemini also doesn't need them; it has its own
 * function-call/response replay if needed).
 */
function messagesToHistory(messages: ChatMessage[]): HistoryMessage[] {
  const out: HistoryMessage[] = [];
  for (const m of messages) {
    const textParts = m.parts
      .filter((p) => p.kind === "text")
      .map((p) => (p as { body: string }).body);
    if (textParts.length === 0) continue;
    out.push({ role: m.role, text: textParts.join("\n\n") });
  }
  return out;
}
