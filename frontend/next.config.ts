import { withAui } from "@assistant-ui/next";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep local HMR working whether the browser uses localhost or 127.0.0.1.
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};

export default withAui(nextConfig);
