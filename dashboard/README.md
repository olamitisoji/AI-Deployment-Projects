# Echo researcher dashboard

Independent **Next.js + TypeScript** researcher workspace for the WhatsApp-first pilot. Participant interviews run on WhatsApp; this dashboard has no participant web interview.

## Run locally

Use Node 22.13+ and start the FastAPI backend first (see `../backend`).

```sh
npm ci
cp .env.example .env.local
# Set ECHO_RESEARCHER_TOKEN to the generated backend token.
npm run dev
```

Open http://127.0.0.1:3000. The scripts bind to this computer only. Local access uses a server-only credential: never prefix it with `NEXT_PUBLIC_`. `ECHO_API_URL` is server-only and defaults to http://127.0.0.1:8000. The gateway forwards a small allowlist of researcher endpoints, rejects cross-origin calls, and only permits local credential access through a loopback hostname. Protect the local machine and do not expose this local mode through a reverse proxy.

## Researcher workflow

1. Create a project and study from an objective and opening questions.
2. Edit topic cards: questions, information requirements, optional probes, clarification/deeper conditions, follow-up limits, destinations, conditional transitions, and completion settings.
3. Save a deterministic draft or request a real AI proposal. AI configuration/quota failures are surfaced; no fake AI fallback is displayed.
4. Review the full guide and explicitly approve it. Approval locks the guide.
5. Generate an expiring general or single-use personalized WhatsApp invitation and copy its link or show its QR code. The dashboard never sends a WhatsApp message.
6. Refresh conversations, inspect consent, per-answer decisions/reason codes/evidence, message delivery status and error codes, and export JSON.
7. Inspect **extractive** excerpts and open their source interview. These are not theme analysis or an AI synthesis.

The connection panel reports configuration separately from verification. A real WhatsApp test, successful funded AI request, and Meta commercial eligibility are not claimed by configuration indicators.

## Hosted production authentication

Set `ECHO_AUTH_MODE=supabase`, configure `NEXT_PUBLIC_SUPABASE_URL` and the public `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and configure the backend to validate Supabase JWTs and researcher access. Use an existing researcher email/password account. No registration flow is provided. Supabase access/refresh tokens stay in browser memory (`persistSession:false`, no local storage or cookies); the API gateway forwards the bearer to the backend, which remains the authorization authority. A page reload requires another login. A local credential is never used in Supabase mode. HTTPS, domain/network configuration, account provisioning, and backend production secrets are deployment prerequisites.

## Verification

```sh
npm test
npm run typecheck
npm run build
```

Gateway tests cover auth separation, cross-origin access, disallowed destinations, local hostname limits, public health access, server-only credential forwarding, upstream failure sanitization, cookie/redirect isolation, and the Next localhost/127.0.0.1 normalization regression. No real participant data is bundled. `.env.local`, `.next`, and dependencies are ignored.
