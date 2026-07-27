/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    ATRIUM_API: process.env.ATRIUM_API ?? "http://localhost:8000",
    ATRIUM_WS: process.env.ATRIUM_WS ?? "ws://localhost:8000",
  },
};
export default nextConfig;
