-- Migration 001: Initial Project Tango schema
-- Run as: psql -U z121532 -d tango -f migrations/001_initial_schema.sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS tango;

CREATE TABLE IF NOT EXISTS tango.sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      VARCHAR(50) NOT NULL,
    persona_name    VARCHAR(100) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    duration_secs   INTEGER GENERATED ALWAYS AS (
                        EXTRACT(EPOCH FROM (ended_at - started_at))::INTEGER
                    ) STORED,
    user_agent      TEXT,
    client_ip       INET,
    livekit_room    VARCHAR(200),
    llm_model       VARCHAR(100),
    total_tokens    INTEGER DEFAULT 0,
    error_code      VARCHAR(50),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tango.turns (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES tango.sessions(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,
    speaker         VARCHAR(10) NOT NULL CHECK (speaker IN ('user', 'agent')),
    text            TEXT NOT NULL,
    is_final        BOOLEAN NOT NULL DEFAULT TRUE,
    tokens_used     INTEGER DEFAULT 0,
    latency_ms      INTEGER,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_persona ON tango.sessions(persona_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON tango.sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_session ON tango.turns(session_id, turn_index);

GRANT USAGE ON SCHEMA tango TO z121532;
GRANT ALL ON ALL TABLES IN SCHEMA tango TO z121532;
GRANT ALL ON ALL SEQUENCES IN SCHEMA tango TO z121532;
