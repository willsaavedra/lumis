/**
 * CloudFront Functions — viewer-request
 *
 * Rewrites SPA-style paths to S3 object keys for a static Next.js export
 * (trailingSlash). Works for any depth: /a/b/c/ → a/b/c/index.html,
 * /a/b/c → a/b/c/index.html.
 *
 * Dynamic routes: Next export only emits a placeholder segment `_` (see
 * generateStaticParams). Real IDs must map to that shell, e.g.
 * /repositories/<uuid>/ → /repositories/_/index.html (otherwise S3 404 → home).
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

  // Static export shells live only under /repositories/_/ and /analyses/_/
  var placeholder = mapDynamicSegmentToPlaceholderUri(uri)
  if (placeholder !== null) {
    request.uri = placeholder
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

/**
 * Single dynamic segment after prefix → prebuilt placeholder HTML (segment '_').
 * Returns null when the list route or placeholder path should use default rules.
 */
function mapDynamicSegmentToPlaceholderUri(uri) {
  var r = mapOneSegmentDynamic(uri, '/repositories/', '/repositories/_/index.html')
  if (r !== null) {
    return r
  }
  return mapOneSegmentDynamic(uri, '/analyses/', '/analyses/_/index.html')
}

function mapOneSegmentDynamic(uri, prefix, targetIndexHtml) {
  if (!uri.startsWith(prefix)) {
    return null
  }
  var rest = uri.substring(prefix.length)
  if (rest.endsWith('/')) {
    rest = rest.substring(0, rest.length - 1)
  }
  if (rest === '') {
    return null
  }
  if (rest.indexOf('/') !== -1) {
    return null
  }
  if (rest === '_') {
    return null
  }
  return targetIndexHtml
}
