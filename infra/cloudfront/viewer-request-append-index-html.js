/**
 * CloudFront Functions — viewer-request
 *
 * Rewrites SPA-style paths to S3 object keys for a static Next.js export
 * (trailingSlash). Works for any depth: /a/b/c/ → a/b/c/index.html,
 * /a/b/c → a/b/c/index.html.
 *
 * Skips real files: /_next/*, common extensions, .html, /.well-known/*.
 *
 * Associate: Viewer request · Include body: No
 */
function handler(event) {
  var request = event.request
  var uri = request.uri

  if (uri === '' || uri === null) {
    request.uri = '/index.html'
    return request
  }

  // Next.js hashed assets (always concrete filenames)
  if (uri.startsWith('/_next/')) {
    return request
  }

  // Optional: CRA/Vite-style public assets
  if (uri.startsWith('/static/')) {
    return request
  }

  // ACME, Universal Links, etc. — must not append index.html
  if (uri.startsWith('/.well-known/')) {
    return request
  }

  // Already requesting an HTML or other explicit object
  if (endsWithHtml(uri)) {
    return request
  }

  // Directory URL: /dashboard/ → dashboard/index.html
  if (uri.endsWith('/')) {
    request.uri = uri + 'index.html'
    return request
  }

  // Last path segment looks like a real file (has a dot) → leave as-is
  // e.g. /favicon.ico, /_next/static/chunks/main-abc.js, /file.min.css
  var lastSeg = lastPathSegment(uri)
  if (segmentLooksLikeFile(lastSeg)) {
    return request
  }

  // Any app route without trailing slash: /login, /analyses/x, /a/b/c
  request.uri = uri + '/index.html'
  return request
}

function lastPathSegment(uri) {
  var i = uri.lastIndexOf('/')
  if (i < 0) {
    return uri
  }
  return uri.substring(i + 1)
}

function endsWithHtml(uri) {
  var len = uri.length
  if (len < 6) {
    return false
  }
  return uri.substring(len - 5) === '.html'
}

/** Dot in the last segment → treat as static asset / real file, not an app route. */
function segmentLooksLikeFile(segment) {
  if (segment === '') {
    return false
  }
  return segment.indexOf('.') !== -1
}
