/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ChAAMP is an internal tool — keep error overlays as helpful as possible.
  experimental: {
    typedRoutes: true,
  },
  async rewrites() {
    // Single catch-all: forward every /api/* path to the Python
    // sidecar (aamp-server) at 127.0.0.1:7331. The sidecar mounts
    // ALL its FastAPI routers under /api/* so the destination keeps
    // the prefix.
    //
    // Why catch-all over an explicit list: every new sidecar route
    // would otherwise need a matching rewrite entry, and the
    // failure mode (404 from Next.js's own routing) is easy to miss
    // in dev. The sidecar's PeerIdentityMiddleware enforces auth
    // uniformly, so a permissive proxy doesn't widen the attack
    // surface.
    //
    // Routes currently served by the sidecar:
    //   /api/credential-capture/*  capture token mint + submit
    //   /api/chat/message          chat SSE
    //   /api/config/status         credential rollup
    //   /api/settings/*            tunable runtime settings
    //   /api/credentials           known credential slots (read-only)
    //   /api/audit                 audit log
    //   /api/site-overview         intent-doc-derived site label
    //   /api/auth/me               connecting-user identity
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:7331/api/:path*",
      },
    ];
  },
};
module.exports = nextConfig;
