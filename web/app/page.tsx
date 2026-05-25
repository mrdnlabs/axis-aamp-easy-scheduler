"use client";

import * as React from "react";
import { TopBar } from "@/components/shell/top-bar";
import { Composer } from "@/components/chat/composer";
import { MessageRow } from "@/components/chat/message-row";
import { ToolCallCard } from "@/components/chat/tool-call-card";
import { PipelineCard } from "@/components/chat/pipeline-card";
import { ScheduleDiffCard } from "@/components/chat/schedule-diff-card";
import { ApplyConfirmCard } from "@/components/chat/apply-confirm-card";
import { SecureCaptureCard } from "@/components/chat/secure-capture-card";
import { ArtifactPill } from "@/components/chat/artifact-pill";
import { ArtifactPane } from "@/components/artifacts/artifact-pane";
import { DayTemplateArtifact } from "@/components/artifacts/day-template-artifact";
import type { DayTemplateArtifact as DayTemplateData } from "@/lib/types";

/**
 * The default route — ChAAMP's chat workspace.
 *
 * Static demo content. No LLM, no tool calls yet — every widget is
 * hand-fed sample data so we can land the visual rhythm before wiring
 * real streams. Per the handoff README's recommended order, the next
 * implementation step is to wire one real MCP tool call end-to-end so
 * the ToolCallCard renders from live data.
 */
export default function HomePage() {
  // Toggle the artifact pane to show/hide the right column. In a real
  // implementation the assistant emits an artifact reference and this
  // state lives at the app level; for the demo we control it locally.
  const [showArtifact, setShowArtifact] = React.useState<boolean>(true);

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar
        siteName="Lincoln Middle School"
        serverStatus="reachable"
        userInitials="MR"
        userName="Maya Rivera"
        userRole="Admin · Lincoln MS"
      />

      <div className="flex-1 flex min-h-0">
        {/* Chat column — full width when artifact pane is closed */}
        <div className="flex-1 flex flex-col min-w-0">
          <main className="flex-1 overflow-y-auto">
            <div className="w-full max-w-[820px] mx-auto px-6 pt-6">
              <DemoConversation
                onOpenArtifact={() => setShowArtifact(true)}
                artifactActive={showArtifact}
              />
            </div>
          </main>

          <Composer
            contextChips={["Lincoln MS", "This week", "12 devices · 4 zones"]}
            suggestions={[
              "What's on the schedule for next Wednesday?",
              "Add a fire drill at 2 PM next Tuesday",
              "Onboard the new speaker at 192.168.1.123",
            ]}
          />
        </div>

        {/* Artifact pane — right-side panel */}
        {showArtifact && (
          <ArtifactPane
            kind="day_template"
            title="Late-start Wednesday"
            onClose={() => setShowArtifact(false)}
          >
            <DayTemplateArtifact data={DEMO_DAY_TEMPLATE} />
          </ArtifactPane>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Demo content — replaced by real LLM-streamed data later
// ---------------------------------------------------------------------------

function DemoConversation({
  onOpenArtifact,
  artifactActive,
}: {
  onOpenArtifact: () => void;
  artifactActive: boolean;
}) {
  return (
    <>
      <MessageRow role="assistant" timestamp="11:42 AM">
        <p>
          Hi Maya — welcome back. Today is <strong>Friday, May 22</strong>. Your{" "}
          <em>Regular school day</em> template is active for Lincoln MS, with
          the warning bell at 8:25 AM and dismissal at 2:30 PM. Nothing has
          misfired this morning.
        </p>
        <p>
          I can help you adjust the schedule, set up a one-off announcement, or
          onboard a new speaker. What would you like to do?
        </p>
      </MessageRow>

      <MessageRow role="user" userInitials="MR" timestamp="11:43 AM">
        <p>
          We&apos;re moving to late-start Wednesdays through June 11. First
          bell shifts to 9:30 instead of 8:00; everything else shifts by the
          same 90 minutes.
        </p>
      </MessageRow>

      <MessageRow role="assistant" timestamp="11:43 AM">
        <p>
          Got it — I&apos;ll build a <strong>Late-start Wednesday</strong>{" "}
          template that mirrors your regular day but shifts every event by 90
          minutes, applied only on Wednesdays from{" "}
          <span className="mono text-[13.5px]">2026-05-27</span> through{" "}
          <span className="mono text-[13.5px]">2026-06-11</span>. Let me stage
          that for you.
        </p>

        <ToolCallCard
          call_id="tc_1"
          name="stage_schedule_change"
          summary='Created template "Late-start Wednesday" with 6 shifted events'
          status="success"
          duration_ms={840}
          args={JSON.stringify(
            {
              template: "late_start_wednesday",
              base: "regular_school_day",
              shift_minutes: 90,
              recurrence: { days: ["Wed"], from: "2026-05-27", to: "2026-06-11" },
            },
            null,
            2,
          )}
          result='{"staging_id": "stg_a4f2", "summary": "6 changes staged: 1 add, 5 shifts"}'
        />

        <ScheduleDiffCard
          title="Late-start Wednesdays"
          effective="May 27 to June 11"
          changes={[
            { kind: "add", label: "Late-start Wednesday template", detail: "Active Wednesdays from May 27", time: "—", destination: "All" },
            { kind: "shift", label: "Period 1 start", detail: "From 08:00 → 09:30 (Wed only)", time: "09:30", destination: "Elementary" },
            { kind: "shift", label: "Period 1 end / passing", detail: "From 08:55 → 10:25", time: "10:25", destination: "Elementary" },
            { kind: "shift", label: "Period 2 start", detail: "From 09:00 → 10:30", time: "10:30", destination: "Elementary" },
            { kind: "shift", label: "Lunch chime", detail: "From 11:30 → 13:00", time: "13:00", destination: "Cafeteria" },
            { kind: "shift", label: "Dismissal", detail: "From 14:30 → 16:00", time: "16:00", destination: "All" },
          ]}
        />

        <p className="text-13 text-slate-600">
          Want to see the full late-start day timeline?
        </p>

        <ArtifactPill
          artifact="day_template"
          title="Late-start Wednesday timeline"
          subtitle="6 events · Wed 2026-05-27 to 2026-06-11"
          active={artifactActive}
          onClick={onOpenArtifact}
        />
      </MessageRow>

      <MessageRow role="user" userInitials="MR" timestamp="11:45 AM">
        <p>
          Looks right. Also, can you onboard the new speaker that arrived this
          morning? It&apos;s at 192.168.1.123.
        </p>
      </MessageRow>

      <MessageRow role="assistant" timestamp="11:45 AM">
        <p>I&apos;ll run the four-step onboarding pipeline against it.</p>

        <PipelineCard
          title="Onboarding 192.168.1.123"
          steps={[
            { name: "Inspect device", status: "success", detail: "AXIS C1710, fw 12.9.57, factory-default", duration_ms: 620 },
            { name: "Authenticate", status: "success", detail: "Created root user with fleet password", duration_ms: 480 },
            { name: "Install ACAP", status: "running", detail: "Uploading AXIS_Audio_Manager_Pro_5_1_34_aarch64.eap (1.2 MB)…" },
            { name: "Point at AAM Pro", status: "pending" },
          ]}
        />
      </MessageRow>

      <MessageRow role="user" userInitials="MR" timestamp="11:46 AM">
        <p>
          Wait — I haven&apos;t configured the device fleet password yet. Can
          you set one up?
        </p>
      </MessageRow>

      <MessageRow role="assistant" timestamp="11:46 AM">
        <p>
          Sure — I&apos;ll prepare a secure capture for the fleet password.
          The value goes straight to Windows Credential Manager; I never see
          it.
        </p>

        <SecureCaptureCard
          key="device/default_password"
          description="This is the password I'll set on every freshly-provisioned Axis device, and try first when authenticating against existing ones."
        />

        <p className="text-13 text-slate-600 mt-1">
          Once it&apos;s captured, I&apos;ll retry the onboarding from where it
          left off.
        </p>
      </MessageRow>

      <MessageRow role="assistant" timestamp="11:47 AM">
        <p>
          A quick example of the lighter apply-confirm pattern — when there&apos;s
          only one change pending and the diff is obvious:
        </p>
        <ApplyConfirmCard
          count={1}
          summary="Set the Lincoln MS warning bell to start at 8:20 instead of 8:25"
        />
      </MessageRow>

      <div className="time-axis my-2" aria-hidden="true" />
    </>
  );
}

const DEMO_DAY_TEMPLATE: DayTemplateData = {
  kind: "day_template",
  title: "Late-start Wednesday",
  recurrence: "Weekly · Wed (May 27 → June 11)",
  pending_changes: 6,
  staging_id: "stg_a4f2",
  events: [
    { time: "09:30", label: "Period 1 start", destination: "Elementary classrooms", tone: "staged_shifted" },
    { time: "10:25", label: "Period 1 end (5-min passing)", destination: "Elementary classrooms", tone: "staged_shifted" },
    { time: "10:30", label: "Period 2 start", destination: "Elementary classrooms", tone: "staged_shifted" },
    { time: "11:25", label: "Period 2 end (5-min passing)", destination: "Elementary classrooms", tone: "staged_shifted" },
    { time: "11:30", label: "Period 3 start", destination: "Elementary classrooms", tone: "staged_shifted" },
    { time: "13:00", label: "Lunch chime", destination: "Cafeteria", tone: "announce" },
    { time: "16:00", label: "Dismissal", destination: "All zones", tone: "staged_shifted" },
  ],
};
