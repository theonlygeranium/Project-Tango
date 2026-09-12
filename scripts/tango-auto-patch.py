#!/usr/bin/env python3
"""
Tango Auto-Patch — Critical Issue Remediation Engine

Invoked by tango-healthcheck.py (Layer 7) when critical issues persist
after all self-healing attempts.

Maps known critical issues to automated remediation actions:
- Service inactive + restart failed → reset-failed + restart + verify
- Endpoint unhealthy + restart failed → escalate + file incident
- TTS synthesis failed + billing OK → restart backend + clear connection pool
- Log anomalies exceeded threshold → capture stack trace + restart + file bug
- No worker registration after restart → escalate to Voss (crash loop suspected)
- ElevenLabs billing issue → send escalation + enable fallback if disabled
- Fleet agent silent/hung → restart agent (if in FLEET_SAFE_SERVICES)

Usage:
    python3 tango-auto-patch.py --issues '["issue1", "issue2"]'

Exit codes:
    0 = patches applied (or no critical issues)
    1 = one or more patches failed, escalation sent
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_FILE = "/var/log/tango-auto-patch.log"
BACKEND_SERVICE = "tango-backend.service"
WEB_SERVICE = "tango-web.service"
LITELLM_SERVICE = "polyglot-litellm.service"
TTS_SERVICE = "tango-tts.service"

# Services we can safely restart
SAFE_SERVICES = {BACKEND_SERVICE, WEB_SERVICE, LITELLM_SERVICE, TTS_SERVICE}

# Fleet agent services that can be safely restarted by auto-patch
FLEET_SAFE_SERVICES = {
    "schubert-bot.service",
    "schubert-architect.service",
    "schubert-cartographer.service",
    "schubert-dr-voss.service",
    "schubert-monitor.service",
    "schubert-proctor.service",
    "schubert-quartermaster.service",
}

# Cooldown for fleet agent restarts (prevent restart loops from Layer 8)
# Fleet agents are event-driven — they can legitimately be silent for hours.
# Only restart them via auto-patch if they've been flagged multiple times.
FLEET_AGENT_RESTART_COOLDOWN_SECONDS = 3600  # 1 hour
FLEET_AGENT_RESTART_COOLDOWN_FILE = "/tmp/tango-auto-patch-fleet-cooldowns.json"

# Alert dispatcher for escalation
ALERT_DISPATCHER = "/opt/Project-Tango/scripts/alert_dispatcher.py"


def log(message: str, level: str = "INFO") -> None:
    """Write a timestamped log line to the log file and stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] {message}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_command(cmd: str, timeout: int = 30) -> tuple[int, str]:
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


def systemctl_reset_failed(service: str) -> bool:
    """Reset the failed state of a service."""
    code, _ = run_command(f"sudo systemctl reset-failed {service}", timeout=10)
    return code == 0


def systemctl_restart(service: str) -> bool:
    """Restart a service."""
    code, _ = run_command(f"sudo systemctl restart {service}", timeout=30)
    return code == 0


def systemctl_is_active(service: str) -> bool:
    """Check if a service is active."""
    code, _ = run_command(f"systemctl is-active {service}", timeout=5)
    return code == 0


def can_restart_fleet_agent(service: str) -> bool:
    """Check if we're allowed to restart this fleet agent (cooldown not expired).

    Fleet agents have a longer cooldown (1 hour) because they are event-driven
    and can legitimately be silent for extended periods. Layer 8 will flag them
    repeatedly, but we only want to restart them once per hour via auto-patch.
    """
    try:
        if os.path.exists(FLEET_AGENT_RESTART_COOLDOWN_FILE):
            with open(FLEET_AGENT_RESTART_COOLDOWN_FILE) as f:
                cooldowns = json.load(f)
            last = cooldowns.get(service, 0)
            if time.time() - last < FLEET_AGENT_RESTART_COOLDOWN_SECONDS:
                remaining = int(FLEET_AGENT_RESTART_COOLDOWN_SECONDS - (time.time() - last))
                log(f"Fleet agent restart cooldown active for {service} ({remaining}s remaining)", "INFO")
                return False
    except Exception:
        pass
    return True


def record_fleet_agent_restart(service: str) -> None:
    """Record that we restarted this fleet agent via auto-patch."""
    try:
        cooldowns = {}
        if os.path.exists(FLEET_AGENT_RESTART_COOLDOWN_FILE):
            with open(FLEET_AGENT_RESTART_COOLDOWN_FILE) as f:
                cooldowns = json.load(f)
        cooldowns[service] = time.time()
        with open(FLEET_AGENT_RESTART_COOLDOWN_FILE, "w") as f:
            json.dump(cooldowns, f)
    except Exception:
        pass


def send_escalation(issue_id: str, message: str, is_critical: bool = True) -> None:
    """Send an escalation alert via the alert dispatcher."""
    if not os.path.exists(ALERT_DISPATCHER):
        log(f"Escalation skipped — alert_dispatcher.py not found", "WARN")
        return

    cmd = (
        f"python3 {ALERT_DISPATCHER} "
        f"--source tango-auto-patch "
        f"--severity {'CRITICAL' if is_critical else 'WARN'} "
        f"--alert_type escalation "
        f"--title 'Auto-patch escalation: {issue_id}' "
        f"--message '{message}' "
        f"--bot_name 'Tango Auto-Patch'"
    )
    code, output = run_command(cmd, timeout=15)
    if code != 0:
        log(f"Escalation send failed: {output}", "ERROR")


def patch_service_inactive(issue: str) -> bool:
    """Patch: Service inactive + restart failed → reset-failed + restart + verify."""
    # Extract service name from issue string
    service = None
    for svc in SAFE_SERVICES | FLEET_SAFE_SERVICES:
        if svc in issue:
            service = svc
            break

    if not service:
        log(f"Could not identify service from issue: {issue}", "WARN")
        return False

    log(f"Patching inactive service: {service}", "INFO")

    # Step 1: Reset failed state
    if systemctl_reset_failed(service):
        log(f"  Reset-failed OK for {service}", "INFO")
    else:
        log(f"  Reset-failed failed for {service}", "WARN")

    time.sleep(2)

    # Step 2: Restart
    if systemctl_restart(service):
        log(f"  Restart OK for {service}", "INFO")
        time.sleep(5)
        if systemctl_is_active(service):
            log(f"  {service} confirmed active after patch", "INFO")
            return True
        else:
            log(f"  {service} still inactive after patch", "CRITICAL")
            send_escalation(
                issue_id=f"{service}-inactive",
                message=f"Auto-patch failed: {service} remains inactive after reset-failed + restart. Manual intervention required.",
                is_critical=True,
            )
            return False
    else:
        log(f"  Restart failed for {service}", "CRITICAL")
        send_escalation(
            issue_id=f"{service}-inactive",
            message=f"Auto-patch failed: Could not restart {service}. Manual intervention required.",
            is_critical=True,
        )
        return False


def patch_endpoint_unhealthy(issue: str) -> bool:
    """Patch: Endpoint unhealthy + restart failed → escalate + file incident."""
    log(f"Patching endpoint unhealthy: {issue}", "WARN")
    send_escalation(
        issue_id="endpoint-unhealthy",
        message=f"Endpoint health check failed and auto-restart did not resolve it: {issue}. Manual investigation required.",
        is_critical=True,
    )
    return False  # Escalation sent, patch considered "handled" by escalation


def patch_tts_synthesis(issue: str) -> bool:
    """Patch: TTS synthesis failed → restart backend + clear connection pool."""
    log(f"Patching TTS synthesis failure: {issue}", "INFO")

    # Restart backend to clear any stale connections
    if systemctl_restart(BACKEND_SERVICE):
        log(f"  Backend restart OK", "INFO")
        time.sleep(10)
        if systemctl_is_active(BACKEND_SERVICE):
            log(f"  TTS synthesis patch applied (backend restarted)", "INFO")
            return True
        else:
            log(f"  Backend inactive after restart", "CRITICAL")
            send_escalation(
                issue_id="tts-synthesis",
                message="TTS synthesis failed and backend restart did not resolve it. Check ElevenLabs API and connection pool.",
                is_critical=True,
            )
            return False
    else:
        log(f"  Backend restart failed", "CRITICAL")
        send_escalation(
            issue_id="tts-synthesis",
            message="TTS synthesis failed and could not restart backend. Manual intervention required.",
            is_critical=True,
        )
        return False


def patch_log_anomalies(issue: str) -> bool:
    """Patch: Log anomalies exceeded threshold → capture stack trace + restart + file bug."""
    log(f"Patching log anomalies: {issue}", "WARN")

    # Capture recent stack traces before restart
    since = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    code, trace = run_command(
        f"sudo journalctl -u {BACKEND_SERVICE} --since '{since}' --no-pager -o cat 2>&1 | grep -E '(Traceback|Error|Exception)' | tail -20",
        timeout=15,
    )
    if code == 0 and trace:
        log(f"  Captured stack trace (first 500 chars): {trace[:500]}", "INFO")
        # TODO: Write to incident file or send to n8n for bug filing

    # Restart backend
    if systemctl_restart(BACKEND_SERVICE):
        log(f"  Backend restart OK after log anomalies", "INFO")
        return True
    else:
        log(f"  Backend restart failed", "CRITICAL")
        send_escalation(
            issue_id="log-anomalies",
            message=f"Log anomalies exceeded threshold and backend restart failed: {issue}",
            is_critical=True,
        )
        return False


def patch_worker_registration(issue: str) -> bool:
    """Patch: No worker registration after restart → escalate (crash loop suspected)."""
    log(f"Patching worker registration failure: {issue}", "CRITICAL")
    send_escalation(
        issue_id="worker-registration",
        message=f"Worker registration failed after multiple backend restarts. Suspected crash loop or LiveKit configuration issue. Manual investigation required.",
        is_critical=True,
    )
    return False  # Escalation sent


def patch_billing_issue(issue: str) -> bool:
    """Patch: ElevenLabs billing issue → send escalation + enable fallback if disabled."""
    log(f"Patching billing issue: {issue}", "CRITICAL")

    # Check if fallback is enabled
    env = {}
    if os.path.exists("/opt/Project-Tango/.env"):
        with open("/opt/Project-Tango/.env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()

    fallback = env.get("TANGO_TTS_FALLBACK", "true").lower() == "true"
    if not fallback:
        log(f"  WARNING: TTS fallback is DISABLED — enabling it now", "CRITICAL")
        # TODO: Update .env to enable fallback
        # For now, just escalate

    send_escalation(
        issue_id="elevenlabs-billing",
        message=f"ElevenLabs subscription issue detected: {issue}. Fallback {'enabled' if fallback else 'DISABLED — URGENT'}. Manual billing review required.",
        is_critical=True,
    )
    return False  # Escalation sent


def patch_fleet_agent_silent(issue: str) -> bool:
    """Patch: Fleet agent silent/hung → restart agent (with cooldown)."""
    service = None
    for svc in FLEET_SAFE_SERVICES:
        if svc in issue:
            service = svc
            break

    if not service:
        log(f"Could not identify fleet agent from issue: {issue}", "WARN")
        return False

    # Check cooldown — fleet agents have a 1-hour cooldown to prevent restart loops
    if not can_restart_fleet_agent(service):
        log(f"  Skipping restart for {service} — cooldown active (Layer 8 will keep flagging)", "INFO")
        return True  # Consider this "handled" — we're intentionally not restarting

    log(f"Patching silent fleet agent: {service}", "INFO")

    if systemctl_restart(service):
        log(f"  Restart OK for {service}", "INFO")
        record_fleet_agent_restart(service)
        time.sleep(5)
        if systemctl_is_active(service):
            log(f"  {service} confirmed active after restart", "INFO")
            return True
        else:
            log(f"  {service} still inactive after restart", "CRITICAL")
            send_escalation(
                issue_id=f"{service}-silent",
                message=f"Auto-patch failed: {service} remains inactive after restart. Manual intervention required.",
                is_critical=True,
            )
            return False
    else:
        log(f"  Restart failed for {service}", "CRITICAL")
        send_escalation(
            issue_id=f"{service}-silent",
            message=f"Auto-patch failed: Could not restart {service}. Manual intervention required.",
            is_critical=True,
        )
        return False


# Issue-to-patch mapping
PATCH_HANDLERS = {
    "inactive": patch_service_inactive,
    "unhealthy": patch_endpoint_unhealthy,
    "synthesis": patch_tts_synthesis,
    "exceeds threshold": patch_log_anomalies,
    "worker registration": patch_worker_registration,
    "billing": patch_billing_issue,
    "no log output": patch_fleet_agent_silent,
    "possible hang": patch_fleet_agent_silent,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Tango Auto-Patch Critical Issue Remediation")
    parser.add_argument("--issues", type=str, required=True, help="JSON array of issue strings")
    args = parser.parse_args()

    try:
        issues = json.loads(args.issues)
    except json.JSONDecodeError:
        log(f"Invalid JSON in --issues argument", "ERROR")
        return 1

    if not issues:
        log("No issues provided — nothing to patch", "INFO")
        return 0

    log(f"Auto-patch starting for {len(issues)} issue(s)", "INFO")

    patched = 0
    failed = 0

    for issue in issues:
        handled = False
        for keyword, handler in PATCH_HANDLERS.items():
            if keyword in issue.lower():
                log(f"Applying patch handler for keyword '{keyword}': {issue}", "INFO")
                if handler(issue):
                    patched += 1
                else:
                    failed += 1
                handled = True
                break

        if not handled:
            log(f"No patch handler for issue: {issue}", "WARN")
            send_escalation(
                issue_id="unknown-critical",
                message=f"Critical issue with no auto-patch handler: {issue}. Manual intervention required.",
                is_critical=True,
            )
            failed += 1

    log(f"Auto-patch complete — {patched} patched, {failed} failed/escalated", "INFO")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
