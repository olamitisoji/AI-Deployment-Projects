-- Private FastAPI/worker runtime role. Login/password provisioning is separate.
-- The migration administrator remains owner; browser roles receive no access.
BEGIN;

CREATE ROLE echo_runtime WITH
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 10;

GRANT CONNECT ON DATABASE postgres TO echo_runtime;
GRANT USAGE ON SCHEMA public TO echo_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.delivery_events,
    public.participants,
    public.projects,
    public.inbound_events,
    public.outbox,
    public.project_members,
    public.studies,
    public.interviews,
    public.invitations,
    public.turns
TO echo_runtime;

CREATE POLICY echo_runtime_access ON public.delivery_events
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.participants
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.projects
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.inbound_events
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.outbox
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.project_members
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.studies
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.interviews
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.invitations
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);
CREATE POLICY echo_runtime_access ON public.turns
    FOR ALL TO echo_runtime USING (true) WITH CHECK (true);

COMMIT;
