/** @type {import('next').NextConfig} */

// NEXT_OUTPUT env controls the output mode:
//   (unset)      → Vercel default (no output key — Vercel manages the build)
//   'standalone' → Docker image (apps/api/Dockerfile target: dev/prod)
//   'export'     → legacy static S3/CloudFront bundle (see deploy:cf script)
const output = process.env.NEXT_OUTPUT || undefined

const nextConfig = {
  ...(output ? { output } : {}),
  trailingSlash: output === 'export',
  images: {
    // Disable Next.js image optimisation for static export only.
    // Vercel and standalone Docker handle it natively.
    unoptimized: output === 'export',
  },
}

module.exports = nextConfig
