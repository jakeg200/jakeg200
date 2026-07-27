import type { NextConfig } from "next";

const config: NextConfig = {
  env: {
    WARRANT_API: process.env.WARRANT_API ?? "http://localhost:8000",
  },
};

export default config;
