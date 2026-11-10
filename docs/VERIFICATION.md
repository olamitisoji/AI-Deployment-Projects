# Verification record

Recorded on **10 November 2026**. This separates implemented behavior, observed checks, and remaining live-service validation. No participant conversations are bundled or presented as demonstration data.

## Automated and local checks

- Latest full backend run: **132 tests passed** against the application modules, with external provider boundaries replaced by test doubles.
- Latest local dashboard run: **10 gateway tests passed**. TypeScript validation passed, and a production build passed from an isolated source copy without private environment settings (using the already-installed dependencies).
- Bootstrap regressions verify that fresh setup does not discover neighboring credentials and that existing private settings are preserved.
- The [first GitHub Actions run](https://github.com/olamitisoji/AI-Deployment-Projects/actions/runs/42875028190) passed both backend and dashboard jobs on commit `d11239ed1c22b51868f152e0964f193bacff47f4`. This includes fresh dependency installation, backend tests, dashboard tests, production build, and typecheck. The workflow has read-only repository permission and needs no provider secrets.
- Joined API/database/worker flow: signed START invitation → disclosure → no pre-consent transcription → consent → primary question → audio/provider boundary → adaptive follow-up → duplicate suppression → pause/resume → completion → export through a new API instance → withdrawal deletion.
- Ordering regressions cover inbox/outbox events received within the same second. Delivery tests cover callbacks arriving before a send response is saved, duplicate callbacks, and protection against delivery/read status regression.
- A generated non-speech OGG/Opus tone was decoded to WAV locally. A 302-second synthetic WAV was rejected by the five-minute limit. This does not measure speech recognition accuracy.
- A browser workflow on a clearly labeled QA study covered project/draft creation, criteria and branch editing, saving, review, and explicit approval. Missing Meta configuration and a provider HTTP 429 surfaced without fabricated results. QA records were removed afterward; the sample research draft remains unapproved.
- Desktop and phone layouts were inspected. No final screenshot artifact is included because the browser surface was unavailable during final capture.
- Local dashboard/API responses were observed, including 401 for unauthenticated `/projects`. Earlier compiled-browser checks found no configured private credentials in client assets.

Provider test doubles verify how the application handles responses and failures. They do not establish real WhatsApp delivery, live model performance, or research quality.

## Cloud PostgreSQL checks

A Supabase PostgreSQL database was deployed with all ten Echo tables, RLS enabled, and browser-role table grants revoked. A nonowner `echo_runtime` role has required table CRUD privileges and role-only policies, without RLS-bypass capability. The API and worker connected through a verified session pooler using TLS `verify-full` and the provider's official CA.

Observed checks passed:

- Runtime-role capabilities, table ownership, RLS policy scope, required grants, and denial of access to Supabase Auth tables.
- SQLAlchemy insert/read/rollback without leaving a test record.
- Singleton worker advisory-lock acquisition, release/reacquisition, and rejection of a second worker.
- Denial of anonymous/authenticated direct-table reads; security advisor returned `lints: []` at that check.
- A public REST request, `GET /rest/v1/interviews?select=id&limit=0`, using a publishable key returned **HTTP 401 / PostgreSQL `42501` (permission denied)**. No participant records were returned.

The database contains an unapproved sample healthcare-administration study and no participant interviews. Moving the draft preserved its memberships, identifiers, and encryption. SQLite remains a supported local alternative. The running dashboard/API/worker are local, and researcher authentication remains local; production Supabase login and public hosting were not verified.

Environment files, passwords, project identifiers, and provisioning material are excluded from this public record. See [database documentation](../supabase/README.md) for reproducible schema and privilege checks.

## Remaining checks

| Area | Status |
| --- | --- |
| Meta test setup | Authorized sender credentials, permitted tester, and account subscription are not configured in the recorded runtime. |
| Public HTTPS webhook | No public callback is configured. Handshake/signature checks passed against local test clients only. |
| Live transcription | No successful live speech transcription is recorded. A prior request encountered a quota error; provider calls remain disabled in the review runtime. |
| Live adaptive interview | Structured adapter implemented; no successful real-account interview decision is recorded. A prior proposal error preserved the draft. |
| Real WhatsApp delivery | No real test-phone interview, delivered message, or read receipt is recorded. |
| Templates and recruitment | Gated adapter only; no approved production template or contact/CSV recruitment workflow verified. |
| Hosted researcher login | JWT validation implemented and tested; production researcher authentication not configured. |
| Containers | Docker recipe prepared but unexecuted. |
| Commercial eligibility | Unresolved; technical access and an operator flag are not approval. |
| Model quality | Human-scored relevance, neutrality, context retention, and transcription metrics remain unmeasured. |
| Public launch | No public Echo product deployment or custom domain. |

## Real-device acceptance test

Use authorized tester-owned numbers and fictional content after account setup and eligibility review:

1. Record the configured Meta app, test sender, supported API version, permitted tester, and subscribed HTTPS callback. Redact identifiers in shared evidence.
2. Verify a real callback handshake and rejection of altered signatures. Confirm model access and available quota before a small synthetic-data request.
3. Review and approve a study, generate its invitation link, and open it on the tester's phone. Confirm that tapping Send starts the consent disclosure.
4. Send `I CONSENT`; confirm delivery of the first question.
5. Send a short fictional voice note. Verify authenticated retrieval, intelligible transcription, stored decision evidence, and a relevant text follow-up.
6. Exercise another answer, `PAUSE`, `RESUME`, `SKIP`, and completion. Restart the API/worker and retrieve the same transcript.
7. Exercise `STOP` and `WITHDRAW`, queued-message suppression, database deletion, retention cleanup, and the human-support route.
8. Exercise provider failure and uncertain delivery without automatic resend. Test the 24-hour boundary and only an actually approved template for a tester with recorded opt-in.
9. Record outcomes and failures. Mark the live milestone complete only when the real flow succeeds. Participant research still needs the privacy, eligibility, and operational checks in [deployment guidance](DEPLOYMENT.md#before-participant-research).

The offline suite and generated audio tone are prerequisites, not substitutes for this real-device test.
