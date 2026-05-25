/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ChAAMP is an internal tool — keep error overlays as helpful as possible.
  experimental: {
    typedRoutes: true,
  },
  async rewrites() {
    // The credential-capture endpoint lives in a separate local process
    // (the Python MCP server's sidecar at :7331). When the user clicks
    // "Set securely" in the SecureCaptureModal, the form posts here.
    // We proxy locally so the browser doesn't hit a different origin.
    return [
      {
        source: "/api/credential-capture/:path*",
        destination: "http://127.0.0.1:7331/credential-capture/:path*",
      },
    ];
  },
};
module.exports = nextConfig;
