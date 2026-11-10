# Supabase database

A Supabase PostgreSQL deployment was verified on **10 November 2026**. The local API and worker connected to it; this is a verified database integration, not a public product release or completed WhatsApp interview. Researcher authentication in the recorded runtime remains local. The sample study is unapproved, and no participant interviews are included.

Project identifiers, connection hostnames, credentials, and operator-specific configuration are intentionally absent from the repository. Supply your own authorized project when reproducing these steps. The [SQLite quickstart](../README.md#local-quickstart) does not require Supabase.

## Schema migrations

- `migrations/202611100001_echo_initial.sql` creates the ten application tables, indexes, and constraints, enables RLS, and revokes direct browser-role table privileges in one transaction.
- `migrations/202611100002_echo_runtime.sql` creates the restricted backend runtime role and its explicit table policies. Login/password provisioning is separate and private.

The initial migration was compiled from SQLAlchemy metadata using the PostgreSQL dialect. Python-side defaults remain application defaults. Its exporter imports metadata only; it does not load private settings, connect to a database, or insert records. Do not regenerate over an applied migration. Use a new migration for subsequent changes.

Inspect the target schema before applying migrations through an authorized administrator connection. The initial migration expects no existing Echo tables and intentionally does not hide conflicts with `IF NOT EXISTS`. It changes only the named Echo tables and their indexes, not Supabase Auth or unrelated tables. Never include participant records, passwords, or password verifiers in checked-in migrations.

## Access boundaries

`PUBLIC`, `anon`, and `authenticated` receive no direct Echo-table privileges. No browser-facing grants or policies are created. RLS is enabled; it is not forced. The trusted API/worker connects as `echo_runtime`, a nonowner with role-specific policies, while the application checks researcher/project membership.

The runtime role receives connection and schema usage plus SELECT/INSERT/UPDATE/DELETE on the ten Echo tables. It receives no superuser, role-management, database-creation, replication, RLS-bypass, or schema-creation capability. Its connection limit is ten. Never grant this role to `anon`, `authenticated`, or PostgREST's `authenticator`.

The application runtime must not run `echo.manage init-db` or schema migrations. Use a separately authorized administrator for schema changes. A successful database setup does not configure researcher login, Meta access, a public callback, or model-service access.

## Private connection setup

1. Complete the local setup script first to generate an encryption key and researcher credential. Preserve that key when moving existing encrypted records.
2. Obtain the chosen project's exact direct/session-pooler endpoint and official CA through its authorized connection settings. Use TLS certificate and hostname verification; transaction pooling cannot preserve the worker's session advisory lock.
3. After applying the schema and runtime-role migrations, use `scripts/prepare_supabase_connection.py` with your project reference and verified session hostname. The helper generates a random private credential, writes owner-only settings, and prepares a one-time SCRAM provisioning file. It displays no credentials and changes no remote state itself.
4. Apply the private login operation through authorized administration. Keep the password/verifier out of repository history, logs, screenshots, and chat, and remove the one-time provisioning file afterward. The helper refuses to replace existing private configuration; it is not a general password-rotation workflow.
5. Select the private settings when starting from `backend` with `ECHO_ENV_FILE=.env.supabase`. Keep `OPENAI_API_KEY=` and `OPENAI_KEY_FILE=` empty when reviewing without provider calls. Process variables override settings files.

The private settings file must remain ignored and owner-readable (`0600`). It is not needed for a reviewer using SQLite. The original `.env` can provide a local SQLite alternative; stop the API/worker before switching databases.

The checked-in [public CA](../backend/certs/README.md) is not a private key. Validate its provenance and current provider instructions for your project. Containers use `/app/certs/supabase-ca-2021.crt`; configure `sslrootcert` to the container path. Do not reuse a developer-machine absolute path.

## Reproduce privilege checks

Run `verify_runtime.sql` using an actual authenticated `echo_runtime` connection after private provisioning. It checks:

- Current user, restricted role attributes, required table grants, ownership, and explicit runtime-only RLS policies.
- Lack of runtime schema-creation and Supabase Auth access.
- Denial of `anon`, `authenticated`, and `PUBLIC` Echo-table privileges, with no role membership allowing PostgREST to assume the runtime role.

Its `LIMIT 0` selects return no participant/Auth records, and its read-only transaction rolls back. No `SET ROLE` membership is required. Investigate failed assertions rather than widening privileges to make verification pass. Broader inherited schema permissions can cause a failure even when table migrations are correct.

The recorded deployment passed these checks, an ORM insert/read/rollback, session-lock acquisition/release/reacquisition, and rejection of a second worker. Anonymous/authenticated reads were denied. A public Data API request using a publishable key returned HTTP 401 with PostgreSQL code `42501`. Security advisor returned no findings at that check; this does not certify the application or establish messaging eligibility. See [verification scope](../docs/VERIFICATION.md).
