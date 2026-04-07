/** @type {import('next').NextConfig} */
const isExport = process.env.NEXT_OUTPUT === 'export'

const nextConfig = {
  // 'export' → static files for S3/CloudFront  |  'standalone' → Docker
  output: isExport ? 'export' : 'standalone',
  trailingSlash: isExport,
  images: {
    // Required for static export; harmless in standalone
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
}

module.exports = nextConfig
