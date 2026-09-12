-- Migration 005: MeetScribe webhook session metadata storage.
-- Stores meeting notes/session metadata received via webhook from MeetScribe.

CREATE TABLE IF NOT EXISTS tango.meetscribe_sessions (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL UNIQUE,
    title TEXT,
    status TEXT,
    started_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    summary TEXT,
    action_items JSONB,
    key_decisions JSONB,
    webhook_received_at TIMESTAMPTZ DEFAULT now()
);
