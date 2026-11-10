-- Generated from echo.database.Base.metadata by scripts/export_postgres_schema.py.

-- Python ORM defaults are intentionally not PostgreSQL server defaults.

-- Empty Echo schema only; no participant, project, or study records are inserted.

BEGIN;

CREATE TABLE public.delivery_events (
	id VARCHAR(64) NOT NULL,
	provider_id VARCHAR(255) NOT NULL,
	status VARCHAR(30) NOT NULL,
	timestamp INTEGER NOT NULL,
	error_code INTEGER,
	expires_at INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_delivery_events_expires_at ON public.delivery_events (expires_at);

CREATE INDEX ix_delivery_events_provider_id ON public.delivery_events (provider_id);

CREATE TABLE public.participants (
	id VARCHAR(36) NOT NULL,
	phone_hash VARCHAR(64) NOT NULL,
	phone_cipher TEXT NOT NULL,
	opted_out BOOLEAN NOT NULL,
	last_inbound_at INTEGER NOT NULL,
	active_interview_id VARCHAR(36),
	PRIMARY KEY (id),
	UNIQUE (phone_hash)
);

CREATE TABLE public.projects (
	id VARCHAR(36) NOT NULL,
	name VARCHAR(120) NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE public.inbound_events (
	id VARCHAR(255) NOT NULL,
	participant_id VARCHAR(36) NOT NULL,
	payload_cipher TEXT NOT NULL,
	status VARCHAR(20) NOT NULL,
	error_code VARCHAR(80),
	created_at INTEGER NOT NULL,
	received_order BIGINT NOT NULL,
	expires_at INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(participant_id) REFERENCES public.participants (id)
);

CREATE INDEX ix_inbound_events_participant_id ON public.inbound_events (participant_id);

CREATE INDEX ix_inbound_events_status ON public.inbound_events (status);

CREATE TABLE public.outbox (
	id VARCHAR(36) NOT NULL,
	event_id VARCHAR(255) NOT NULL,
	participant_id VARCHAR(36) NOT NULL,
	interview_id VARCHAR(36),
	text_cipher TEXT NOT NULL,
	status VARCHAR(30) NOT NULL,
	provider_id VARCHAR(255),
	delivery_at INTEGER NOT NULL,
	error_code VARCHAR(80),
	control_ack BOOLEAN NOT NULL,
	created_at INTEGER NOT NULL,
	created_order BIGINT NOT NULL,
	expires_at INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (event_id),
	FOREIGN KEY(participant_id) REFERENCES public.participants (id),
	UNIQUE (provider_id)
);

CREATE INDEX ix_outbox_participant_id ON public.outbox (participant_id);

CREATE INDEX ix_outbox_status ON public.outbox (status);

CREATE TABLE public.project_members (
	project_id VARCHAR(36) NOT NULL,
	user_id VARCHAR(128) NOT NULL,
	role VARCHAR(16) NOT NULL,
	PRIMARY KEY (project_id, user_id),
	FOREIGN KEY(project_id) REFERENCES public.projects (id) ON DELETE CASCADE
);

CREATE TABLE public.studies (
	id VARCHAR(36) NOT NULL,
	project_id VARCHAR(36) NOT NULL,
	title VARCHAR(120) NOT NULL,
	pathway TEXT NOT NULL,
	status VARCHAR(20) NOT NULL,
	version INTEGER NOT NULL,
	approved_at INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES public.projects (id)
);

CREATE INDEX ix_studies_project_id ON public.studies (project_id);

CREATE TABLE public.interviews (
	id VARCHAR(36) NOT NULL,
	study_id VARCHAR(36) NOT NULL,
	participant_id VARCHAR(36) NOT NULL,
	status VARCHAR(30) NOT NULL,
	pathway_cipher TEXT NOT NULL,
	state_cipher TEXT NOT NULL,
	consent_cipher TEXT NOT NULL,
	created_at INTEGER NOT NULL,
	updated_at INTEGER NOT NULL,
	expires_at INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (study_id, participant_id),
	FOREIGN KEY(study_id) REFERENCES public.studies (id),
	FOREIGN KEY(participant_id) REFERENCES public.participants (id)
);

CREATE INDEX ix_interviews_participant_id ON public.interviews (participant_id);

CREATE INDEX ix_interviews_study_id ON public.interviews (study_id);

CREATE TABLE public.invitations (
	id VARCHAR(36) NOT NULL,
	study_id VARCHAR(36) NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	max_uses INTEGER NOT NULL,
	uses INTEGER NOT NULL,
	bound_participant_id VARCHAR(36),
	expires_at INTEGER NOT NULL,
	revoked BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(study_id) REFERENCES public.studies (id),
	UNIQUE (token_hash)
);

CREATE INDEX ix_invitations_study_id ON public.invitations (study_id);

CREATE TABLE public.turns (
	id VARCHAR(36) NOT NULL,
	interview_id VARCHAR(36) NOT NULL,
	event_id VARCHAR(255) NOT NULL,
	sequence INTEGER NOT NULL,
	payload_cipher TEXT NOT NULL,
	created_at INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(interview_id) REFERENCES public.interviews (id) ON DELETE CASCADE,
	UNIQUE (event_id)
);

CREATE INDEX ix_turns_interview_id ON public.turns (interview_id);

-- Table creation and browser-role denial become visible in one commit.

ALTER TABLE public.delivery_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.participants ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.inbound_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.outbox ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.project_members ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.studies ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.interviews ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.invitations ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.turns ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.delivery_events, public.participants, public.projects, public.inbound_events, public.outbox, public.project_members, public.studies, public.interviews, public.invitations, public.turns FROM PUBLIC;

DO $echo_access$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL PRIVILEGES ON TABLE public.delivery_events, public.participants, public.projects, public.inbound_events, public.outbox, public.project_members, public.studies, public.interviews, public.invitations, public.turns FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL PRIVILEGES ON TABLE public.delivery_events, public.participants, public.projects, public.inbound_events, public.outbox, public.project_members, public.studies, public.interviews, public.invitations, public.turns FROM authenticated;
    END IF;
END;
$echo_access$;

COMMIT;
