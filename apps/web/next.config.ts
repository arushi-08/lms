import type { NextConfig } from "next";

import { buildCsp } from "./csp.mjs";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    // Built from NEXT_PUBLIC_API_URL, so the policy follows wherever the API
    // is. See csp.mjs for why that matters.
    const csp = buildCsp(process.env.NEXT_PUBLIC_API_URL);

    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default config;
