-- Migration 007: Programs — voice-created derived personas
-- Stores named programs with custom system prompts that inherit the base
-- persona's voice, TTS, STT, and MCP tools. Programs are created via Control
-- Mode and activated by voice commands during a conversation.

CREATE SCHEMA IF NOT EXISTS tango;

CREATE TABLE IF NOT EXISTS tango.programs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    base_persona_id VARCHAR(50) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    system_prompt   TEXT        NOT NULL,
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (base_persona_id, name)
);

CREATE INDEX IF NOT EXISTS idx_programs_persona
    ON tango.programs (base_persona_id, active, created_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'z121532') THEN
        GRANT USAGE ON SCHEMA tango TO z121532;
        GRANT ALL ON TABLE tango.programs TO z121532;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tango_user') THEN
        GRANT USAGE ON SCHEMA tango TO tango_user;
        GRANT ALL ON TABLE tango.programs TO tango_user;
    END IF;
END $$;
