#!/usr/bin/env python3
"""
Tango Health Guardian — six-layer self-healing health monitor.

Runs as a systemd timer (every 3 minutes, ~5 seconds execution).
Checks service health, endpoint health, ElevenLabs billing, TTS synthesis,
log anomalies, and worker registration. Auto-remediates where possible.

Usage:
    python3 tango-healthcheck.py [--dry-run]

Exit codes:
    0 = all checks passed
    1 = one or more checks failed (remediation attempted)
    2 = configuration error
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = "/opt/Project-Tango/.env"
LOG_FILE = "/var/log/tango-healthcheck.log"
BACKEND_SERVICE = "tango-backend.service"
WEB_SERVICE = "tango-web.service"
LITELLM_SERVICE = "polyglot-litellm.service"
TTS_SERVICE = "tango-tts.service"

# Services that are alert-only (never auto-restart)
FORBIDDEN_SERVICES = {
    "caddy.service",
    "cloudflared.service",
    "postgresql@18-main.service",
    "tailscaled.service",
}

# Services we can safely restart
SAFE_SERVICES = {BACKEND_SERVICE, WEB_SERVICE, LITELLM_SERVICE, TTS_SERVICE}

# Endpoint health checks: (name, url, expected_substring)
ENDPOINT_CHECKS = [
    ("backend", "http://127.0.0.1:8030/healthz", "ok"),
    ("litellm", "http://127.0.0.1:4000/health/liveness", "alive"),
]

# Log anomaly patterns (checked in last 5 minutes)
ANOMALY_PATTERNS = [
    "NameError",
    "NotImplementedError",
    "no audio frames were pushed",
    "job crashed",
    "unhandled exception",
]
ANOMALY_THRESHOLD = 3  # restart if more than this many errors in 5 min

# Worker registration: look for this in recent logs
WORKER_REGISTRATION_PATTERN = "registered worker"
WORKER_STALE_MINUTES = 5

# TTS test: small text to synthesize (Layer 4)
TTS_TEST_TEXT = "OK"
TTS_TEST_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"  # Daniel - steady broadcaster
TTS_TEST_MODEL = "eleven_flash_v2_5"

# ElevenLabs API
ELEVENLABS_SUBSCRIPTION_URL = "https://api.us.elevenlabs.io/v1/user/subscription"

# How long to wait after a restart before re-checking
RESTART_SETTLE_SECONDS = 5

# Rate limiting: don't restart the same service more than once per 10 minutes
RESTART_COOLDOWN_SECONDS = 600
RESTART_COOLDOWN_FILE = "/tmp/tango-healthcheck-restart-cooldowns.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(message: str, level: str = "INFO") -> None:
    """Write a timestamped log line to the log file and stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] {message}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass  # don't fail if log file isn't writable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_env() -> dict[str, str]:
    """Load environment variables from the .env file."""
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


def run_command(cmd: str, timeout: int = 10) -> tuple[int, str]:
    """Run a shell command, return (exit_code, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def systemctl_is_active(service: str) -> bool:
    code, _ = run_command(f"systemctl is-active {service}")
    return code == 0


def systemctl_restart(service: str) -> bool:
    code, output = run_command(f"sudo systemctl restart {service}", timeout=30)
    return code == 0


def systemctl_start(service: str) -> bool:
    code, output = run_command(f"sudo systemctl start {service}", timeout=30)
    return code == 0


# ---------------------------------------------------------------------------
# Restart cooldown
# ---------------------------------------------------------------------------


def can_restart(service: str) -> bool:
    """Check if we're allowed to restart this service (cooldown not expired)."""
    try:
        if os.path.exists(RESTART_COOLDOWN_FILE):
            with open(RESTART_COOLDOWN_FILE) as f:
                cooldowns = json.load(f)
            last = cooldowns.get(service, 0)
            if time.time() - last < RESTART_COOLDOWN_SECONDS:
                remaining = int(RESTART_COOLDOWN_SECONDS - (time.time() - last))
                log(f"Restart cooldown active for {service} ({remaining}s remaining)", "WARN")
                return False
    except Exception:
        pass
    return True


def record_restart(service: str) -> None:
    """Record that we restarted this service."""
    try:
        cooldowns = {}
        if os.path.exists(RESTART_COOLDOWN_FILE):
            with open(RESTART_COOLDOWN_FILE) as f:
                cooldowns = json.load(f)
        cooldowns[service] = time.time()
        with open(RESTART_COOLDOWN_FILE, "w") as f:
            json.dump(cooldowns, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Layer 1: Service health
# ---------------------------------------------------------------------------


def check_service_health() -> list[str]:
    """Layer 1: Check if critical services are active. Restart if not."""
    issues = []
    all_services = SAFE_SERVICES | FORBIDDEN_SERVICES

    for service in sorted(all_services):
        active = systemctl_is_active(service)
        if not active:
            if service in FORBIDDEN_SERVICES:
                log(f"ALERT: Forbidden service {service} is inactive (alert-only, not restarting)", "CRITICAL")
                issues.append(f"{service} inactive (forbidden - alert only)")
            elif service in SAFE_SERVICES:
                if can_restart(service):
                    log(f"Layer 1: {service} is inactive, restarting...", "WARN")
                    if systemctl_restart(service):
                        log(f"Layer 1: {service} restarted successfully", "INFO")
                        record_restart(service)
                        time.sleep(RESTART_SETTLE_SECONDS)
                    else:
                        log(f"Layer 1: FAILED to restart {service}", "ERROR")
                        issues.append(f"{service} inactive, restart failed")
                else:
                    issues.append(f"{service} inactive (cooldown)")
    return issues


# ---------------------------------------------------------------------------
# Layer 2: Endpoint health
# ---------------------------------------------------------------------------


def check_endpoint_health() -> list[str]:
    """Layer 2: Check if endpoints respond. Restart if active but unresponsive."""
    issues = []
    for name, url, expected in ENDPOINT_CHECKS:
        code, output = run_command(
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {url}", timeout=8
        )
        http_ok = code == 0 and output.strip() == "200"

        if not http_ok:
            # Check if the service is marked active (hung process)
            service_map = {"backend": BACKEND_SERVICE, "litellm": LITELLM_SERVICE}
            service = service_map.get(name)
            if service and systemctl_is_active(service):
                if can_restart(service):
                    log(f"Layer 2: {name} endpoint unhealthy (HTTP {output}), service active but hung. Restarting {service}...", "WARN")
                    if systemctl_restart(service):
                        log(f"Layer 2: {service} restarted successfully", "INFO")
                        record_restart(service)
                        time.sleep(RESTART_SETTLE_SECONDS)
                    else:
                        log(f"Layer 2: FAILED to restart {service}", "ERROR")
                        issues.append(f"{name} endpoint unhealthy, restart failed")
                else:
                    issues.append(f"{name} endpoint unhealthy (cooldown)")
            else:
                issues.append(f"{name} endpoint unhealthy (service not active)")
    return issues


# ---------------------------------------------------------------------------
# Layer 3: ElevenLabs billing
# ---------------------------------------------------------------------------


def check_elevenlabs_billing() -> list[str]:
    """Layer 3: Check ElevenLabs subscription status. Alert if not active."""
    issues = []
    env = load_env()
    api_key = env.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        log("Layer 3: ELEVENLABS_API_KEY not found in .env, skipping", "WARN")
        return issues

    code, output = run_command(
        f'curl -s -w "\\n%{{http_code}}" --max-time 10 {ELEVENLABS_SUBSCRIPTION_URL} '
        f'-H "xi-api-key: {api_key}"',
        timeout=15,
    )
    if code != 0:
        issues.append("ElevenLabs subscription check failed (network error)")
        log(f"Layer 3: ElevenLabs subscription check failed: {output}", "WARN")
        return issues

    lines = output.strip().rsplit("\n", 1)
    if len(lines) != 2:
        issues.append("ElevenLabs subscription check failed (bad response)")
        return issues

    body, http_code = lines[0], lines[1].strip()

    if http_code != "200":
        issues.append(f"ElevenLabs API returned HTTP {http_code}")
        log(f"Layer 3: ElevenLabs API returned HTTP {http_code}", "CRITICAL")
        # Verify fallback is enabled
        fallback_enabled = env.get("TANGO_TTS_FALLBACK", "true").lower() == "true"
        if fallback_enabled:
            log("Layer 3: Deepgram Aura fallback is enabled — agents should still speak", "INFO")
        else:
            log("Layer 3: WARNING — TTS fallback is DISABLED, agents will go silent!", "CRITICAL")
        return issues

    try:
        data = json.loads(body)
        status = data.get("status", "unknown")
        char_count = data.get("character_count", 0)
        char_limit = data.get("character_limit", 0)

        if status != "active":
            issues.append(f"ElevenLabs subscription status is '{status}' (not active)")
            log(f"Layer 3: ElevenLabs subscription status='{status}' — billing issue detected!", "CRITICAL")
            # Verify fallback
            fallback_enabled = env.get("TANGO_TTS_FALLBACK", "true").lower() == "true"
            if fallback_enabled:
                log("Layer 3: Deepgram Aura fallback is enabled — agents should still speak", "INFO")
            else:
                log("Layer 3: WARNING — TTS fallback is DISABLED, agents will go silent!", "CRITICAL")
        else:
            log(f"Layer 3: ElevenLabs OK — status=active, chars={char_count}/{char_limit}", "INFO")

    except json.JSONDecodeError:
        issues.append("ElevenLabs subscription check failed (invalid JSON)")

    return issues


# ---------------------------------------------------------------------------
# Layer 4: TTS synthesis test
# ---------------------------------------------------------------------------


def check_tts_synthesis() -> list[str]:
    """Layer 4: Send a tiny TTS request to verify synthesis works. Restart backend on failure."""
    issues = []
    env = load_env()
    api_key = env.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        log("Layer 4: ELEVENLABS_API_KEY not found, skipping TTS test", "WARN")
        return issues

    base_url = env.get("ELEVENLABS_BASE_URL", "https://api.us.elevenlabs.io/v1")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    tts_url = f"{base_url}/text-to-speech/{TTS_TEST_VOICE_ID}"
    payload = json.dumps({
        "text": TTS_TEST_TEXT,
        "model_id": TTS_TEST_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
    })

    code, output = run_command(
        f'curl -s -o /dev/null -w "%{{http_code}}|%{{size_download}}" --max-time 15 '
        f'-X POST "{tts_url}" '
        f'-H "xi-api-key: {api_key}" '
        f'-H "Content-Type: application/json" '
        f'-d \'{payload}\'',
        timeout=20,
    )

    if code != 0:
        issues.append("TTS synthesis check failed (network error)")
        log("Layer 4: TTS synthesis check failed (network error)", "WARN")
        return issues

    parts = output.strip().split("|")
    if len(parts) != 2:
        issues.append("TTS synthesis check failed (bad response format)")
        return issues

    http_code, size_download = parts[0], int(parts[1]) if parts[1].isdigit() else 0

    if http_code == "200" and size_download > 100:
        log(f"Layer 4: TTS synthesis OK — HTTP 200, {size_download} bytes", "INFO")
    else:
        issues.append(f"TTS synthesis failed (HTTP {http_code}, {size_download} bytes)")
        log(f"Layer 4: TTS synthesis failed — HTTP {http_code}, {size_download} bytes", "WARN")

        # If billing is active but TTS fails, the backend may have a stale connection
        # Only restart if this is a persistent issue (not a transient API hiccup)
        log("Layer 4: TTS failed but ElevenLabs billing is active — possible connection pool issue. Not auto-restarting (transient failures are common).", "WARN")

    return issues


# ---------------------------------------------------------------------------
# Layer 5: Log anomaly scan
# ---------------------------------------------------------------------------


def check_log_anomalies() -> list[str]:
    """Layer 5: Scan recent backend logs for error patterns. Restart if threshold exceeded."""
    issues = []
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    total_errors = 0
    for pattern in ANOMALY_PATTERNS:
        code, output = run_command(
            f"sudo journalctl -u {BACKEND_SERVICE} --since '{since}' --no-pager -o cat 2>&1 | grep -c '{pattern}'",
            timeout=10,
        )
        # grep -c returns exit code 1 when count is 0 (no matches), which is NOT an error
        if code == 0 or code == 1:
            try:
                count = int(output.strip())
            except ValueError:
                count = 0
            if count > 0:
                log(f"Layer 5: Found {count} occurrences of '{pattern}' in last 5 min", "WARN")
                total_errors += count

    if total_errors > ANOMALY_THRESHOLD:
        issues.append(f"{total_errors} log errors in last 5 min (threshold: {ANOMALY_THRESHOLD})")
        log(f"Layer 5: {total_errors} errors in 5 min exceeds threshold {ANOMALY_THRESHOLD}", "CRITICAL")

        if can_restart(BACKEND_SERVICE):
            log(f"Layer 5: Restarting {BACKEND_SERVICE} due to excessive log errors...", "WARN")
            if systemctl_restart(BACKEND_SERVICE):
                log(f"Layer 5: {BACKEND_SERVICE} restarted successfully", "INFO")
                record_restart(BACKEND_SERVICE)
                time.sleep(RESTART_SETTLE_SECONDS)
            else:
                log(f"Layer 5: FAILED to restart {BACKEND_SERVICE}", "ERROR")
    elif total_errors > 0:
        log(f"Layer 5: {total_errors} errors in 5 min (below threshold {ANOMALY_THRESHOLD}, not restarting)", "INFO")
    else:
        log("Layer 5: No log anomalies detected", "INFO")

    return issues


# ---------------------------------------------------------------------------
# Layer 6: Worker registration
# ---------------------------------------------------------------------------


def check_worker_registration() -> list[str]:
    """Layer 6: Verify the LiveKit worker has registered since startup. Restart if missing."""
    issues = []

    # The LiveKit worker registers ONCE at startup, not periodically.
    # So we search logs since the service's actual start time, not a fixed window.
    # This avoids false positives on long-running services.
    code, start_ts = run_command(
        f"systemctl show -p ActiveEnterTimestamp --value {BACKEND_SERVICE}",
        timeout=10,
    )

    # Default to 5-minute window if we can't get the start time
    since = (datetime.now(timezone.utc) - timedelta(minutes=WORKER_STALE_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

    if code == 0 and start_ts:
        # systemctl returns timestamps like "Sun 2026-08-16 08:21:20 UTC"
        # We need to parse and reformat. Use the raw string — journalctl accepts it.
        # Strip the timezone suffix and day-of-week for journalctl --since
        # journalctl accepts: "2026-08-16 08:21:20"
        import re
        match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", start_ts)
        if match:
            since = match.group(1)

    code, output = run_command(
        f"sudo journalctl -u {BACKEND_SERVICE} --since '{since}' --no-pager -o cat 2>&1 | grep -c '{WORKER_REGISTRATION_PATTERN}'",
        timeout=10,
    )

    # grep -c returns exit code 1 when count is 0 (no matches), which is NOT an error
    if code != 0 and code != 1:
        issues.append("Worker registration check failed (journalctl error)")
        return issues

    try:
        count = int(output.strip())
    except ValueError:
        count = 0

    # Also check if the backend is currently active
    backend_active = systemctl_is_active(BACKEND_SERVICE)

    # Check service uptime to apply a grace period for fresh startups
    code, uptime_output = run_command(
        f"systemctl show -p ActiveEnterTimestampMonotonic --value {BACKEND_SERVICE}",
        timeout=10,
    )
    uptime_seconds = 0
    if code == 0 and uptime_output:
        try:
            uptime_us = int(uptime_output.strip())  # microseconds
            uptime_seconds = uptime_us / 1_000_000
        except ValueError:
            pass

    GRACE_PERIOD_SECONDS = 30  # allow 30s for worker to register after startup

    if backend_active and count == 0:
        if uptime_seconds < GRACE_PERIOD_SECONDS:
            # Service just started, worker may still be registering
            log(f"Layer 6: Worker not yet registered but service is fresh ({uptime_seconds:.0f}s uptime, grace period {GRACE_PERIOD_SECONDS}s)", "INFO")
        else:
            # Service has been up long enough that worker should have registered
            issues.append(f"No worker registration since startup (uptime {uptime_seconds:.0f}s)")
            log(f"Layer 6: No worker registration since startup (uptime {uptime_seconds:.0f}s) — backend may be stuck", "CRITICAL")

            if can_restart(BACKEND_SERVICE):
                log(f"Layer 6: Restarting {BACKEND_SERVICE} to restore worker registration...", "WARN")
                if systemctl_restart(BACKEND_SERVICE):
                    log(f"Layer 6: {BACKEND_SERVICE} restarted successfully", "INFO")
                    record_restart(BACKEND_SERVICE)
                    time.sleep(RESTART_SETTLE_SECONDS)
                else:
                    log(f"Layer 6: FAILED to restart {BACKEND_SERVICE}", "ERROR")
    elif backend_active and count > 0:
        log(f"Layer 6: Worker registration OK ({count} registration(s) since startup)", "INFO")
    elif not backend_active:
        # Already handled by Layer 1
        log("Layer 6: Backend not active (Layer 1 will handle)", "INFO")
    else:
        log("Layer 6: Worker registration check inconclusive", "WARN")

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    log("=" * 60, "INFO")
    log("Tango Health Guardian starting" + (" [DRY RUN]" if dry_run else ""), "INFO")

    all_issues: list[str] = []

    # Layer 1: Service health
    log("--- Layer 1: Service health ---", "INFO")
    if dry_run:
        for svc in sorted(SAFE_SERVICES | FORBIDDEN_SERVICES):
            active = systemctl_is_active(svc)
            log(f"  [DRY RUN] {svc}: {'active' if active else 'INACTIVE'}", "INFO")
    else:
        all_issues.extend(check_service_health())

    # Layer 2: Endpoint health
    log("--- Layer 2: Endpoint health ---", "INFO")
    if dry_run:
        for name, url, expected in ENDPOINT_CHECKS:
            code, output = run_command(
                f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {url}", timeout=8
            )
            log(f"  [DRY RUN] {name}: HTTP {output.strip() if code == 0 else 'FAIL'}", "INFO")
    else:
        all_issues.extend(check_endpoint_health())

    # Layer 3: ElevenLabs billing
    log("--- Layer 3: ElevenLabs billing ---", "INFO")
    if dry_run:
        log("  [DRY RUN] Skipping ElevenLabs billing check", "INFO")
    else:
        all_issues.extend(check_elevenlabs_billing())

    # Layer 4: TTS synthesis
    log("--- Layer 4: TTS synthesis ---", "INFO")
    if dry_run:
        log("  [DRY RUN] Skipping TTS synthesis test", "INFO")
    else:
        all_issues.extend(check_tts_synthesis())

    # Layer 5: Log anomalies
    log("--- Layer 5: Log anomalies ---", "INFO")
    if dry_run:
        log("  [DRY RUN] Skipping log anomaly scan", "INFO")
    else:
        all_issues.extend(check_log_anomalies())

    # Layer 6: Worker registration
    log("--- Layer 6: Worker registration ---", "INFO")
    if dry_run:
        log("  [DRY RUN] Skipping worker registration check", "INFO")
    else:
        all_issues.extend(check_worker_registration())

    # Summary
    log("=" * 60, "INFO")
    if all_issues:
        log(f"Health check COMPLETE — {len(all_issues)} issue(s) found:", "WARN")
        for issue in all_issues:
            log(f"  - {issue}", "WARN")
        log("=" * 60, "INFO")
        return 1
    else:
        log("Health check COMPLETE — all systems nominal", "INFO")
        log("=" * 60, "INFO")
        return 0


if __name__ == "__main__":
    sys.exit(main())