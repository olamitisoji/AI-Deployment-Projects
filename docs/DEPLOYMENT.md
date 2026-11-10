# Deployment and configuration

## Verified scope

The local API and worker have connected to a cloud Supabase PostgreSQL database using TLS certificate and hostname validation. Ten Echo tables are deployed with RLS enabled and browser-role table grants revoked. A dedicated nonowner `echo_runtime` role has the required Echo-table CRUD grants and role-only policies, without RLS bypass or schema-creation privileges.

Runtime privilege assertions, denied anonymous/authenticated table access, an ORM insert/rollback, and worker singleton-lock checks passed. A public REST request using a publishable key was also denied, and the security advisor returned no findings at that check. These results validate the recorded database configuration; they do not certify the whole application.

The dashboard, API, and worker currently run locally with local researcher authentication. There is no public Echo deployment, configured production researcher login, or completed real WhatsApp interview. The sample study remains an unapproved draft; no participant interviews are included. The Docker recipe has not been executed.

## Local settings

Start with the [SQLite quickstart](../README.md#local-quickstart). `scripts/configure_local.py` generates private local backend/dashboard settings and refuses to replace existing values. It also prepares Docker configuration. New local settings default to no AI key or external key-file dependency; existing private settings are preserved.

When starting from `backend`, `ECHO_ENV_FILE=.env` selects SQLite settings; an independently prepared `ECHO_ENV_FILE=.env.supabase` can select cloud PostgreSQL. Restart the API and worker after switching. Keep the encryption key stable for existing records. Never copy a database while changing the key without an explicit re-encryption migration.

To inspect the application without model calls, keep both process overrides:

```sh
ECHO_ENV_FILE=.env OPENAI_API_KEY= OPENAI_KEY_FILE= ../.venv/bin/python -m echo.worker
```

Use the same overrides for API startup. Process environment values override dotenv files. Provider operations require separately configured credentials, access, and available quota; generating a key does not establish those conditions.

Private environment files and local databases must stay excluded from source control and build contexts. Local configuration uses owner-only file permissions. The dashboard's researcher token is server-only; never prefix it with `NEXT_PUBLIC_` or expose local-token mode through a public proxy.

## PostgreSQL and Supabase

See [database setup](../supabase/README.md) for the initial schema, restricted runtime migration, and verification SQL. Apply migrations through a separately authorized administrator. The runtime role must not run `echo.manage init-db` or future migrations.

Use a verified **direct or session-persistent** PostgreSQL connection. A transaction pooler cannot preserve the worker's session advisory lock. The application pool is bounded to two persistent connections and one overflow connection per process; the supplied runtime role has a connection limit of ten. Include the worker's held lock connection when sizing deployments.

Use `sslmode=verify-full` and the database provider's official CA. Confirm the exact endpoint and CA through the chosen project's official connection settings; do not reuse another deployment's hostname. The checked-in public CA is documented in [certificate provenance](../backend/certs/README.md). Containers include it at `/app/certs/supabase-ca-2021.crt`; the container database URL's `sslrootcert` must use that container path rather than a developer-machine path.

For a local API using independently provisioned Supabase settings, run from `backend`:

```sh
ECHO_ENV_FILE=.env.supabase OPENAI_API_KEY= OPENAI_KEY_FILE= ../.venv/bin/python -m uvicorn echo.api:app_factory --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Run the worker in a separate terminal with the same environment selection. SQLite remains available by stopping both processes and restarting with `ECHO_ENV_FILE=.env` and its corresponding private settings.

## Optional local Docker recipe

`compose.yaml` defines PostgreSQL, explicit schema initialization, API, worker, and dashboard. It binds application ports to loopback and defaults to local researcher access. This recipe is prepared but unexecuted.

After running the setup script:

```sh
docker compose --env-file .env.compose up --build
```

Stop existing local application processes first to free ports 8000 and 3002. PostgreSQL persists in a named volume; `docker compose down -v` deletes that volume. A settings source is mounted as a container secret and parsed server-side for optional OpenAI access. The generated standalone local settings contain no AI key; retain that empty configuration for an offline review. This local recipe is distinct from cloud deployment.

## Hosted runtime prerequisites

A public release needs a Python HTTP service, a continuously running single worker, and a Next.js dashboard, sharing a stable encryption key and PostgreSQL database.

1. Apply required administrator migrations before releasing code that needs them. Deploy API and worker using the restricted runtime credential and a verified session connection.
2. Configure asymmetric Supabase researcher JWT signing and account provisioning. The backend checks signature, issuer, audience, expiration, and the `authenticated` role against JWKS; legacy shared-secret JWTs are not accepted. Set backend `MODE=production`, `AUTH_MODE=supabase`, and `SUPABASE_URL`.
3. Supply `DATABASE_URL`, `ENCRYPTION_KEY`, and provider secrets through the host's secret manager. Set dashboard `ECHO_AUTH_MODE=supabase`, its backend address, and the public Supabase URL/key documented in the [dashboard README](../dashboard/README.md). Database/admin credentials, encryption keys, Meta secrets, and OpenAI keys must never enter browser configuration.
4. Put the API behind HTTPS. Run `uvicorn echo.api:app_factory --factory --host 0.0.0.0 --port 8000 --no-access-log` and one `python -m echo.worker` replica as separate services. Configure health checks, rate limits, and alerts. Keep request bodies, authorization headers, verification-token queries, phone numbers, and transcripts out of logs. The webhook enforces a 1 MiB request limit.
5. Configure the Meta callback at `https://<backend-host>/webhooks/whatsapp`, verify handshake/signatures and message subscription, then execute the [real-device test](VERIFICATION.md#real-device-acceptance-test). Keep test messaging and an explicit tester allowlist enabled until eligibility is independently verified.

A test tunnel may expose only the webhook while the researcher workspace stays local. Verify the tunnel's HTTPS address before registering it with Meta. Local credentials and the API explorer must remain private.

## Before participant research

- Verify use-case eligibility, account access, opt-in, template approval/locale, and the messaging-window boundary in the actual environment. An eligibility flag is an operator gate, not evidence of approval.
- Supply a real human support route and HTTPS privacy notice covering the research controller, purposes, processors, consent, retention, withdrawal, and limits on deletion from provider systems, backups, and exports.
- Review approved pathways and evaluate relevance, neutrality, context retention, and transcription quality. The prototype is not approved for patient records or confidential clinical material.
- Exercise withdrawal and retention against the deployed database; keep the worker operational for cleanup. Define backup deletion, encryption-key rotation/re-encryption, spend limits, and incident handling.

The present slice stores no audio objects. If later recording storage is added, use private storage, scoped expiring access, and deletion rules. Contact/CSV recruitment is not implemented; importing a contact must not imply permission to message.

No application API initiates model training. `store:false` on Responses does not itself define all provider retention or logging. Echo withdrawal cannot recall delivered WhatsApp messages or delete external exports.
