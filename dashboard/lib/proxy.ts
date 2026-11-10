/** Server-side gateway. Never send the local researcher credential to the browser. */
const allowed = /^(health|projects|projects\/[^/]+\/studies|studies\/[^/]+\/(pathway|propose-pathway|approve|invitations|interviews|synthesis)|interviews\/[^/]+(?:\/export)?)$/;
type Environment = Record<string, string | undefined>;
export async function proxyRequest(request: Request, segments: string[], env: Environment, upstream: typeof fetch = fetch): Promise<Response> {
  const path = segments.join('/');
  if (!allowed.test(path) || segments.some(part => part === '.' || part === '..' || part.includes('%') || part.includes('?'))) return Response.json({detail:'Unknown researcher endpoint.'}, {status:404});
  const url = new URL(request.url);
  const origin = request.headers.get('origin');
  // Next may normalize request.url to localhost even when the browser used 127.0.0.1.
  // Host is the browser-facing authority; do not trust X-Forwarded-Host.
  const host = request.headers.get('host') || url.host;
  const forwardedProtocol = request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim();
  const protocol = forwardedProtocol === 'https' || forwardedProtocol === 'http' ? `${forwardedProtocol}:` : url.protocol;
  let browserUrl: URL;
  try { browserUrl = new URL(`${protocol}//${host}`); } catch { return Response.json({detail:'Invalid request host.'}, {status:400}); }
  if (origin && origin !== browserUrl.origin) return Response.json({detail:'Cross-origin requests are not allowed.'}, {status:403});
  const headers = new Headers({'Content-Type':'application/json'});
  if (path !== 'health') {
    if (env.ECHO_AUTH_MODE === 'local') {
      if (!['localhost','127.0.0.1','[::1]'].includes(browserUrl.hostname)) return Response.json({detail:'Local researcher access is available only on this computer.'}, {status:403});
      if (!env.ECHO_RESEARCHER_TOKEN) return Response.json({detail:'Configure the server-only ECHO_RESEARCHER_TOKEN in dashboard/.env.local.'}, {status:503});
      headers.set('Authorization',`Bearer ${env.ECHO_RESEARCHER_TOKEN}`);
    } else {
      const bearer = request.headers.get('authorization');
      if (!bearer || !/^Bearer \S+$/.test(bearer)) return Response.json({detail:'Sign in with a researcher account.'}, {status:401});
      headers.set('Authorization',bearer);
    }
  }
  try {
    const destination = new URL(env.ECHO_API_URL || 'http://127.0.0.1:8000');
    destination.pathname = `${destination.pathname.replace(/\/$/,'')}/${segments.map(encodeURIComponent).join('/')}`;
    destination.search = url.search;
    const response = await upstream(destination, {method:request.method, headers, body: ['GET','HEAD'].includes(request.method) ? undefined : await request.text(), cache:'no-store', signal:AbortSignal.timeout(60_000), redirect:'error'});
    return new Response(await response.text(), {status:response.status, headers:{'Content-Type':response.headers.get('Content-Type') || 'application/json','Cache-Control':'no-store'}});
  } catch { return Response.json({detail:'Echo API is unavailable. Start the backend and check ECHO_API_URL.'}, {status:502}); }
}
