"""Launch a Chromium browser pointed at AAM Pro and log all interesting network traffic.

Goal: capture the JSON request/response shapes the AAM Pro SPA uses against
``/webapi/v1/*`` (and the OAuth/OIDC handshake against ports 10032-10034)
so we can document them and eventually swap our write layer to hit those
endpoints instead of writing directly to PostgreSQL.

Usage:
    .venv\\Scripts\\python.exe tools\\observer.py

The browser opens at ``https://localhost/``. Drive the AAM Pro UI as
normal — every relevant request gets appended to
``logs/traffic_<timestamp>.jsonl``. The script exits when the browser
window is closed (or on Ctrl+C / SIGTERM).

Static assets, font/icon fetches, and websocket frames are filtered out.
Auth bearer tokens are masked in the captured headers so the log file is
shareable.
"""

from __future__ import annotations

import asyncio
import json
import re
import signal
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Request, Response

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_STATE_DIR = PROJECT_ROOT / ".browser-state"

# Filter: keep things relevant to AAM Pro analysis.
INTERESTING_HOST_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?")
SKIP_EXTENSIONS = (".js", ".css", ".mjs", ".map", ".png", ".jpg", ".jpeg", ".svg",
                   ".gif", ".woff", ".woff2", ".ttf", ".ico", ".webp", ".webmanifest")
SKIP_RESOURCE_TYPES = {"image", "font", "stylesheet", "media", "manifest"}
MASK_HEADER_NAMES = {"authorization", "cookie", "set-cookie", "x-csrf-token"}

# Inline body masking. We never want passwords or tokens in the log file, even briefly.
JSON_FIELDS_TO_MASK = ("access_token", "refresh_token", "id_token", "password",
                      "client_secret", "code_verifier")
FORM_FIELDS_TO_MASK = ("password", "code_verifier", "code", "client_secret",
                       "access_token", "refresh_token")

_JSON_MASK_PATTERNS = [
    (field, re.compile(rf'("{re.escape(field)}"\s*:\s*")((?:[^"\\]|\\.)*)(")'))
    for field in JSON_FIELDS_TO_MASK
]
_FORM_MASK_PATTERNS = [
    (field, re.compile(rf'(^|&)({re.escape(field)})=([^&]*)'))
    for field in FORM_FIELDS_TO_MASK
]

START_URL = "https://localhost/"


def mask_body(body: str | None) -> str | None:
    """Scrub passwords/tokens from a request or response body before it touches disk."""
    if not body:
        return body
    stripped = body.lstrip()
    if stripped.startswith(("{", "[")):
        for _field, pattern in _JSON_MASK_PATTERNS:
            body = pattern.sub(lambda m: f'{m.group(1)}***MASKED***{m.group(3)}', body)
    elif re.match(r"^[a-zA-Z_][\w.\-]*=", body) and "&" in body:
        for _field, pattern in _FORM_MASK_PATTERNS:
            body = pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}=***MASKED***', body)
    return body


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in MASK_HEADER_NAMES:
            if v and len(v) > 12:
                out[k] = f"{v[:6]}...{v[-4:]}  (masked)"
            else:
                out[k] = "(masked)"
        else:
            out[k] = v
    return out


def is_interesting_url(url: str, resource_type: str) -> bool:
    if not INTERESTING_HOST_RE.match(url):
        return False
    if resource_type in SKIP_RESOURCE_TYPES:
        return False
    bare = url.split("?", 1)[0].lower()
    if bare.endswith(SKIP_EXTENSIONS):
        return False
    return True


async def main() -> int:
    log_path = LOG_DIR / f"traffic_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    summary_count = {"requests": 0, "responses": 0, "paths": set()}
    log_fh = log_path.open("a", encoding="utf-8", buffering=1)
    print(f"[observer] Logging to {log_path}")
    print(f"[observer] Browser state cache: {BROWSER_STATE_DIR}")

    def on_request(req: Request) -> None:
        if not is_interesting_url(req.url, req.resource_type):
            return
        summary_count["requests"] += 1
        try:
            body = req.post_data
        except Exception:
            body = None
        entry = {
            "phase": "request",
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "method": req.method,
            "url": req.url,
            "resource_type": req.resource_type,
            "headers": mask_headers(dict(req.headers)),
            "body": mask_body(body),
        }
        log_fh.write(json.dumps(entry, default=str) + "\n")

    async def on_response(resp: Response) -> None:
        req = resp.request
        if not is_interesting_url(req.url, req.resource_type):
            return
        summary_count["responses"] += 1
        path = req.url.split("?", 1)[0].replace("https://localhost", "").replace("https://127.0.0.1", "")
        summary_count["paths"].add(path)
        body_text: str | None = None
        try:
            ct = resp.headers.get("content-type", "")
            if "json" in ct.lower() or "text" in ct.lower():
                body_text = await resp.text()
                if body_text and len(body_text) > 8000:
                    full_len = len(body_text)
                    body_text = body_text[:8000] + f"...[truncated, full {full_len} bytes]"
        except Exception as e:
            body_text = f"(could not read body: {e})"
        entry = {
            "phase": "response",
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "method": req.method,
            "url": req.url,
            "status": resp.status,
            "status_text": resp.status_text,
            "headers": mask_headers(dict(resp.headers)),
            "body": mask_body(body_text),
        }
        log_fh.write(json.dumps(entry, default=str) + "\n")
        if resp.status >= 400 or req.method != "GET":
            print(f"[{resp.status}] {req.method} {path}")

    closed = asyncio.Event()

    def on_context_close(_ctx) -> None:
        print("[observer] context close event received.")
        closed.set()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_STATE_DIR),
            headless=False,
            ignore_https_errors=True,
            args=[
                "--ignore-certificate-errors",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1400,900",
            ],
            viewport={"width": 1400, "height": 900},
        )
        context.on("request", on_request)
        context.on("response", on_response)
        context.on("close", on_context_close)

        # Use any existing page in the persistent context, else open new.
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(START_URL, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"[observer] initial goto failed (you can navigate manually): {e}")

        print("[observer] Browser is open. Drive AAM Pro as you normally would.")
        print("[observer] Close the browser window (or Ctrl+C this terminal) to stop.\n")

        # Install signal handlers so Ctrl+C drains the event loop cleanly.
        loop = asyncio.get_running_loop()

        def _signal_exit() -> None:
            print("\n[observer] signal received; exiting.")
            closed.set()

        try:
            loop.add_signal_handler(signal.SIGINT, _signal_exit)
        except (NotImplementedError, AttributeError):
            # Windows asyncio doesn't support add_signal_handler on default loop.
            # KeyboardInterrupt will propagate normally instead.
            pass

        # Block until the context closes (user closes browser) OR signal.
        try:
            await closed.wait()
        except KeyboardInterrupt:
            pass

        try:
            await context.close()
        except Exception:
            pass

    log_fh.close()
    print(f"[observer] Done. {summary_count['requests']} requests, "
          f"{summary_count['responses']} responses across "
          f"{len(summary_count['paths'])} distinct paths.")
    print(f"[observer] Log saved: {log_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
