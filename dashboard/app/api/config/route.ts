export const dynamic = 'force-dynamic';
export async function GET() {
 // Runtime lookup keeps a container's public project values configurable after build.
 const environment = process.env;
 return Response.json({authMode:environment.ECHO_AUTH_MODE === 'local' ? 'local' : 'supabase', localConfigured:!!environment.ECHO_RESEARCHER_TOKEN, supabaseUrl:environment.NEXT_PUBLIC_SUPABASE_URL || '', supabaseAnonKey:environment.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''}, {headers:{'Cache-Control':'no-store'}});
}
