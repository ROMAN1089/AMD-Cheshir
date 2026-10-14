import type { NextConfig } from 'next';
const config: NextConfig = {
  output:'standalone',
  async rewrites() { const backend=process.env.BACKEND_URL || 'http://127.0.0.1:5000'; return [{source:'/api/:path*',destination:`${backend}/api/:path*`},{source:'/media/:path*',destination:`${backend}/media/:path*`}]; },
};
export default config;
