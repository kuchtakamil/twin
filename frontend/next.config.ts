import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'export',
  images: {
    unoptimized: true
  },
  transpilePackages: ['remark-gfm']
};

export default nextConfig;