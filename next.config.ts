import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Ship the built Windows app with the function that serves it.
  outputFileTracingIncludes: {
    "/api/collector/windows": ["./collector-dist/custy-collector.exe"],
    "/api/collector/version": ["./collector-dist/custy-collector.exe"],
  },
};

export default nextConfig;
