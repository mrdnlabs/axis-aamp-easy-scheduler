import { TopBar } from "@/components/shell/top-bar";
import { Composer } from "@/components/chat/composer";
import { MessageRow } from "@/components/chat/message-row";

/**
 * The default route — ChAAMP's chat workspace.
 *
 * This first-pass page is intentionally static: TopBar + Chat column +
 * Composer with a short demo conversation. No LLM, no tool calls yet —
 * the goal is to land the visual rhythm and verify the design tokens
 * before wiring real data.
 *
 * Per the handoff README, the recommended next implementation steps are:
 *   1. ✓ Shell — topbar + chat column + composer  (this file)
 *   2. Wire one tool call end-to-end so ToolCallCard renders from real data
 *   3. Build the secure-credential capture loop with a stub backend
 *   4. Build PipelineCard + streaming onboarding tool
 *   5. Add the artifact pane with one type (DayTemplateArtifact)
 *   6. Add ScheduleDiffCard + ApplyConfirmCard + stage/apply/discard
 *   7. Add the other artifact types + Credentials/Audit/Settings sub-views
 */
export default function HomePage() {
  return (
    <div className="min-h-screen flex flex-col">
      <TopBar
        siteName="Lincoln Middle School"
        serverStatus="reachable"
        userInitials="MR"
        userName="Maya Rivera"
        userRole="Admin · Lincoln MS"
      />

      <main className="flex-1 overflow-y-auto">
        <div className="w-full max-w-[820px] mx-auto px-6 pt-6">
          <MessageRow role="assistant" timestamp="11:42 AM">
            <p>
              Hi Maya — welcome back. Today is <strong>Friday, May 22</strong>.
              Your <em>Regular school day</em> template is active for Lincoln MS,
              with the warning bell at 8:25 AM and dismissal at 2:30 PM. Nothing
              has misfired this morning.
            </p>
            <p>
              I can help you adjust the schedule, set up a one-off announcement,
              or onboard a new speaker. What would you like to do?
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
              Got it — I&apos;ll stage a <strong>late-start Wednesday</strong>{" "}
              template that mirrors your regular day but shifts every event 90
              minutes later, applied only on Wednesdays from{" "}
              <span className="mono text-[13.5px]">2026-05-27</span> through{" "}
              <span className="mono text-[13.5px]">2026-06-11</span>.
            </p>
            <p className="text-slate-500 text-[13.5px]">
              <em>
                When the rest of the chat surface is wired (ToolCallCard,
                ScheduleDiffCard, ApplyConfirmCard), the diff and apply controls
                will appear here. For now this is a static demo.
              </em>
            </p>
          </MessageRow>
        </div>
      </main>

      <Composer
        contextChips={["Lincoln MS", "This week", "12 devices · 4 zones"]}
        suggestions={[
          "What&apos;s on the schedule for next Wednesday?",
          "Add a fire drill at 2 PM next Tuesday",
          "Onboard the new speaker at 192.168.1.123",
        ]}
      />
    </div>
  );
}
