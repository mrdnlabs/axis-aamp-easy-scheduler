"""ChAAMP HTTP sidecar — FastAPI app that hosts the credential-capture
endpoint, the chat SSE bridge, and (later) a generic MCP tool surface
for the web client.

Run with::

    aamp-server                             # default: http://127.0.0.1:7331
    aamp-server --host 127.0.0.1 --port 8888

**Always 127.0.0.1.** The capture endpoint writes to the OS credential
vault. Exposing it on any other interface would be a security disaster.
The CLI's ``--host`` flag exists for tests and unusual deployments only;
the default refuses anything but loopback.
"""

from __future__ import annotations

import argparse
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import capture, chat


# Origin of the Next.js dev server. CORS is restrictive — only this origin
# may call the sidecar. Production deployments will likely co-host the
# Next.js + FastAPI behind a reverse proxy and not need CORS at all.
WEB_ORIGIN_DEV = "http://localhost:7330"


def create_app() -> FastAPI:
    """Construct the FastAPI app with all routes mounted."""
    app = FastAPI(
        title="ChAAMP sidecar",
        description=(
            "Credential capture + chat SSE for the ChAAMP web client. "
            "Binds to 127.0.0.1 only — never expose remotely."
        ),
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[WEB_ORIGIN_DEV],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    # Routes live under /api so the Next.js dev-server rewrite rule
    # (next.config.js: /api/credential-capture/* -> :7331) lines up.
    app.include_router(capture.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


# Module-level app for ``uvicorn aamp.server.app:app`` usage.
app = create_app()


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point — runs uvicorn with safe defaults."""
    parser = argparse.ArgumentParser(prog="aamp-server", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind host (default: 127.0.0.1 — DO NOT change for production)")
    parser.add_argument("--port", type=int, default=7331,
                        help="bind port (default: 7331)")
    parser.add_argument("--reload", action="store_true",
                        help="enable hot reload (development only)")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        print(
            f"REFUSING to bind to {args.host!r} — the capture endpoint must "
            "remain loopback-only. Override at your own risk by editing app.py.",
            file=sys.stderr,
        )
        return 2

    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn not installed. Run: pip install 'uvicorn[standard]>=0.32'",
            file=sys.stderr,
        )
        return 1

    uvicorn.run(
        "aamp.server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
