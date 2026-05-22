# Credential handling

How AampEasyScheduler keeps passwords, API keys, and access tokens out of LLM context, off-disk, and off-screen. This is the architecture reference; for product behavior see `src/aamp/system_prompt.md` (the chat agent's instructions) and the canonical secret table in `src/aamp/credentials.py`.

## Core principle

> The LLM is a planner, not a credential carrier. It passes identifiers (`account_id`, `field`); the server resolves them to secrets at the moment of action. Plaintext secrets never enter the model's context window — not in tool returns, not in tool arguments, not in chat history.

## Architecture

```
┌─────────────────┐     calls onboard_axis_device(ip="...")
│   Chat agent    │ ──────────────────────────────────────────┐
│  (LLM context)  │ ◀── result string (no secrets)           │
└─────────────────┘                                            │
                                                               ▼
                                              ┌────────────────────────────┐
                                              │  MCP tool layer            │
                                              │  (mcp_server.py, onboard.py)│
                                              └─────────────┬──────────────┘
                                                            │ load_config()
                                                            ▼
                                              ┌────────────────────────────┐
                                              │  AampConfig (config.py)    │
                                              │  • non-secret fields       │
                                              │  • secret fields resolve   │
                                              │    via the store ──────────┼─┐
                                              └────────────────────────────┘ │
                                                                             │ get("aamp", "password")
                                                                             ▼
                                              ┌────────────────────────────┐
                                              │  AuditingStore             │ → ~/.aamp_audit.log
                                              │   wraps                    │   (every access logged)
                                              │  ChainedCredentialStore    │
                                              │   ↓                        │
                                              │  ┌──────────────────────┐  │
                                              │  │ KeyringCredentialStore│ │ → Windows Credential Manager
                                              │  │  (writable, primary) │  │
                                              │  └──────────────────────┘  │
                                              │  ┌──────────────────────┐  │
                                              │  │ EnvCredentialStore   │  │ → .aamp_credentials  +
                                              │  │  (read-only fallback)│  │   environment variables
                                              │  └──────────────────────┘  │
                                              └────────────────────────────┘

                              Tool errors / step traces / log writes
                                            ↓
              ┌──────────────────┐     ┌───────────────────┐     ┌──────────────────┐
              │  VAPIX scrubber  │     │  chat_log         │     │  Tool result     │
              │  (device.py)     │     │  Scrubber         │     │  string to LLM   │
              │  scrubs error    │     │  scrubs disk-     │     │  (post-scrub)    │
              │  bodies before   │     │  bound JSONL +    │     │                  │
              │  VapixError      │     │  markdown         │     │                  │
              └──────────────────┘     └───────────────────┘     └──────────────────┘
```

## Canonical secret table

Every secret in the codebase appears in `KNOWN_SECRETS` (`src/aamp/credentials.py`). Add a row there — and only there — when introducing a new secret.

| `account_id` | `field` | Used by | Description |
|---|---|---|---|
| `aamp` | `password` | `config.py`, `auth.py` | AAM Pro admin login |
| `aamp` | `client_secret` | `auth.py` | Pre-registered OAuth client (optional) |
| `device` | `default_password` | `onboard.py`, `device.py` | Fleet password for Axis devices |
| `device` | `password_candidates` | `onboard.py` | CSV list of legacy passwords |
| `elevenlabs` | `api_key` | `voice.py` | Voice generation |

Non-secret fields (host, username, voice_id, etc.) stay in `.aamp_credentials` / env. The store is **for secrets only**.

## 9-pattern checklist

The pattern this implementation follows. Status as of the credential-handling milestone:

| # | Pattern | Status | Notes |
|---|---|---|---|
| 1 | No password-shaped fields in tool schemas | ✅ Implemented | Audited 38 MCP tools — none take or return passwords. |
| 2 | No `get_credentials` tool | ✅ Implemented | Doesn't exist. Documented as non-goal. |
| 3 | Out-of-band capture | ✅ CLI implemented | `aamp-set-credential` uses `getpass()`. Web URL flow deferred. |
| 4 | Per-device short-lived temp creds | ⏸ Deferred | Significant Axis-side complexity; current fleet-password model is acceptable. |
| 5 | Encrypted storage behind an interface | ✅ Implemented | OS keyring backend + chained env fallback. |
| 6 | Fixed-length masking | ✅ Implemented | `"********"` everywhere (configs, CLI, transcripts). Never `*` per character. |
| 7 | Two trust boundaries | ⏸ Deferred | Single principal (`"process"`) for now. Audit log carries the field; web UI will populate `"human:<user>"` and `"llm"`. |
| 8 | Audit every credential access | ✅ Implemented | `~/.aamp_audit.log` JSONL. Get/set/delete/list all logged with decision tag. |
| 9 | Confirmation gates for dangerous ops | ⏸ Out of scope | Separate concern, planned later. |

## Backends

### `KeyringCredentialStore` (default, primary)

Uses the [`keyring`](https://github.com/jaraco/keyring) library to store values in the OS-native credential vault:
- **Windows**: Windows Credential Manager (encrypted by DPAPI)
- **macOS**: Keychain
- **Linux**: libsecret (e.g. GNOME Keyring)

On construction it runs a health-check (writes a sentinel, reads it back, deletes it). If the backend can't persist, raises `RuntimeError` so callers don't silently degrade. Common failure: headless Windows service accounts where Credential Manager isn't available — use `AAMP_CREDENTIAL_BACKEND=env` to fall back.

Listing isn't supported by Windows Credential Manager natively. We maintain a metadata-only index at `~/.aamp_credential_index.json` recording which `(account_id, field)` pairs have been written. The index never contains values.

### `EnvCredentialStore` (read-only fallback)

Reads `.aamp_credentials` (project root, then `~`) and process environment variables. Read-only — writes raise `NotImplementedError`. Exists to keep existing setups working during the keyring transition.

### `ChainedCredentialStore` (the default factory output)

Walks a list of stores on `get`. Writes go to the first writable store (the keyring). The default factory returns `ChainedCredentialStore([keyring, env])` so existing `.aamp_credentials` files Just Work — and `aamp-set-credential` always lands in the keyring.

### `AuditingStore` (wraps any backend)

Decorates any `CredentialStore` and writes a JSONL audit entry for every `get` / `set` / `delete` / `list`. Wrapped by the factory automatically. Disable with `get_credential_store(audit=False)` (tests only).

## Migration steps for existing users

```powershell
# 1. Pull the latest code
git pull && pip install -e .

# 2. Verify the keyring backend works for you
aamp-list-credentials
#   → (no credentials stored)  ← keyring is empty, that's fine

# 3. Migrate from your existing .aamp_credentials
aamp-migrate-credentials
#   → moves each secret to OS keyring
#   → offers to rename .aamp_credentials to .aamp_credentials.bak.<ts>

# 4. Confirm
aamp-list-credentials
#   → aamp/password   = ********
#   → ...etc

# 5. If you ever need to roll back: rename .aamp_credentials.bak.<ts> back
#    to .aamp_credentials. The chained backend will pick it up again.
```

For **fresh installs** (no existing `.aamp_credentials`):

```powershell
aamp-set-credential aamp/password
aamp-set-credential device/default_password    # only if onboarding devices
aamp-set-credential elevenlabs/api_key         # only if using voice
```

Non-secret fields (`AAMP_HOST`, `AAMP_USER`, `AAMP_DEVICE_DEFAULT_USER`, etc.) still go in `.aamp_credentials` or environment variables — see `.aamp_credentials.example`.

## Adding a new secret

Three steps. No others.

1. **Add a row to `KNOWN_SECRETS`** in `src/aamp/credentials.py`:
   ```python
   SecretField("myservice", "api_token", "MYSERVICE_API_TOKEN",
               "Token for the new XYZ integration"),
   ```

2. **Fetch it where you need it**:
   ```python
   from .credentials import get_credential_store
   token = get_credential_store().get("myservice", "api_token")
   if not token:
       raise RuntimeError(
           "Run: aamp-set-credential myservice/api_token"
       )
   ```

3. **Document the row** in this file's canonical-secret-table section above.

The CLI (`aamp-set-credential`, etc.) automatically knows about every entry in `KNOWN_SECRETS` — no extra wiring needed.

## What the chat agent sees

System prompt section (`src/aamp/system_prompt.md`, the **Credential handling** block) instructs the model to:

- Never ask for a password in chat.
- Never echo a password the user offers; respond with the `aamp-set-credential` command instead.
- Relay credential-missing tool errors verbatim — the tool tells the user exactly which command to run.

Tool failure messages from `onboard.py` etc. are crafted to include the literal CLI command. Two scrubber layers protect against accidental leaks:

- **`device.py` VAPIX scrubber** — strips `pwd=...` query-param echoes from VAPIX error bodies before they reach `VapixError → onboard step trace → MCP tool result → LLM`.
- **`chat_log.Scrubber`** — recursively masks every registered secret value in tool args, tool results, user messages, and assistant text before disk write to `logs/chat_*.{jsonl,md}`.

## Threat model

**What this protects against:**
- Plaintext passwords reaching the LLM via tool returns / chat transcripts / system prompts.
- Plaintext passwords in disk-bound chat transcripts even if upstream layers fail.
- Plaintext passwords in version control (the legacy `.aamp_credentials` is gitignored; the migration moves them off-disk).
- Audit gaps — every credential access is recorded with timestamp + decision.

**What this does NOT protect against:**
- A compromised process on the user's machine. Windows Credential Manager is per-user; any code running as the user can read it.
- Credential leakage through device hardware (e.g. logs that the Axis device itself keeps — out of our control).
- Multi-user scenarios. There's only one principal (`"process"`) today. The web UI milestone introduces `"human:<user>"` and `"llm"` distinctions.
- Confirmation gates for destructive operations (e.g. accidental `factory_default()` calls from the chat). That's a separate concern; see the pattern checklist.

## Files

| Path | Role |
|---|---|
| `src/aamp/credentials.py` | Store ABC + backends + canonical table + factory |
| `src/aamp/credentials_cli.py` | `aamp-set-credential`, `-list-credentials`, `-delete-credential`, `-migrate-credentials` |
| `src/aamp/audit.py` | `AuditLog` + `AuditingStore` decorator |
| `src/aamp/config.py` | Reads non-secrets directly, resolves secrets via the store |
| `src/aamp/voice.py` | ElevenLabs key via the store |
| `src/aamp/device.py` | VAPIX error-body scrubber + per-device sensitive-value tracking |
| `src/aamp/chat_log.py` | `Scrubber` + integration into `TranscriptLogger` |
| `src/aamp/chat.py` | Builds the scrubber once at session start from all known secrets |
| `src/aamp/system_prompt.md` | The LLM's "do not handle passwords" instructions |
| `~/.aamp_credential_index.json` | Metadata-only index of what's in keyring (no values) |
| `~/.aamp_audit.log` | Append-only JSONL credential-access log |
