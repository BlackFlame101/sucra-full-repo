import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      ],
    }]
  },
};

if (process.env.SOCRA_MANUAL_TEST === "1") {
  nextConfig.distDir = ".next-socra-test";
  nextConfig.typescript = { tsconfigPath: "tsconfig.socra-test.json" };
}

export default nextConfig;
