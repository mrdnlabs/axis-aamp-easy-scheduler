/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ChAAMP is an internal tool — keep error overlays as helpful as possible.
  experimental: {
    typedRoutes: true,
  },
  async rewrites() {
    // Proxy every /api/* path to the Python sidecar (aamp-server) running
    // at 127.0.0.1:7331. The sidecar mounts ALL its FastAPI routers under
    // /api/* — so the destination must keep the /api/ prefix in the
    // forwarded URL or every request 404s.
    //
    // Routes proxied:
    //   /api/credential-capture/start         — POST: mint a capture token
    //   /api/credential-capture/{token}/status — GET: countdown + slot info
    //   /api/credential-capture/{token}        — POST: submit value (single-use)
    //   /api/chat/message                     — POST: enqueue a chat message
    //   /api/chat/{session_id}/stream         — GET: SSE message-parts stream
    return [
      {
        source: "/api/credential-capture/:path*",
        destination: "http://127.0.0.1:7331/api/credential-capture/:path*",
      },
      {
        source: "/api/chat/:path*",
        destination: "http://127.0.0.1:7331/api/chat/:path*",
      },
    ];
  },
};
module.exports = nextConfig;
