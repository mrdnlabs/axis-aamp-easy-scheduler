"use client";

import * as React from "react";
import { ToolCallCard } from "@/components/chat/tool-call-card";
import { PipelineCard } from "@/components/chat/pipeline-card";
import { ScheduleDiffCard } from "@/components/chat/schedule-diff-card";
import { ApplyConfirmCard } from "@/components/chat/apply-confirm-card";
import { SecureCaptureCard } from "@/components/chat/secure-capture-card";
import { ArtifactPill } from "@/components/chat/artifact-pill";
import type { MessagePart } from "@/lib/types";

interface MessagePartViewProps {
  part: MessagePart;
  /**
   * Called when the user clicks an ArtifactPill or the "Set securely"
   * button on a SecureCaptureCard. The parent owns the artifact-pane
   * state + the capture-modal open state.
   */
  onOpenArtifact?: (artifact: string, key: string) => void;
  onOpenCapture?: (credentialKey: string) => void;
  /**
   * Called when the user clicks Apply / Discard on a ScheduleDiffCard
   * or ApplyConfirmCard. The parent injects a synthetic user turn so
   * the LLM dispatches ``apply_staged_changes`` / ``discard_staged_changes``
   * — same code path as if the user had typed it.
   */
  onStagingAction?: (action: "apply" | "discard", stagingId: string) => void;
  artifactActive?: { artifact: string; key: string } | null;
}

/**
 * Dispatch on the message-part kind and render the right component.
 *
 * Every MessagePart variant has exactly one renderer. Adding a new
 * variant means: extend the union in lib/types.ts, add a case here,
 * and emit the new shape from the Python backend.
 */
export function MessagePartView({
  part,
  onOpenArtifact,
  onOpenCapture,
  onStagingAction,
  artifactActive,
}: MessagePartViewProps) {
  switch (part.kind) {
    case "text":
      return <RenderText body={part.body} />;

    case "tool_call":
      return (
        <ToolCallCard
          call_id={part.call_id}
          name={part.name}
          summary={part.summary}
          status={part.status}
          args={part.args}
          result={part.result}
          duration_ms={part.duration_ms}
        />
      );

    case "pipeline":
      return <PipelineCard title={part.title} steps={part.steps} />;

    case "schedule_diff":
      return (
        <ScheduleDiffCard
          title={part.title}
          effective={part.effective}
          changes={part.changes}
          onApply={() => onStagingAction?.("apply", part.staging_id)}
          onDiscard={() => onStagingAction?.("discard", part.staging_id)}
        />
      );

    case "apply_confirm":
      return (
        <ApplyConfirmCard
          count={part.count}
          summary={part.summary}
          onApply={() => onStagingAction?.("apply", part.staging_id)}
          onDiscard={() => onStagingAction?.("discard", part.staging_id)}
        />
      );

    case "secure_capture":
      return (
        <SecureCaptureCard
          credentialKey={part.credential_key}
          description={part.description}
          captured={part.captured}
          denied_because_value_offered={part.denied_because_value_offered}
          onSetSecurely={() => onOpenCapture?.(part.credential_key)}
          onCopyCli={() => {
            navigator.clipboard?.writeText(
              `aamp-set-credential ${part.credential_key}`,
            );
          }}
        />
      );

    case "artifact_pill":
      return (
        <ArtifactPill
          artifact={part.artifact}
          title={part.title}
          subtitle={part.subtitle}
          active={
            !!artifactActive &&
            artifactActive.artifact === part.artifact &&
            artifactActive.key === part.key
          }
          onClick={() => onOpenArtifact?.(part.artifact, part.key)}
        />
      );
  }
}

/**
 * Minimal markdown-ish text renderer.
 *
 * Splits on blank lines into paragraphs and runs a few cheap inline
 * substitutions (bold via ``**``, inline code via backticks). Doesn't
 * try to be a full markdown parser — the LLM sticks to a narrow subset
 * in practice, and a real markdown lib would balloon the bundle.
 */
function RenderText({ body }: { body: string }) {
  const paragraphs = body.split(/\n\s*\n/);
  return (
    <>
      {paragraphs.map((p, i) => (
        <p
          key={i}
          className="text-14 leading-[1.6] text-ink"
          dangerouslySetInnerHTML={{ __html: inlineFormat(p) }}
        />
      ))}
    </>
  );
}

function inlineFormat(text: string): string {
  // Order matters: escape first, then apply the inline rules.
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return esc
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(
      /`([^`]+)`/g,
      '<code class="mono text-[13px] bg-slate-100 px-1 py-0.5 rounded">$1</code>',
    )
    .replace(/_([^_]+)_/g, "<em>$1</em>")
    .replace(/\n/g, "<br />");
}
