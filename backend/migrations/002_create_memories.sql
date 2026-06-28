-- Migration 002: Create Project Tango memory table
-- Schubert pgvector check on 2026-06-28 found no installed vector extension.
-- TODO: migrate embedding_vec from TEXT to vector(1536) when pgvector is available.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS tango;

CREATE TABLE IF NOT EXISTS tango.memories (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    persona         TEXT        NOT NULL,
    session_id      UUID        REFERENCES tango.sessions(id) ON DELETE SET NULL,
    memory_type     TEXT        NOT NULL CHECK (memory_type IN ('session_summary', 'user_profile', 'open_loop')),
    content         TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    embedding_vec   TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_persona
    ON tango.memories (persona, memory_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_session
    ON tango.memories (session_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'z121532') THEN
        GRANT USAGE ON SCHEMA tango TO z121532;
        GRANT ALL ON TABLE tango.memories TO z121532;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tango_user') THEN
        GRANT USAGE ON SCHEMA tango TO tango_user;
        GRANT ALL ON TABLE tango.memories TO tango_user;
    END IF;
END $$;
