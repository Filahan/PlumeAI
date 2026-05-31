import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // MCP SDK is server-only with subpath exports Turbopack's bundler mis-resolves;
  // let Node resolve it at runtime instead.
  serverExternalPackages: ["@modelcontextprotocol/sdk"],
};

export default nextConfig;
