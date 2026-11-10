-- Run using an authenticated echo_runtime connection after private login setup.
-- Catalog checks inspect privileges, not auth.users or participant rows.
BEGIN READ ONLY;

DO $echo_verify$
DECLARE
    runtime_oid oid;
    attributes record;
    table_name text;
    privilege_name text;
    browser_role text;
    relation_oid oid;
    auth_users_oid oid;
    tables text[] := ARRAY[
        'delivery_events', 'participants', 'projects', 'inbound_events', 'outbox',
        'project_members', 'studies', 'interviews', 'invitations', 'turns'
    ];
BEGIN
    IF current_user <> 'echo_runtime' THEN
        RAISE EXCEPTION 'Verification requires an echo_runtime connection';
    END IF;
    SELECT oid, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit, rolconnlimit
        INTO STRICT attributes FROM pg_catalog.pg_roles WHERE rolname = 'echo_runtime';
    runtime_oid := attributes.oid;
    IF attributes.rolsuper OR attributes.rolcreatedb OR attributes.rolcreaterole
       OR attributes.rolreplication OR attributes.rolbypassrls OR attributes.rolinherit
       OR attributes.rolconnlimit <> 10 THEN
        RAISE EXCEPTION 'Echo runtime has unexpected role capabilities';
    END IF;
    IF NOT has_database_privilege('echo_runtime', 'postgres', 'CONNECT')
       OR NOT has_schema_privilege('echo_runtime', 'public', 'USAGE') THEN
        RAISE EXCEPTION 'Echo runtime lacks required connection/schema usage';
    END IF;
    IF has_schema_privilege('echo_runtime', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'Echo runtime can create public objects (check inherited PUBLIC privileges)';
    END IF;
    SELECT relation.oid INTO STRICT auth_users_oid
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'auth' AND relation.relname = 'users';
    IF has_schema_privilege('echo_runtime', 'auth', 'USAGE')
       OR has_table_privilege('echo_runtime', auth_users_oid, 'SELECT') THEN
        RAISE EXCEPTION 'Echo runtime has unexpected access to Supabase Auth';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member = runtime_oid) THEN
        RAISE EXCEPTION 'Echo runtime unexpectedly inherits another database role';
    END IF;

    FOREACH table_name IN ARRAY tables LOOP
        relation_oid := pg_catalog.to_regclass(format('public.%I', table_name));
        IF relation_oid IS NULL THEN
            RAISE EXCEPTION 'Required Echo table missing: %', table_name;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class
                       WHERE oid = relation_oid AND relrowsecurity AND NOT relforcerowsecurity
                         AND relowner <> runtime_oid) THEN
            RAISE EXCEPTION 'Unexpected Echo table ownership/RLS: %', table_name;
        END IF;
        FOREACH privilege_name IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
            IF NOT has_table_privilege('echo_runtime', relation_oid, privilege_name) THEN
                RAISE EXCEPTION 'Runtime lacks % on %', privilege_name, table_name;
            END IF;
            FOREACH browser_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = browser_role) THEN
                    IF has_table_privilege(browser_role, relation_oid, privilege_name)
                       OR pg_has_role(browser_role, runtime_oid, 'MEMBER') THEN
                        RAISE EXCEPTION 'Browser role unexpectedly has Echo access: %', browser_role;
                    END IF;
                END IF;
            END LOOP;
        END LOOP;
        FOREACH privilege_name IN ARRAY ARRAY['TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege('echo_runtime', relation_oid, privilege_name) THEN
                RAISE EXCEPTION 'Runtime unexpectedly has % on %', privilege_name, table_name;
            END IF;
        END LOOP;
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_class AS relation,
                LATERAL pg_catalog.aclexplode(COALESCE(relation.relacl, pg_catalog.acldefault('r', relation.relowner))) AS permission
            WHERE relation.oid = relation_oid AND permission.grantee = 0
        ) THEN
            RAISE EXCEPTION 'PUBLIC unexpectedly retains an Echo table privilege: %', table_name;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_policy
            WHERE polrelid = relation_oid AND polname = 'echo_runtime_access'
              AND polcmd = '*' AND polpermissive AND polroles = ARRAY[runtime_oid]
              AND pg_catalog.pg_get_expr(polqual, polrelid) = 'true'
              AND pg_catalog.pg_get_expr(polwithcheck, polrelid) = 'true'
        ) THEN
            RAISE EXCEPTION 'Runtime-only RLS policy missing or changed: %', table_name;
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'authenticator') THEN
        IF pg_has_role('authenticator', runtime_oid, 'MEMBER') THEN
            RAISE EXCEPTION 'PostgREST authenticator can assume Echo runtime';
        END IF;
    END IF;
END;
$echo_verify$;

-- LIMIT 0 exercises SELECT authorization without returning or scanning records.
SELECT 1 FROM public.delivery_events LIMIT 0;
SELECT 1 FROM public.participants LIMIT 0;
SELECT 1 FROM public.projects LIMIT 0;
SELECT 1 FROM public.inbound_events LIMIT 0;
SELECT 1 FROM public.outbox LIMIT 0;
SELECT 1 FROM public.project_members LIMIT 0;
SELECT 1 FROM public.studies LIMIT 0;
SELECT 1 FROM public.interviews LIMIT 0;
SELECT 1 FROM public.invitations LIMIT 0;
SELECT 1 FROM public.turns LIMIT 0;
SELECT true AS echo_runtime_verification_passed;
ROLLBACK;
