-- Migration 004: Account authentication, authorization, and tenant isolation.
-- Applied transactionally by backend/migrate.py.

CREATE SCHEMA IF NOT EXISTS tango;

CREATE TABLE IF NOT EXISTS tango.schema_migrations (
    version         INTEGER PRIMARY KEY,
    filename        TEXT NOT NULL UNIQUE,
    checksum        TEXT NOT NULL,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tango.users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name          VARCHAR(100) NOT NULL CHECK (length(btrim(first_name)) BETWEEN 1 AND 100),
    last_name           VARCHAR(100) NOT NULL CHECK (length(btrim(last_name)) BETWEEN 1 AND 100),
    email               VARCHAR(320) NOT NULL CHECK (email = lower(btrim(email))),
    role                VARCHAR(20) NOT NULL DEFAULT 'regular'
                            CHECK (role IN ('admin', 'regular')),
    password_hash       TEXT NOT NULL,
    password_lookup     BYTEA NOT NULL UNIQUE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          UUID REFERENCES tango.users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at       TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_normalized
    ON tango.users (lower(email));
CREATE INDEX IF NOT EXISTS idx_users_active_role
    ON tango.users (is_active, role);

CREATE TABLE IF NOT EXISTS tango.user_persona_access (
    user_id             UUID NOT NULL REFERENCES tango.users(id) ON DELETE CASCADE,
    persona_id          VARCHAR(50) NOT NULL,
    llm_model_override  VARCHAR(100),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, persona_id)
);

CREATE TABLE IF NOT EXISTS tango.auth_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES tango.users(id) ON DELETE CASCADE,
    token_hash      BYTEA NOT NULL UNIQUE,
    csrf_hash       BYTEA NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    client_ip       INET,
    user_agent      TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
    ON tango.auth_sessions (user_id, expires_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
    ON tango.auth_sessions (expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS tango.auth_rate_limits (
    key_type            VARCHAR(20) NOT NULL CHECK (key_type IN ('ip', 'credential')),
    key_hash            BYTEA NOT NULL,
    failure_count       INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    window_started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_failure_at     TIMESTAMPTZ,
    blocked_until       TIMESTAMPTZ,
    PRIMARY KEY (key_type, key_hash)
);

CREATE INDEX IF NOT EXISTS idx_auth_rate_limits_blocked
    ON tango.auth_rate_limits (blocked_until)
    WHERE blocked_until IS NOT NULL;

CREATE TABLE IF NOT EXISTS tango.voice_room_grants (
    room_name               VARCHAR(200) PRIMARY KEY,
    user_id                 UUID NOT NULL REFERENCES tango.users(id) ON DELETE CASCADE,
    persona_id              VARCHAR(50) NOT NULL,
    effective_llm_model     VARCHAR(100) NOT NULL,
    participant_identity    VARCHAR(200) NOT NULL UNIQUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at              TIMESTAMPTZ NOT NULL,
    dispatched_at           TIMESTAMPTZ,
    revoked_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_voice_room_grants_user_active
    ON tango.voice_room_grants (user_id, expires_at DESC)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS tango.admin_audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    actor_user_id       UUID REFERENCES tango.users(id) ON DELETE SET NULL,
    target_user_id      UUID REFERENCES tango.users(id) ON DELETE SET NULL,
    action              VARCHAR(100) NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    client_ip           INET,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_actor_created
    ON tango.admin_audit_log (actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_target_created
    ON tango.admin_audit_log (target_user_id, created_at DESC);

ALTER TABLE tango.sessions
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES tango.users(id) ON DELETE SET NULL;
ALTER TABLE tango.memories
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES tango.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_user_started
    ON tango.sessions (user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_user_persona
    ON tango.memories (user_id, persona, memory_type, created_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'z121532') THEN
        GRANT USAGE ON SCHEMA tango TO z121532;
        GRANT ALL ON ALL TABLES IN SCHEMA tango TO z121532;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA tango TO z121532;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tango_user') THEN
        GRANT USAGE ON SCHEMA tango TO tango_user;
        GRANT ALL ON ALL TABLES IN SCHEMA tango TO tango_user;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA tango TO tango_user;
    END IF;
END $$;
