# Authentication

ChAAMP authenticates users via **Windows peer-identity on the loopback
socket**. There is no sign-in form, no password prompt, no session
cookie. You authenticate by being the Windows user who opens the
browser; the sidecar identifies you per-request from the TCP socket
itself.

## The model in one paragraph

The ChAAMP sidecar (`aamp-server`) binds to `127.0.0.1:7331`. Every
incoming HTTP request runs through a middleware that asks Windows
*"which process owns the other end of this TCP socket?"*, walks the
TCP table via `GetExtendedTcpTable`, opens the process token, reads
the user SID, and tests membership in a configurable Windows group.
If the user is a member, the request runs. If not, the sidecar
returns `403`. If the connection can't be identified at all (a race
where the socket closed before the lookup), the sidecar also returns
`403` — we fail closed.

The default required group is **`BUILTIN\Administrators`** (SID
`S-1-5-32-544`), matching AAM Pro's own default admin policy. This
is configurable via the `auth_required_group_sid` setting; any
local-or-domain group SID works.

## Why this and not OAuth

We considered an OAuth redirect to AAM Pro's bundled IAM (which is
how AAM Pro's own admin UI works). We chose peer-identity instead
because:

- **Zero clicks.** The browser opens, the chat is there.
- **Per-request verification.** OAuth verifies who logged in some
  hours ago. Peer-identity verifies who's connecting *right now*. If
  a coworker walks up and uses your unlocked desktop, OAuth would
  still grant them access; peer-identity sees their TCP socket
  belongs to your session.
- **No session storage.** Nothing to expire, nothing to revoke,
  nothing to leak.
- **Audit attribution falls out.** Every request already knows who
  the user is — the audit log's `principal` field is the real
  `DOMAIN\username` automatically.

The cost is that ChAAMP is **Windows-only**. The sidecar refuses to
start on macOS / Linux rather than degrading silently into a no-auth
state. That fits the deployment reality: AAM Pro itself only runs on
Windows.

## Allowlist

Three sidecar routes bypass the auth gate. They're either liveness
probes or the identity-probe itself:

- `GET /healthz` — uvicorn liveness; no auth info.
- `GET /api/healthz` — same.
- `GET /api/config/status` — boolean rollup of which credential slots
  are stored; safe to expose.
- `GET /api/auth/me` — identity probe. Always `200`. Non-admins can
  read this to see what they're signed in as and which group they
  need to be in.

Every other route enforces admin membership.

## What if I'm in Administrators but get 403?

This used to be a real bug — Windows' UAC token filtering removes
`BUILTIN\Administrators` from the *process token* of admin users
running non-elevated processes (the default). A bare
`CheckTokenMembership` against the process token would say "not
admin" for an admin running a normal browser.

The peer-identity module handles this by falling back to the
user's **linked token** (the elevated counterpart Windows keeps
stashed on every filtered token). So:

| Scenario | Result |
|---|---|
| Admin running elevated process | ✓ admin |
| Admin running normal process (UAC-filtered) | ✓ admin (via linked token) |
| Non-admin user | ✗ not admin |
| Sandboxed / restricted token without an admin link | ✗ not admin |

If you're sure you're a local admin but still get denied, check:

1. `whoami /groups` — does it list `BUILTIN\Administrators`? If the
   line says `Group used for deny only`, your account has been
   explicitly denied — see your system policy.
2. The configured group SID in Settings — has it been changed away
   from `S-1-5-32-544` to something you're not in?
3. Restart the browser. The 60-second peer-identity cache may be
   holding a stale "not admin" result.

## Changing who's allowed

The required group is a setting, not code. To broaden access:

1. Open **Settings** from the TopBar menu.
2. Change `auth_required_group_sid`.
3. Save.

Examples:

| SID | Group | Who gets in |
|---|---|---|
| `S-1-5-32-544` | `BUILTIN\Administrators` | Local admins (default) |
| `S-1-5-32-545` | `BUILTIN\Users` | Every signed-in Windows account |
| `S-1-5-32-547` | `BUILTIN\Power Users` | Legacy power-user accounts |
| any custom group SID | e.g., `ChAAMP-Operators` | Whoever you put in that group |

Changes take effect on the next request — no restart.

## Testing as a different user

Use `runas` to launch a browser as another Windows account:

```powershell
runas /user:LimitedUser "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

The Chrome window that opens belongs to `LimitedUser`. Browse to
`http://localhost:7330` (or wherever the dev server is) — you'll see
the access-denied screen with `LimitedUser` named explicitly. Close
that Chrome window to clean up.

## Why there's no Sign-out button

You can't sign out of Windows from inside a web page. The closest
analog would be a button that nukes the peer-identity cache — but
even that wouldn't actually log anyone out, just force a re-check on
the next request. We don't render a button for it because the
mental model is wrong: ChAAMP doesn't have its own session. If you
want to act as another Windows user, switch accounts in Windows
(or use the `runas` recipe above).

## Audit log

Every credential read/write recorded by the audit logger now carries
the real Windows username in its `principal` field, not the previous
`"process"` placeholder. Inspect with:

```
notepad %USERPROFILE%\.aamp_audit.log
```

or via the Audit log panel in the TopBar menu. CLI / MCP-server
invocations (which don't go through the sidecar) continue to log
`"process"` — that distinguishes "the chat agent did this" from "a
human in the web UI did this".

## Trust boundary checklist

- The sidecar binds **127.0.0.1 only**. It refuses any non-loopback
  bind via the `--host` arg.
- The peer-identity middleware fails closed: identification failure
  → 403, not 200.
- The TestClient bypass (synthetic admin identity when
  `request.client.host == "testclient"`) is the **only** code path
  that grants access without a real socket check. It's gated on
  Starlette's TestClient sentinel, which can't be triggered by a
  real HTTP request.
- Credentials still live in OS keyring (per-user). A non-admin user
  on the same machine couldn't read them even if they could reach
  the sidecar (which they can't, because of the gate).
