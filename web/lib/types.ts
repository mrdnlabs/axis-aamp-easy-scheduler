/**
 * ChAAMP chat protocol — message + content-part types.
 *
 * This is the contract between the Python chat backend and the Next.js
 * web client. Once the backend HTTP/SSE endpoint is implemented, every
 * event streamed from server to browser will match one of these shapes.
 *
 * The shapes deliberately mirror the design-handoff component contracts:
 * `tool_call` → ToolCallCard, `pipeline` → PipelineCard, etc. Adding a
 * new chat-inline widget means (1) adding a discriminator here, (2) adding
 * a renderer in the message-parts dispatcher, (3) emitting the new shape
 * from the backend.
 */

// ---------------------------------------------------------------------------
// Tool-call statuses
// ---------------------------------------------------------------------------

export type ToolStatus = "running" | "success" | "failed";

// ---------------------------------------------------------------------------
// Message-part variants (the discriminated union)
// ---------------------------------------------------------------------------

/** Plain markdown / prose. */
export interface TextPart {
  kind: "text";
  /** Raw markdown. The renderer is responsible for safe rendering. */
  body: string;
}

/** A single tool invocation rendered as a ToolCallCard. */
export interface ToolCallPart {
  kind: "tool_call";
  /** Stable id from the backend (e.g. for streaming arg / result updates). */
  call_id: string;
  /** Canonical tool name as exposed via MCP. */
  name: string;
  /** One-line summary the LLM emits alongside the call. */
  summary: string;
  status: ToolStatus;
  /** JSON-stringified args (post-scrub). */
  args?: string;
  /** Whatever the tool returned. May be markdown. */
  result?: string;
  /** Wall-clock duration in ms, populated on completion. */
  duration_ms?: number;
}

/** A multi-step tool whose steps stream in. Rendered as one PipelineCard. */
export interface PipelinePart {
  kind: "pipeline";
  pipeline_id: string;
  title: string;
  steps: PipelineStep[];
}

export interface PipelineStep {
  name: string;
  status: ToolStatus | "pending";
  detail?: string;
  duration_ms?: number;
}

/** A staged set of schedule changes, ready for review. */
export interface ScheduleDiffPart {
  kind: "schedule_diff";
  staging_id: string;
  /** "Late-start Wednesdays" or similar. */
  title: string;
  /** Human-readable date range — "May 27 to June 11". */
  effective: string;
  changes: ScheduleChange[];
}

export type ChangeKind = "add" | "shift" | "delete";

export interface ScheduleChange {
  kind: ChangeKind;
  /** "Period 1 bell" — what the change is about. */
  label: string;
  /** Plain-language description of the change. */
  detail: string;
  /** Optional time-of-day (mono) for context. */
  time?: string;
  /** Optional destination chip ("Elementary", "Gym", etc.). */
  destination?: string;
}

/** A simpler one-line "ready to apply" prompt. */
export interface ApplyConfirmPart {
  kind: "apply_confirm";
  staging_id: string;
  summary: string;
  /** Number of changes pending. */
  count: number;
}

/** A credential the assistant needs the user to capture (out of context). */
export interface SecureCapturePart {
  kind: "secure_capture";
  /**
   * account_id/field — e.g. "device/default_password".
   *
   * NOTE: This field is named ``credential_key``, not ``key``, because
   * ``key`` is reserved by React's reconciler — it would never reach the
   * SecureCaptureCard component. The wire protocol uses the same name
   * as the React prop for consistency.
   */
  credential_key: string;
  /** Plain-language description ("Fleet password set on new devices…"). */
  description: string;
  /** Set true once a capture event has fired this session. */
  captured?: boolean;
  /** True when the user accidentally pasted a value in chat — show the warning. */
  denied_because_value_offered?: boolean;
}

/** A pill suggesting the user open a richer view in the right-side artifact pane. */
export interface ArtifactPillPart {
  kind: "artifact_pill";
  /** Artifact kind — drives which component the pane renders. */
  artifact: "day_template" | "onboarding" | "discovery";
  /** Opaque key passed to the renderer to identify the specific artifact. */
  key: string;
  title: string;
  subtitle?: string;
  /**
   * Optional inline payload. When present, the pane renders directly
   * from this; when absent, the renderer falls back to demo data (or
   * shows a "no data yet" placeholder).
   *
   * Re-emitting a pill with the same ``(artifact, key)`` and updated
   * ``data`` is how the server streams live updates into an artifact
   * the user already has open (e.g. an onboarding pipeline advancing
   * step by step).
   */
  data?: DayTemplateArtifact | OnboardingArtifact | DiscoveryArtifact;
}

export type MessagePart =
  | TextPart
  | ToolCallPart
  | PipelinePart
  | ScheduleDiffPart
  | ApplyConfirmPart
  | SecureCapturePart
  | ArtifactPillPart;

// ---------------------------------------------------------------------------
// Full message
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  /** ISO timestamp. */
  ts: string;
  parts: MessagePart[];
}

// ---------------------------------------------------------------------------
// Artifact pane content
// ---------------------------------------------------------------------------

export type ArtifactKind = "day_template" | "onboarding" | "discovery";

export interface DayTemplateArtifact {
  kind: "day_template";
  title: string;
  /** "Weekly · Wed", "Mon Wed Fri", etc. */
  recurrence: string;
  /** Staged-changes count if this artifact has pending edits. */
  pending_changes?: number;
  staging_id?: string;
  events: DayTemplateEvent[];
}

export interface DayTemplateEvent {
  time: string;
  label: string;
  destination?: string;
  /** "regular" / "announce" / "staged_new" / "staged_shifted". */
  tone: "regular" | "announce" | "staged_new" | "staged_shifted";
}

export interface OnboardingArtifact {
  kind: "onboarding";
  ip: string;
  /** "C1110-E" — populated once identified. */
  model?: string;
  mac?: string;
  arch?: string;
  firmware?: string;
  classification?: string;
  steps: PipelineStep[];
}

/** Result of a multi-protocol LAN discovery sweep. */
export interface DiscoveryArtifact {
  kind: "discovery";
  /** Per-protocol stats — what each method contributed. */
  methods: DiscoveryMethodResult[];
  /** Merged unique-device list, sorted by IP. */
  devices: DiscoveredDevice[];
  /** Wall-clock duration of the run, seconds. */
  total_seconds?: number;
}

export interface DiscoveryMethodResult {
  /** "mdns" / "ssdp" / "ws-discovery" / "http-sweep" / "arp" */
  name: string;
  devices_found: number;
  seconds: number;
  error?: string;
}

export interface DiscoveredDevice {
  ip: string;
  mac?: string;
  model?: string;
  /** "audio" / "audio?" / "non-audio" / "aam-pro-server" / "unknown" */
  device_class: string;
  audio_subtype?: string;
  /** "+" delimited list of methods that found this device. */
  sources: string;
}

export type Artifact = DayTemplateArtifact | OnboardingArtifact | DiscoveryArtifact;
