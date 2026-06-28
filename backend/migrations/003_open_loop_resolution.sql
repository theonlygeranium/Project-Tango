-- Migration 003: Add resolution tracking for open loop memories

ALTER TABLE tango.memories
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS resolution_note TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_memories_unresolved
    ON tango.memories (persona, memory_type, created_at DESC)
    WHERE resolved_at IS NULL AND memory_type = 'open_loop';
