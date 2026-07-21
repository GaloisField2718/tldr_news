const KEY_RE = /^daily\/\d{4}\/\d{2}\/\d{2}\/[0-9a-f]{64}\.webp$/;

function headersFor(object) {
  const metadata = object.customMetadata || {};
  const identity = metadata.sha256 || object.httpEtag || object.etag;
  const etag = identity ? (String(identity).startsWith('"') ? String(identity) : `"${identity}"`) : null;
  const headers = new Headers({
    'Content-Type': object.httpMetadata?.contentType || 'image/webp',
    'Cache-Control': 'public, max-age=31536000, immutable',
    'X-Content-Type-Options': 'nosniff',
    'Access-Control-Allow-Origin': '*',
  });
  if (etag) headers.set('ETag', etag);
  return headers;
}

export async function handleRequest(request, env) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', { status: 405, headers: { Allow: 'GET, HEAD' } });
  }
  let pathname;
  try {
    pathname = new URL(request.url).pathname;
    // Decode once and reject ambiguous encodings, control characters and traversal.
    pathname = decodeURIComponent(pathname);
  } catch {
    return new Response('Not Found', { status: 404 });
  }
  if (pathname.includes('\\') || /[\x00-\x1f\x7f]/.test(pathname)) return new Response('Not Found', { status: 404 });
  const key = pathname.startsWith('/') ? pathname.slice(1) : pathname;
  if (!KEY_RE.test(key)) return new Response('Not Found', { status: 404 });

  const object = request.method === 'HEAD' ? await env.ASSETS.head(key) : await env.ASSETS.get(key);
  if (!object) return new Response('Not Found', { status: 404 });
  const headers = headersFor(object);
  if (request.headers.get('If-None-Match') === headers.get('ETag')) return new Response(null, { status: 304, headers });
  return new Response(request.method === 'HEAD' ? null : object.body, { status: 200, headers });
}

export default { fetch: handleRequest };
