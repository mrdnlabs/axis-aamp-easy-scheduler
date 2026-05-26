"use client";

import * as React from "react";
import { TopBar } from "@/components/shell/top-bar";
import { Composer } from "@/components/chat/composer";
import { MessageRow } from "@/components/chat/message-row";
import { MessagePartView } from "@/components/chat/message-part-view";
import { ArtifactPane } from "@/components/artifacts/artifact-pane";
import { DayTemplateArtifact } from "@/components/artifacts/day-template-artifact";
import { OnboardingArtifact } from "@/components/artifacts/onboarding-artifact";
import { DiscoveryArtifact } from "@/components/artifacts/discovery-artifact";
import { SecureCaptureModal } from "@/components/artifacts/secure-capture-modal";
import { GeminiSetupCard } from "@/components/setup/gemini-setup-card";
import { SettingsPanel } from "@/components/panels/settings-panel";
import { CredentialsPanel } from "@/components/panels/credentials-panel";
import { AuditLogPanel } from "@/components/panels/audit-log-panel";
import { AccessDeniedScreen } from "@/components/auth/access-denied-screen";
import { useChat, artifactStoreKey } from "@/lib/use-chat";
import { useConfigStatus } from "@/lib/use-config-status";
import { useSiteOverview } from "@/lib/use-site-overview";
import { useCurrentUser } from "@/lib/use-current-user";
import type { ArtifactKind } from "@/lib/types";

type PanelKind = "settings" | "credentials" | "audit";

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
  // Auth gate runs first — if the connecting Windows user isn't an
  // admin (or peer identification failed), the access-denied screen
  // takes over the whole viewport and the chat hook never even runs.
  const { user, isLoading: userLoading } = useCurrentUser();

  const { messages, isStreaming, error, tokenTotals, artifacts, send } = useChat(
    "Hi — I'm ChAAMP. Tell me what you'd like to change about your schedule, " +
      "or ask me about your devices. I'll show you the diff before I apply " +
      "anything.",
  );

  // Server-reported credential rollup. When the Gemini key is missing
  // we hide the chat workspace entirely and show a centered setup view
  // — see the render block below.
  const { status: configStatus, isLoading: configLoading, refresh: refreshConfig } =
    useConfigStatus();
  const geminiReady = configStatus?.gemini_configured ?? false;

  // Site-overview drives the TopBar siteName once the user has named
  // the org during intake. Before that, we show "ChAAMP" (handled by
  // the TopBar fallback when siteName is null).
  const { overview: siteOverview, refresh: refreshSiteOverview } = useSiteOverview();

  // Artifact pane state. ``null`` means the pane is closed.
  const [artifact, setArtifact] = React.useState<{
    artifact: ArtifactKind;
    key: string;
  } | null>(null);

  // Secure-capture modal state.
  const [capture, setCapture] = React.useState<{
    credentialKey: string;
  } | null>(null);

  // Which side panel is open (Settings / Credentials / Audit).
  const [openPanel, setOpenPanel] = React.useState<PanelKind | null>(null);

  // Auto-scroll the chat to the bottom whenever a new part lands.
  const scrollRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);

  // When a chat turn ends, the LLM may have patched the intent doc's
  // Description (during the org-intake conversation). Re-fetch the
  // site overview so the TopBar siteName picks up the new value
  // without a manual refresh. Cheap call; only runs on turn-end edges.
  const wasStreamingRef = React.useRef(false);
  React.useEffect(() => {
    if (wasStreamingRef.current && !isStreaming) {
      void refreshSiteOverview();
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming, refreshSiteOverview]);

  // Auth-gate the entire app. Before we know who the user is we
  // render nothing (very brief flash on cold load). If we learn the
  // user is not admin OR identification failed, take over the whole
  // viewport with the access-denied screen. Only admins fall through
  // to the chat workspace + setup gate.
  if (userLoading) {
    return <div className="h-screen bg-surface" aria-busy="true" />;
  }
  if (!user || !user.is_admin) {
    return <AccessDeniedScreen user={user} />;
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-surface">
      <TopBar
        siteName={siteOverview?.site_label ?? null}
        serverStatus="reachable"
        tokenTotals={tokenTotals}
        username={user.username}
        onNavigate={(route) => setOpenPanel(route)}
      />

      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Chat column */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
          {/* Setup gate — when the server reports no Gemini key we REPLACE
              the chat workspace with a centered setup view. Welcome
              message, message log, and composer are all hidden so the
              key-setup card is unmissable.

              Render-state matrix:
                configLoading        → tiny spinner (sub-100ms typically)
                !configLoading & !geminiReady → hero setup card
                geminiReady          → full chat workspace */}
          {configLoading ? (
            <div className="flex-1 flex items-center justify-center text-13 text-slate-500">
              <span className="inline-flex items-center gap-2">
                <span className="block w-3.5 h-3.5 rounded-full border-[1.5px] border-accent border-t-transparent animate-spin" />
                Checking configuration…
              </span>
            </div>
          ) : !geminiReady ? (
            <div className="flex-1 min-h-0 overflow-y-auto">
              <div className="min-h-full flex items-center justify-center px-6 py-12">
                <div className="w-full max-w-[640px]">
                  <GeminiSetupCard
                    onSetUp={() => setCapture({ credentialKey: "gemini/api_key" })}
                    size="hero"
                  />
                </div>
              </div>
            </div>
          ) : (
          <>
          <main ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
            <div className="w-full max-w-[820px] mx-auto px-6 pt-6 pb-4">
              {messages.map((m) => (
                <MessageRow
                  key={m.id}
                  role={m.role}
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
                        onStagingAction={(action, stagingId) => {
                          // Inject a synthetic user message so the LLM
                          // dispatches the right MCP tool. We include
                          // the staging_id verbatim so the model has
                          // no ambiguity about which change-set the
                          // user clicked on. The same SSE pipeline
                          // narrates the outcome.
                          const verb =
                            action === "apply" ? "Apply" : "Discard";
                          void send(
                            `${verb} the staged changes (staging_id: ${stagingId}).`,
                          );
                        }}
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

          {/* Composer — pinned to the bottom of the chat column.
              Only rendered once Gemini is configured; the setup view
              above stands in for it otherwise. Context chips and
              suggestions are intentionally left as empty arrays —
              they were demo content. Real ones can come back wired
              to live state later. */}
          <div className="shrink-0 border-t border-slate-200 bg-surface">
            <Composer onSend={(text, files) => void send(text, files)} />
          </div>
          </>
          )}
        </div>

        {/* Artifact pane — opens on demand. Data comes from the
            artifact store (server-emitted via emit_artifact_pill).
            Falls back to a demo if the LLM opened the pane without
            sending data. */}
        {artifact && (
          <ArtifactPane
            kind={artifact.artifact}
            title={artifactTitle(artifact)}
            onClose={() => setArtifact(null)}
          >
            {(() => {
              const live = artifacts[artifactStoreKey(artifact)];
              if (artifact.artifact === "day_template") {
                return (
                  <DayTemplateArtifact
                    data={
                      live?.kind === "day_template"
                        ? live
                        : demoDayTemplate(artifact.key)
                    }
                  />
                );
              }
              if (artifact.artifact === "onboarding") {
                return (
                  <OnboardingArtifact
                    data={
                      live?.kind === "onboarding"
                        ? live
                        : demoOnboarding(artifact.key)
                    }
                  />
                );
              }
              if (artifact.artifact === "discovery") {
                return live?.kind === "discovery" ? (
                  <DiscoveryArtifact data={live} />
                ) : (
                  <DiscoveryEmpty />
                );
              }
              return null;
            })()}
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
        onCaptured={(info) => {
          // The next chat send will pick the new value up from the
          // server's credential store. We also refresh the config
          // status so the setup card disappears and the composer
          // un-gates — particularly important for ``gemini/api_key``.
          setCapture(null);
          if (info.account_id === "gemini") void refreshConfig();
        }}
      />

      {/* Side panels — at most one open at a time. */}
      <SettingsPanel
        open={openPanel === "settings"}
        onOpenChange={(open) => {
          if (!open) setOpenPanel(null);
        }}
      />
      <CredentialsPanel
        open={openPanel === "credentials"}
        onOpenChange={(open) => {
          if (!open) setOpenPanel(null);
        }}
        onRotate={(credentialKey) => {
          // Closing the panel before opening the capture modal keeps
          // the z-stack clean — only one dialog at a time. The
          // SecureCaptureModal's ``onCaptured`` callback handles the
          // post-success cleanup; the user can reopen the
          // credentials panel to confirm the rotation landed.
          setOpenPanel(null);
          setCapture({ credentialKey });
        }}
      />
      <AuditLogPanel
        open={openPanel === "audit"}
        onOpenChange={(open) => {
          if (!open) setOpenPanel(null);
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
function demoOnboarding(key: string): import("@/lib/types").OnboardingArtifact {
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

function DiscoveryEmpty() {
  return (
    <div className="text-13 text-slate-500 leading-relaxed">
      <em>
        No discovery data attached to this pill yet. The next sweep will
        populate this view — or ask the assistant to run a fresh
        discovery and surface the result here.
      </em>
    </div>
  );
}

function demoDayTemplate(key: string): import("@/lib/types").DayTemplateArtifact {
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
