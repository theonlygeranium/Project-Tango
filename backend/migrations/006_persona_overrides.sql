-- Migration 006: Persona overrides for Control Mode
-- Stores persistent behavior/instruction changes made via the voice
-- agent's Control Mode administrative interface.

CREATE SCHEMA IF NOT EXISTS tango;

CREATE TABLE IF NOT EXISTS tango.persona_overrides (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      VARCHAR(50) NOT NULL,
    change_type     VARCHAR(30) NOT NULL CHECK (change_type IN (
                        'tone',
                        'instruction_addition',
                        'instruction_replacement',
                        'behavior_rule'
                    )),
    content         TEXT        NOT NULL,
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persona_overrides_persona
    ON tango.persona_overrides (persona_id, active, created_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'z121532') THEN
        GRANT USAGE ON SCHEMA tango TO z121532;
        GRANT ALL ON TABLE tango.persona_overrides TO z121532;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tango_user') THEN
        GRANT USAGE ON SCHEMA tango TO tango_user;
        GRANT ALL ON TABLE tango.persona_overrides TO tango_user;
    END IF;
END $$;
