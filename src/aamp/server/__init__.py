"""HTTP sidecar for ChAAMP.

Wraps :mod:`aamp.mcp_server` with a FastAPI app so the web client can
talk to it. Exposes:

- ``/capture/*``  — credential-capture flow (the secure modal POSTs here)
- ``/chat/*``     — chat session SSE (the next.js useChat() hook calls here)
- ``/mcp/*``      — generic MCP tool surface for the web client

Run with::

    aamp-server   # binds to 127.0.0.1:7331

Always 127.0.0.1 only — never bind 0.0.0.0. The capture endpoint writes
to the OS keyring; remote exposure would be a security disaster.
"""
