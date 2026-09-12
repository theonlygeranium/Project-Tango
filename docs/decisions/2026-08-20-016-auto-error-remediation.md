# ADR: Auto-Error Remediation via Inter-Bot Delegation

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Writer Agent (Cursor)

## Context

The Schubert Discord bot fleet (Admiral, Architect, Proctor, Dr. Voss, Quartermaster, Cartographer) runs as long-lived systemd services. When a bot encounters a runtime error (ValueError, AttributeError, etc.), the error is logged to journald and a truncated error message is sent to the Discord channel. However:

1. **No cross-bot notification**: Errors are only logged and sent to the user in the channel. No other bot is notified.
2. **No automated remediation**: A human developer must manually read the logs, diagnose the root cause, and apply a fix.
3. **No log scanning**: The Proctor's HealthMonitor checks service status via `systemctl is-active` but does not scan journalctl logs for error patterns (except briefly after auto-updates).
4. **Error replies lose traceback**: The `❌ Agent error: {str(e)[:500]}` reply truncates the error message and discards the traceback, making it impossible for the Proctor to extract actionable info.

## Decision

Implement an Auto-Error Remediation system that automatically detects runtime errors, diagnoses the root cause, and delegates the fix to the Architect bot — replicating what a human developer would do.

### Architecture

Two detection paths feed into a common delegation pipeline:

1. **Discord error reply detection**: Enhanced error replies now include a compact traceback in a code block. The Proctor's `detect_quality_issue()` parses this to extract error type, source file, line number, and function name via the new `parse_error_from_message()` function.

2. **Journalctl error monitor**: A new continuous background loop in the Proctor's `HealthMonitor` scans all 6 bot service logs every 60 seconds for Python error patterns. The `parse_error_from_journal()` function extracts structured error details from the log lines.

Both paths produce an `ErrorDetails` dataclass, which is used to build a structured FLEET delegation message to the Architect. The Architect receives the error type, source file, line number, function name, and traceback — enough information to read the source code, diagnose the root cause, and apply a fix.

### Guardrails

- **Rate limit**: Max 3 auto-remediation delegations per hour
- **Cooldown**: Same error signature (file:line:error_type) can only be delegated once per 30 minutes
- **Never-touch paths**: AGENTS.md and .env are excluded from auto-remediation
- **Rollback**: The Architect's existing AutoUpdater rollback mechanism applies — if a fix introduces new errors, auto-rollback is triggered

## Rationale

The fleet already had most of the infrastructure:
- FLEET protocol for inter-bot delegation
- Proctor PerformanceTracker for quality issue detection
- Architect auto-updater for code fixes
- Proctor intensive monitor for post-update error scanning

The gap was connecting these pieces: enhancing error replies to include tracebacks, adding continuous log scanning, and structuring the delegation message with actionable error details.

## Alternatives Considered

1. **External monitoring service (Sentry/Datadog)**: Would require external infrastructure and subscription. The fleet already has all the pieces needed for self-contained remediation.
2. **Human-only remediation**: Current approach. Works but requires human intervention for every error, including trivial ones like the `check_hard_blocks` unpack error.
3. **Single centralized error handler**: Would require all bots to report to a central service. The FLEET protocol already provides inter-bot communication, making it simpler to use the existing Proctor-to-Architect delegation channel.

## Consequences

- **Positive**: Errors are detected and fixed automatically, reducing downtime and human intervention.
- **Positive**: The Proctor now catches errors that don't surface as Discord replies (like the recurring "Memory decay failed" error).
- **Risk**: Auto-remediation could apply incorrect fixes. Mitigated by guardrails (rate limit, cooldown, never-touch paths) and the Architect's existing rollback mechanism.
- **Risk**: Increased journalctl scanning could add CPU load. Mitigated by 60-second interval and short scan window (65 seconds of logs per scan).

## References

- `scripts/proctor_observer.py` — ErrorDetails, parse_error_from_message(), parse_error_from_journal()
- `scripts/proctor-bot.py` — HealthMonitor._journal_error_monitor_loop(), _delegate_error_fix()
- `scripts/schubert-bot-v2.py` — Enhanced error reply with compact traceback
- `scripts/architect-bot.py` — Enhanced error reply with compact traceback
- `scripts/fleet_protocol.py` — FLEET delegation protocol
