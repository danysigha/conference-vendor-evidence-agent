import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  outputFileTracingIncludes: {
    "/api/sessions": [
      "./data/conference/**/*",
      "./outputs/**/*.xlsx",
    ],
    "/api/sessions/[id]/messages": [
      "./data/conference/**/*",
      "./outputs/**/*.xlsx",
    ],
    "/api/conference/directory": ["./outputs/**/*.xlsx"],
    "/sources/[docId]": ["./data/conference/raw/**/*"],
  },
  // Managed Agents turns and file downloads stream through route handlers;
  // keep them out of any response cache.
  headers: async () => [
    {
      source: "/api/:path*",
      headers: [{ key: "Cache-Control", value: "no-store" }],
    },
  ],
};

export default nextConfig;
