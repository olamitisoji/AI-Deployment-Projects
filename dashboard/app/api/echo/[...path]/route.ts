import { proxyRequest } from '@/lib/proxy';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
async function handle(request: Request, context: {params: Promise<{path:string[]}>}) {
 return proxyRequest(request, (await context.params).path, process.env);
}
export { handle as GET, handle as POST, handle as PUT };
