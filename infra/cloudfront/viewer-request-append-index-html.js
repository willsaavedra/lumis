/**
 * CloudFront Functions — viewer-request
 *
 * Attach to the S3 origin behavior so paths like /dashboard/ resolve to the
 * object key dashboard/index.html (static Next export + trailingSlash).
 *
 * Without this, S3 returns 404 for directory-style URLs; a 404→index.html
 * error response serves the site root and the user sees the landing page on refresh.
 *
 * Associate: Viewer request, Include body: No
 */
function handler(event) {
  var request = event.request
  var uri = request.uri

  // Next.js build assets already use full file names
  if (uri.startsWith('/_next/')) {
    return request
  }

  if (uri.endsWith('/')) {
    request.uri += 'index.html'
    return request
  }

  // /pricing → pricing/index.html (no file extension in last segment)
  var lastSlash = uri.lastIndexOf('/')
  var lastSegment = lastSlash >= 0 ? uri.substring(lastSlash + 1) : uri
  if (lastSegment.indexOf('.') === -1) {
    request.uri += '/index.html'
  }

  return request
}
