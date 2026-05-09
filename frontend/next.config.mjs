/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "*.supabase.co" },
      { protocol: "https", hostname: "*.supabase.in" },
      { protocol: "https", hostname: "images.unsplash.com" },
    ],
  },
  async rewrites() {
    const apiV2Base = process.env.API_V2_URL ?? "http://localhost:8001";
    const apiV1Base = process.env.API_V1_URL ?? "http://localhost:5001";
    return [
      // Route v2 API calls to FastAPI
      {
        source: "/api/v2/:path*",
        destination: `${apiV2Base}/api/v2/:path*`,
      },
      // Route legacy API calls to Flask
      {
        source: "/api/:path*",
        destination: `${apiV1Base}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
