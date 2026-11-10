import test from 'node:test';
import assert from 'node:assert/strict';
import { proxyRequest } from '../lib/proxy.ts';
const req = (path, init) => new Request(`http://localhost:3000/api/echo/${path}`, init);
test('rejects backend destinations outside the researcher API', async () => {
 const r = await proxyRequest(req('webhooks/whatsapp'), ['webhooks','whatsapp'], {});
 assert.equal(r.status, 404);
});
test('requires a browser bearer in production auth mode', async () => {
 const r = await proxyRequest(req('projects'), ['projects'], { ECHO_AUTH_MODE:'supabase' });
 assert.equal(r.status, 401);
});
test('local credential cannot be used through a public host', async () => {
 const r = await proxyRequest(new Request('https://public.example/api/echo/projects'), ['projects'], { ECHO_AUTH_MODE:'local', ECHO_RESEARCHER_TOKEN:'private' });
 assert.equal(r.status, 403);
});
test('blocks cross-origin mutation before attaching the server credential', async () => {
 const r = await proxyRequest(req('projects', {method:'POST', headers:{origin:'https://evil.example'}, body:'{}'}), ['projects'], {ECHO_AUTH_MODE:'local',ECHO_RESEARCHER_TOKEN:'private'});
 assert.equal(r.status, 403);
});
test('only health bypasses researcher authentication', async () => {
 let received;
 const r = await proxyRequest(req('health'), ['health'], {}, async (url, init) => {received=init; return new Response('{"status":"ok"}', {headers:{'Content-Type':'application/json'}})});
 assert.equal(r.status, 200);
 assert.equal(received.headers.get('authorization'), null);
 assert.equal(r.headers.get('cache-control'), 'no-store');
});
test('local credential is forwarded upstream without entering response body', async () => {
 let credential;
 const r = await proxyRequest(req('projects'), ['projects'], {ECHO_AUTH_MODE:'local',ECHO_RESEARCHER_TOKEN:'private'}, async (url, init) => { credential=init.headers.get('authorization'); return new Response('[]') });
 assert.equal(credential,'Bearer private');
 assert.equal(await r.text(),'[]');
});
test('supabase mode ignores a configured local credential', async () => {
 let credential;
 const r=await proxyRequest(req('projects',{headers:{Authorization:'Bearer browser-session'}}),['projects'],{ECHO_AUTH_MODE:'supabase',ECHO_RESEARCHER_TOKEN:'local-only'},async(url,init)=>{credential=init.headers.get('authorization');return new Response('[]')});
 assert.equal(r.status,200);
 assert.equal(credential,'Bearer browser-session');
});
test('upstream failures do not expose internal error messages', async () => {
 const r=await proxyRequest(req('health'),['health'],{},async()=>{throw new Error('private credential debug details')});
 assert.equal(r.status,502);
 assert.equal((await r.text()).includes('private credential'),false);
});
test('gateway refuses upstream redirects and forwards no browser cookies', async () => {
 let options;
 await proxyRequest(req('projects',{headers:{Authorization:'Bearer session',Cookie:'private-cookie'}}),['projects'],{},async(url,init)=>{options=init;return new Response('[]')});
 assert.equal(options.redirect,'error');
 assert.equal(options.headers.get('cookie'),null);
});
test('accepts browser loopback host when Next normalizes the internal URL to localhost', async () => {
 const request=new Request('http://localhost:3002/api/echo/projects',{method:'POST',headers:{host:'127.0.0.1:3002',origin:'http://127.0.0.1:3002'},body:'{"name":"QA"}'});
 const r=await proxyRequest(request,['projects'],{ECHO_AUTH_MODE:'local',ECHO_RESEARCHER_TOKEN:'private'},async()=>new Response('{"id":"created"}',{status:201}));
 assert.equal(r.status,201);
});
