# Architectural Decision Records

Each ADR is a file named `YYYY-MM-DD-NNN-short-title.md`, where `NNN` is its number. Numbers are
unique for Project Tango ADRs. **Next free number: 029.**

## Renumbered on 2026-10-05

Five Tango ADRs were created with numbers that Discord-fleet ADRs had already taken a day or two
earlier, so "ADR-011" or "ADR-012" could mean two or three different decisions. They were
renumbered; each file states its former number. Older commits, CHANGELOG entries and comments that
cite the former numbers refer to these files.

| New | Former | File | Decision |
|---|---|---|---|
| ADR-024 | ADR-011 | `2026-08-20-024-flux-eager-eot.md` | Per-persona Deepgram Flux eager end-of-turn |
| ADR-025 | ADR-012 | `2026-08-20-025-voice-mcp-access.md` | Read-only MCP tools for voice personas |
| ADR-026 | ADR-013 | `2026-08-20-026-control-mode.md` | Control Mode (voice-driven persona overrides) |
| ADR-027 | ADR-014 | `2026-08-20-027-voice-programs.md` | Voice-created programs (derived personas) |
| ADR-028 | ADR-012 | `2026-09-12-028-disable-sync-transcription.md` | Disable RoomIO transcript sync, raise `max_tool_steps` |

## Project Tango voice companion

| Number | Date | File | Decision |
|---|---|---|---|
| ADR-001 | 2026-06-22 | `2026-06-22-001-livekit-agents-sdk.md` | LiveKit Agents SDK, not Pipecat |
| ADR-002 | 2026-06-26 | `2026-06-26-002-deepgram-flux-stt.md` | Deepgram Flux STT for English personas |
| ADR-003 | 2026-06-28 | `2026-06-28-003-nova3-tagalog-stt.md` | Deepgram Nova-3 `tl` for Tagalog personas |
| ADR-004 | 2026-06-27 | `2026-06-27-004-disable-tts-aligned-transcript.md` | `use_tts_aligned_transcript=False` (incomplete; see ADR-028) |
| ADR-005 | 2026-06-23 | `2026-06-23-005-cloudflare-tunnel-direct.md` | Cloudflare Tunnel straight to the backend |
| ADR-006 | 2026-06-23 | `2026-06-23-006-dispatch-after-room-connect.md` | Dispatch the agent after `room.connect()` |
| ADR-007 | 2026-06-22 | `2026-06-22-007-litellm-proxy-all-llm.md` | All LLM calls through LiteLLM |
| ADR-008 | 2026-07-01 | `2026-07-01-008-f5-tts-jeremiah-pilot.md` | F5-TTS sidecar pilot for Jeremiah |
| ADR-009 | 2026-07-22 | `2026-07-22-009-groq-tagalog-and-voice-constraints.md` | Groq for Tagalog personas; Layer 1 voice constraints |
| ADR-010 | 2026-07-22 | `2026-07-22-010-account-authentication-and-persona-authorization.md` | Accounts and persona authorization |
| ADR-023 | 2026-10-05 | `2026-10-05-023-flux-stt-turn-detection.md` | Restore Flux as the turn-detection source |
| ADR-024 | 2026-08-20 | `2026-08-20-024-flux-eager-eot.md` | Flux eager end-of-turn (not in effect until ADR-023) |
| ADR-025 | 2026-08-20 | `2026-08-20-025-voice-mcp-access.md` | Voice MCP access |
| ADR-026 | 2026-08-20 | `2026-08-20-026-control-mode.md` | Control Mode |
| ADR-027 | 2026-08-20 | `2026-08-20-027-voice-programs.md` | Voice programs |
| ADR-028 | 2026-09-12 | `2026-09-12-028-disable-sync-transcription.md` | Disable transcript sync; vision clause reversed 2026-10-05 |

## Discord bot fleet and other projects in this repository

These ADRs belong to the Discord bot fleet, Nexus and related tooling that share this repository.
They were not renumbered. Numbers 015, 016 and 020 are each still used by two fleet ADRs; tell them
apart by date.

| Number | Date | File |
|---|---|---|
| ADR-011 | 2026-08-18 | `2026-08-18-011-discord-slack-notifications.md` |
| ADR-012 | 2026-08-18 | `2026-08-18-012-slack-mcp-server.md` |
| ADR-013 | 2026-08-19 | `2026-08-19-013-mcp-only-no-webhooks.md` |
| ADR-014 | 2026-08-19 | `2026-08-19-014-writer-playbook-integration.md` |
| ADR-015 | 2026-08-19 | `2026-08-19-015-discord-bot-ui-ux-enhancements.md` |
| ADR-015 | 2026-08-20 | `2026-08-20-015-architect-thread-channel-fix.md` |
| ADR-016 | 2026-08-19 | `2026-08-19-016-meetscribe-discord-context-integration.md` |
| ADR-016 | 2026-08-20 | `2026-08-20-016-auto-error-remediation.md` |
| ADR-017 | 2026-08-20 | `2026-08-20-017-n8n-alert-aggregation-hub.md` |
| ADR-018 | 2026-08-20 | `2026-08-20-018-nexus-bus-redis-streams.md` |
| ADR-019 | 2026-08-20 | `2026-08-20-019-self-healing-foundation.md` |
| ADR-020 | 2026-08-20 | `2026-08-20-020-hierarchy-collapse.md` |
| ADR-020 | 2026-08-22 | `2026-08-22-020-fleet-palmyra-x6-default.md` |
| ADR-021 | 2026-08-20 | `2026-08-20-021-gitops-update-pipeline.md` |
| ADR-022 | 2026-08-20 | `2026-08-20-022-sentinel-testing-agent.md` |
| — | 2026-08-20 | `2026-08-20-fleet-config-externalization.md` |
| — | 2026-08-20 | `2026-08-20-fleet-config-externalization-phase-2.md` |
