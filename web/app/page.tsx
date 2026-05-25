"use client";

import * as React from "react";
import { TopBar } from "@/components/shell/top-bar";
import { Composer } from "@/components/chat/composer";
import { MessageRow } from "@/components/chat/message-row";
import { MessagePartView } from "@/components/chat/message-part-view";
import { ArtifactPane } from "@/components/artifacts/artifact-pane";
import { DayTemplateArtifact } from "@/components/artifacts/day-template-artifact";
import { OnboardingArtifact } from "@/components/artifacts/onboarding-artifact";
import { SecureCaptureModal } from "@/components/artifacts/secure-capture-modal";
import { useChat } from "@/lib/use-chat";
import type {
  ArtifactKind,
  DayTemplateArtifact as DayTemplateData,
  OnboardingArtifact as OnboardingArtifactData,
} from "@/lib/types";

/**
 * ChAAMP home — the live chat workspace.
 *
 * Streams from the Python sidecar via the ``useChat`` hook. Each user
 * send POSTs ``/api/chat/message`` with the full prior history (the
 * server is stateless); the SSE response feeds parts into the message
 * log as they arrive.
 *
 * Two contextual surfaces drive in from the chat:
 *   - ``ArtifactPill`` parts open the right-side ArtifactPane.
 *   - ``SecureCaptureCard`` parts (the LLM emits these when it needs a
 *     credential) open the SecureCaptureModal.
 *
 * Both are managed at this layer so the chat hook stays focused on
 * messages.
 */
export default function HomePage() {
  const { messages, isStreaming, error, tokenTotals, send } = useChat(
    "Hi — I'm ChAAMP. Tell me what you'd like to change about your schedule, " +
      "or ask me about your devices. I'll show you the diff before I apply " +
      "anything.",
  );

  // Artifact pane state. ``null`` means the pane is closed.
  const [artifact, setArtifact] = React.useState<{
    artifact: ArtifactKind;
    key: string;
  } | null>(null);

  // Secure-capture modal state.
  const [capture, setCapture] = React.useState<{
    credentialKey: string;
  } | null>(null);

  // Auto-scroll the chat to the bottom whenever a new part lands.
  const scrollRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-surface">
      <TopBar
        siteName="Lincoln Middle School"
        serverStatus="reachable"
        userInitials="MR"
        userName="Maya Rivera"
        userRole="Admin · Lincoln MS"
        tokenTotals={tokenTotals}
      />

      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Chat column */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
          <main ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
            <div className="w-full max-w-[820px] mx-auto px-6 pt-6 pb-4">
              {messages.map((m) => (
                <MessageRow
                  key={m.id}
                  role={m.role}
                  userInitials="MR"
                  timestamp={formatTimestamp(m.ts)}
                >
                  {m.parts.length === 0 && m.role === "assistant" && isStreaming ? (
                    <div className="flex items-center gap-2 text-13 text-slate-500">
                      <span className="block w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent animate-spin" />
                      <span>Thinking…</span>
                    </div>
                  ) : (
                    m.parts.map((part, i) => (
                      <MessagePartView
                        key={i}
                        part={part}
                        artifactActive={artifact}
                        onOpenArtifact={(kind, key) =>
                          setArtifact({ artifact: kind as ArtifactKind, key })
                        }
                        onOpenCapture={(credentialKey) =>
                          setCapture({ credentialKey })
                        }
                      />
                    ))
                  )}
                </MessageRow>
              ))}

              {/* Standalone error banner if the stream itself failed
                  (vs an in-conversation error which renders as a text
                  part inside the last assistant message). */}
              {error && (
                <div className="my-4 px-3.5 py-2.5 rounded-3 border border-critical/30 bg-critical-soft">
                  <div className="text-13 font-semibold text-critical">
                    Connection error
                    {error.status !== undefined && (
                      <span className="mono ml-2 text-12 font-medium text-slate-500">
                        HTTP {error.status}
                      </span>
                    )}
                  </div>
                  <div className="text-[12.5px] text-slate-700 mt-0.5">
                    {error.detail}
                  </div>
                  <div className="text-[11.5px] text-slate-500 mt-1.5">
                    Is{" "}
                    <code className="mono bg-card px-1.5 py-0.5 rounded border border-slate-200">
                      aamp-server
                    </code>{" "}
                    running in another terminal?
                  </div>
                </div>
              )}
            </div>
          </main>

          {/* Composer — pinned to the bottom of the chat column. */}
          <div className="shrink-0 border-t border-slate-200 bg-surface">
            <Composer
              contextChips={["Lincoln MS", "This week", "12 devices · 4 zones"]}
              suggestions={[
                "What's on the schedule for next Wednesday?",
                "Add a fire drill at 2 PM next Tuesday",
                "Onboard the new speaker at 192.168.1.123",
              ]}
              onSend={(text) => void send(text)}
            />
          </div>
        </div>

        {/* Artifact pane — opens on demand */}
        {artifact && (
          <ArtifactPane
            kind={artifact.artifact}
            title={artifactTitle(artifact)}
            onClose={() => setArtifact(null)}
          >
            {artifact.artifact === "day_template" && (
              <DayTemplateArtifact data={demoDayTemplate(artifact.key)} />
            )}
            {artifact.artifact === "onboarding" && (
              <OnboardingArtifact data={demoOnboarding(artifact.key)} />
            )}
            {artifact.artifact === "discovery" && (
              <div className="text-13 text-slate-500">
                <em>
                  Discovery artifact renderer is not yet built. Add a
                  component under <code className="mono">components/artifacts/</code>
                  and wire it in here.
                </em>
              </div>
            )}
          </ArtifactPane>
        )}
      </div>

      {/* Secure-capture modal */}
      <SecureCaptureModal
        open={capture !== null}
        onOpenChange={(open) => {
          if (!open) setCapture(null);
        }}
        credentialKey={capture?.credentialKey}
        onCaptured={() => {
          // The next chat send will pick the new value up from the
          // server's credential store; nothing client-side to do.
          setCapture(null);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function artifactTitle(a: { artifact: ArtifactKind; key: string }): string {
  // Once real artifact data flows from the server this lookup will use
  // the actual title. For now we synthesize a placeholder.
  if (a.artifact === "day_template") return a.key || "Day template";
  if (a.artifact === "onboarding") return a.key || "Device onboarding";
  return a.key || a.artifact;
}

/**
 * Stand-in until real artifact data flows from the server (the
 * artifact_pill part currently carries only ``key``, not the full
 * payload). When the backend extends ``ArtifactPillPart`` with a
 * ``data`` field, replace these stand-ins with a lookup against
 * received data.
 */
function demoOnboarding(key: string): OnboardingArtifactData {
  return {
    kind: "onboarding",
    ip: key || "192.168.1.123",
    model: "C1710",
    mac: "E8:27:25:09:59:C6",
    arch: "aarch64",
    firmware: "12.9.57",
    classification: "audio:speaker",
    steps: [
      { name: "Inspect device", status: "success", detail: "C1710 fw 12.9.57; factory-default", duration_ms: 620 },
      { name: "Authenticate", status: "success", detail: "Created root user with fleet password", duration_ms: 480 },
      { name: "Install ACAP", status: "running", detail: "Uploading AXIS_Audio_Manager_Pro_5_1_34_aarch64.eap…" },
      { name: "Point at AAM Pro", status: "pending" },
    ],
  };
}

function demoDayTemplate(key: string): DayTemplateData {
  return {
    kind: "day_template",
    title: key || "Day template (demo)",
    recurrence: "Weekly",
    events: [
      { time: "08:00", label: "First bell", destination: "Elementary", tone: "regular" },
      { time: "08:55", label: "Period 1 end (passing)", destination: "Elementary", tone: "regular" },
      { time: "12:00", label: "Lunch chime", destination: "Cafeteria", tone: "announce" },
      { time: "14:30", label: "Dismissal", destination: "All zones", tone: "regular" },
    ],
  };
}
