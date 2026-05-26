/**
 * Typed API client for the ChAAMP Python sidecar.
 *
 * Routes are proxied through Next.js (see ``next.config.js``) so this
 * code can use relative URLs in both dev and prod. The sidecar lives at
 * ``localhost:7331`` and the rewrite rule maps ``/api/*`` to it.
 *
 * IMPORTANT: the credential-capture endpoints accept a cleartext value
 * over the wire. They are bound to 127.0.0.1 only on the server side;
 * this client must NEVER be invoked from a non-loopback origin.
 */

// ---------------------------------------------------------------------------
// Config status
// ---------------------------------------------------------------------------

/**
 * Boolean rollup of credential / capability state.
 *
 * The frontend uses ``gemini_configured`` to gate the composer — chat
 * cannot run without a Gemini API key. The other booleans inform softer
 * UX cues (e.g. dim voice features when ElevenLabs isn't set).
 *
 * Only booleans cross the wire — no values, no last-set timestamps.
 */
export interface ConfigStatus {
  gemini_configured: boolean;
  elevenlabs_configured: boolean;
  aamp_configured: boolean;
  device_default_password_configured: boolean;
}

/** Fetch the credential rollup. Safe to call repeatedly. */
export async function getConfigStatus(): Promise<ConfigStatus> {
  const r = await fetch("/api/config/status");
  if (!r.ok) throw await apiError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Settings — non-secret user-tunable knobs
// ---------------------------------------------------------------------------

export type SettingType = "int" | "float" | "bool" | "string" | "json";

export interface SettingView {
  key: string;
  value: unknown;
  default: unknown;
  type: SettingType;
  category: string;
  description: string;
}

export async function getSettings(): Promise<SettingView[]> {
  const r = await fetch("/api/settings");
  if (!r.ok) throw await apiError(r);
  return r.json();
}

/** PUT one setting. Pass ``null`` to reset to default. */
export async function putSetting(key: string, value: unknown): Promise<SettingView> {
  const r = await fetch(`/api/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!r.ok) throw await apiError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Credentials — list only; values never cross the wire
// ---------------------------------------------------------------------------

export interface CredentialSlotView {
  account_id: string;
  field: string;
  description: string;
  env_var: string;
  is_csv_list: boolean;
  stored: boolean;
}

export async function getCredentials(): Promise<CredentialSlotView[]> {
  const r = await fetch("/api/credentials");
  if (!r.ok) throw await apiError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

export interface AuditEntry {
  ts?: string;
  op?: string;
  account_id?: string;
  field?: string;
  principal?: string;
  decision?: string;
  reason?: string;
  extra: Record<string, unknown>;
}

export interface AuditQuery {
  limit?: number;
  op?: string;
  principal?: string;
}

export async function getAudit(q: AuditQuery = {}): Promise<AuditEntry[]> {
  const params = new URLSearchParams();
  if (q.limit !== undefined) params.set("limit", String(q.limit));
  if (q.op) params.set("op", q.op);
  if (q.principal) params.set("principal", q.principal);
  const qs = params.toString();
  const r = await fetch(`/api/audit${qs ? `?${qs}` : ""}`);
  if (!r.ok) throw await apiError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Site overview — used to un-hardcode the TopBar site name
// ---------------------------------------------------------------------------

export interface SiteOverview {
  site_id: number;
  site_label: string | null;
  headline: string | null;
  source: "intent_doc" | "placeholder" | "missing";
}

export async function getSiteOverview(siteId: number = 1): Promise<SiteOverview> {
  const r = await fetch(`/api/site-overview?site_id=${siteId}`);
  if (!r.ok) throw await apiError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Credential capture
// ---------------------------------------------------------------------------

export interface CaptureStartRequest {
  account_id: string;
  field: string;
}

export interface CaptureStartResponse {
  token: string;
  account_id: string;
  field: string;
  description: string;
  expires_in_seconds: number;
}

export interface CaptureStatusResponse {
  account_id: string;
  field: string;
  description: string;
  expires_in_seconds: number;
}

export interface CaptureSubmitResponse {
  captured: true;
  account_id: string;
  field: string;
}

/**
 * Mint a capture token. Normally the LLM calls this via the MCP tool
 * ``request_credential_capture`` and returns the token to the frontend;
 * this helper is provided for tests and admin-driven flows.
 */
export async function startCapture(
  req: CaptureStartRequest,
): Promise<CaptureStartResponse> {
  const r = await fetch("/api/credential-capture/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw await apiError(r);
  return r.json();
}

/**
 * Fetch the current status of a capture token (account/field/expiry).
 * Used by the SecureCaptureModal to render the countdown when opened
 * with an inherited token.
 */
export async function captureStatus(token: string): Promise<CaptureStatusResponse> {
  const r = await fetch(`/api/credential-capture/${encodeURIComponent(token)}/status`);
  if (!r.ok) throw await apiError(r);
  return r.json();
}

/**
 * Submit a captured credential value. Single-use; the server consumes
 * the token regardless of success. The value flows straight to the OS
 * keyring on the server side; the LLM never sees it.
 */
export async function submitCapture(
  token: string,
  value: string,
): Promise<CaptureSubmitResponse> {
  const r = await fetch(`/api/credential-capture/${encodeURIComponent(token)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!r.ok) throw await apiError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export interface HistoryMessage {
  role: "user" | "assistant";
  text: string;
}

export interface ChatRequest {
  text: string;
  history?: HistoryMessage[];
  session_id?: string;
}

export interface SseEvent<T = unknown> {
  event: string;
  data: T;
}

/**
 * Send a user message and stream back assistant parts via SSE.
 *
 * The backend is **stateless** — the client passes the full chat history
 * on every call. Each yielded event has an ``event`` discriminator and a
 * parsed ``data`` payload:
 *
 *   - ``session`` — once at the start; ``{session_id}``
 *   - ``part``    — one of the MessagePart variants from ``./types.ts``
 *   - ``error``   — fatal error; ``{detail, stage?}``
 *   - ``done``    — turn complete; ``{finish_reason?}``
 *
 * Usage::
 *
 *   for await (const ev of streamChatMessage({text: "hi", history: prior})) {
 *     if (ev.event === "part") appendPart(ev.data as MessagePart);
 *     else if (ev.event === "error") showError((ev.data as any).detail);
 *   }
 *
 * The generator returns when the server emits ``done`` (or the stream
 * closes). Errors during the network call throw an ``ApiError``.
 */
export async function* streamChatMessage(
  req: ChatRequest,
): AsyncGenerator<SseEvent> {
  const r = await fetch("/api/chat/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: req.text,
      history: req.history ?? [],
      session_id: req.session_id,
    }),
  });
  if (!r.ok || !r.body) throw await apiError(r);

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE messages are separated by a blank line.
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const ev = parseSseMessage(raw);
      if (!ev) continue;
      yield ev;
      if (ev.event === "done") return;
    }
  }
}

function parseSseMessage(raw: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(dataStr) };
  } catch {
    return { event, data: dataStr };
  }
}

// ---------------------------------------------------------------------------
// Error envelope
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function apiError(r: Response): Promise<ApiError> {
  let detail = "request failed";
  try {
    const j = (await r.json()) as { detail?: string };
    if (j.detail) detail = j.detail;
  } catch {
    // Body wasn't JSON — use the status text instead.
    detail = r.statusText || detail;
  }
  return new ApiError(r.status, detail);
}
