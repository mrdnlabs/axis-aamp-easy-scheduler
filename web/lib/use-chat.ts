"use client";

import * as React from "react";
import { streamChatMessage, ApiError, type HistoryMessage } from "@/lib/api";
import type {
  Artifact,
  ArtifactPillPart,
  ChatMessage,
  MessagePart,
  ToolCallPart,
} from "@/lib/types";

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
export interface TokenTotals {
  /** Number of completed user turns. */
  turns: number;
  /** Cumulative input tokens across the session. */
  prompt_tokens: number;
  /** Cumulative output tokens across the session. */
  candidates_tokens: number;
  /** Prompt-cache hits — billed at a discount. */
  cached_tokens: number;
  /** Extended-thinking output (only present when enabled). */
  thoughts_tokens: number;
  /** Per-tool overhead — declarations injected into each request. */
  tool_use_prompt_tokens: number;
  /** SDK-reported total. */
  total_tokens: number;
}

export interface UseChatResult {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: { detail: string; status?: number } | null;
  /** Running session totals — accumulated across all sends. */
  tokenTotals: TokenTotals;
  /**
   * Latest known data for every artifact emitted this session, keyed by
   * ``${artifact}:${key}``. Re-emitting a pill with the same key updates
   * in place so an open pane reflects the new state automatically.
   */
  artifacts: Record<string, Artifact>;
  send: (text: string) => Promise<void>;
  reset: () => void;
}

function artifactStoreKey(a: { artifact: string; key: string }): string {
  return `${a.artifact}:${a.key}`;
}

const EMPTY_TOTALS: TokenTotals = {
  turns: 0,
  prompt_tokens: 0,
  candidates_tokens: 0,
  cached_tokens: 0,
  thoughts_tokens: 0,
  tool_use_prompt_tokens: 0,
  total_tokens: 0,
};

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
  const [tokenTotals, setTokenTotals] = React.useState<TokenTotals>(EMPTY_TOTALS);
  const [artifacts, setArtifacts] = React.useState<Record<string, Artifact>>({});

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
    setTokenTotals(EMPTY_TOTALS);
    setArtifacts({});
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
            // If the part is an artifact pill carrying data, also cache
            // the data in the artifact store so the side pane can render
            // from it whenever the user opens it.
            if (part.kind === "artifact_pill") {
              const pp = part as ArtifactPillPart;
              if (pp.data) {
                setArtifacts((prev) => ({
                  ...prev,
                  [artifactStoreKey(pp)]: pp.data!,
                }));
              }
            }
          } else if (ev.event === "usage") {
            // Per-turn usage delta — fold into the running session totals.
            const d = ev.data as { per_turn?: Partial<TokenTotals> };
            const delta = d.per_turn ?? {};
            setTokenTotals((t) => ({
              turns: t.turns + 1,
              prompt_tokens: t.prompt_tokens + (delta.prompt_tokens ?? 0),
              candidates_tokens: t.candidates_tokens + (delta.candidates_tokens ?? 0),
              cached_tokens: t.cached_tokens + (delta.cached_tokens ?? 0),
              thoughts_tokens: t.thoughts_tokens + (delta.thoughts_tokens ?? 0),
              tool_use_prompt_tokens:
                t.tool_use_prompt_tokens + (delta.tool_use_prompt_tokens ?? 0),
              total_tokens: t.total_tokens + (delta.total_tokens ?? 0),
            }));
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

  return { messages, isStreaming, error, tokenTotals, artifacts, send, reset };
}

export { artifactStoreKey };

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
