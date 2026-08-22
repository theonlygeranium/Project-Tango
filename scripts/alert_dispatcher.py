#!/usr/bin/env python3
"""
Alert Dispatcher — Unified Alert Routing for Project Tango
==========================================================

Forwards alerts to the n8n Alert Aggregation Hub at
``http://100.86.47.6:5678/webhook/tango-alert``.

Covers two caller generations:

* Pre-Nexus scripts (``tango-healthcheck.py``, ``scheduler.py``, Discord bots)
* Nexus Fleet ``health.alert`` events (``forward_nexus_health_alert``)

The dispatcher is synchronous, stdlib-only, and swallows HTTP failures so it
never breaks the caller. A local dedup cache is a second line of defense;
n8n also deduplicates for 30 minutes.

Author: Cursor Agent (via EdStratum Labs)
Created: 2026-08-20
Updated: 2026-08-22 — Nexus health.alert mapping after fleet rebuild
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = "/opt/Project-Tango/.env"

DEFAULT_WEBHOOK_URL = "http://100.86.47.6:5678/webhook/tango-alert"
HTTP_TIMEOUT_SECONDS = 10
DEDUP_TTL_SECONDS = 1800  # 30 minutes

_SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "CRITICAL": 3}

# Nexus Bus uses mixed severity labels (warning/error/healthy).
_NEXUS_SEVERITY_MAP = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARN": "WARN",
    "WARNING": "WARN",
    "CRITICAL": "CRITICAL",
    "ERROR": "CRITICAL",
    "FATAL": "CRITICAL",
    "OK": "INFO",
    "HEALTHY": "INFO",
    "PASS": "INFO",
}


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Load environment variables from the Project Tango .env file.

    Uses os.environ.setdefault so variables already present (e.g. from
    systemd) are not overwritten.
    """
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(env_path):
        env_path = ENV_FILE
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def n8n_alerts_enabled() -> bool:
    """Return True unless N8N_ALERT_ENABLED is an explicit falsey value."""
    load_env()
    return os.environ.get("N8N_ALERT_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def normalize_severity(value: Any, default: str = "WARN") -> str:
    """Map free-form severity strings onto the n8n hub vocabulary."""
    if value is None:
        return default
    mapped = _NEXUS_SEVERITY_MAP.get(str(value).strip().upper())
    return mapped or default


# ---------------------------------------------------------------------------
# Alert Dispatcher
# ---------------------------------------------------------------------------


class AlertDispatcher:
    """Unified alert dispatcher for the Project Tango ecosystem.

    Sends alerts to the n8n Alert Aggregation Hub via HTTP POST. Includes
    a deduplication cache with TTL to prevent alert storms.

    All HTTP failures are silently swallowed (logged to stderr) so that
    alert dispatch never breaks the calling service.
    """

    def __init__(self, webhook_url=None, dedup_ttl=DEDUP_TTL_SECONDS):
        """Initialize the alert dispatcher.

        Args:
            webhook_url: Override the n8n webhook URL. If None, reads from
                        N8N_ALERT_WEBHOOK_URL env var, falling back to
                        the default.
            dedup_ttl: Deduplication cache TTL in seconds. Defaults to
                      30 minutes (1800s).
        """
        load_env()
        self.webhook_url = webhook_url or os.environ.get(
            "N8N_ALERT_WEBHOOK_URL", DEFAULT_WEBHOOK_URL
        )
        self.dedup_ttl = dedup_ttl
        self._dedup_cache = {}  # key -> expiry timestamp

    # -- Deduplication ------------------------------------------------------

    def _dedup_key(self, source, alert_type, title):
        """Build a dedup cache key from the alert identity triple."""
        raw = f"{source}|{alert_type}|{title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_duplicate(self, source, alert_type, title):
        """Check if this alert was sent recently.

        Returns True if the alert is a duplicate (within the TTL window),
        False otherwise. Expired entries are pruned as a side effect.
        """
        key = self._dedup_key(source, alert_type, title)
        now = time.time()

        expired = [k for k, exp in self._dedup_cache.items() if exp < now]
        for k in expired:
            del self._dedup_cache[k]

        if key in self._dedup_cache:
            return True

        self._dedup_cache[key] = now + self.dedup_ttl
        return False

    # -- HTTP ---------------------------------------------------------------

    def _post(self, payload):
        """Send the alert payload to the n8n webhook via HTTP POST.

        Failures are logged to stderr but never raised.
        """
        try:
            import urllib.error
            import urllib.request

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS)
        except Exception as e:
            print(f"[alert_dispatcher] Failed to send alert: {e}", file=sys.stderr)

    # -- Core send ----------------------------------------------------------

    def _send(
        self,
        source,
        severity,
        alert_type,
        title,
        message,
        bot_name=None,
        metadata=None,
    ):
        """Build the unified payload and dispatch it.

        Applies enablement + deduplication before sending. Returns True if
        the alert was sent, False if it was skipped.
        """
        if not n8n_alerts_enabled():
            return False

        severity = normalize_severity(severity)
        if self._is_duplicate(source, alert_type, title):
            return False

        payload = {
            "source": source,
            "severity": severity,
            "alert_type": alert_type,
            "title": title,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if bot_name:
            payload["bot_name"] = bot_name
        if metadata:
            payload["metadata"] = metadata

        self._post(payload)
        return True

    # -- Convenience methods ------------------------------------------------

    def send_health_alert(self, message, severity="WARN", metadata=None):
        """Send a health check alert (for tango-healthcheck.py)."""
        return self._send(
            source="tango-healthcheck",
            severity=severity,
            alert_type="health_check",
            title="Tango Health Alert",
            message=message,
            bot_name="Tango Health Guardian",
            metadata=metadata,
        )

    def send_deployment_alert(
        self, title, message, bot_name="The Architect", status="info", metadata=None
    ):
        """Send a deployment alert (for architect-bot.py)."""
        severity = "INFO" if status in ("info", "success") else "WARN"
        return self._send(
            source="architect-bot",
            severity=severity,
            alert_type="deployment",
            title=title,
            message=message,
            bot_name=bot_name,
            metadata=metadata,
        )

    def send_service_alert(
        self, service_name, event_type, previous_state, current_state, metadata=None
    ):
        """Send a service state change alert (for scheduler.py)."""
        severity = (
            "CRITICAL"
            if current_state in ("failed", "inactive", "dead")
            else "WARN"
        )
        title = f"Service {service_name} {event_type}"
        message = f"{service_name}: {previous_state} -> {current_state}"
        return self._send(
            source="scheduler",
            severity=severity,
            alert_type="service_failed",
            title=title,
            message=message,
            bot_name=None,
            metadata=metadata,
        )

    def send_performance_report(
        self, title, message, bot_name="The Proctor", metadata=None
    ):
        """Send a performance report (for fleet_health_monitor.py)."""
        return self._send(
            source="fleet-health-monitor",
            severity="INFO",
            alert_type="performance_report",
            title=title,
            message=message,
            bot_name=bot_name,
            metadata=metadata,
        )

    def send_self_heal(self, message, bot_name, metadata=None):
        """Send a self-healing notification (for bot self-remediation)."""
        return self._send(
            source=bot_name,
            severity="INFO",
            alert_type="self_heal",
            title=f"{bot_name} self-healed",
            message=message,
            bot_name=bot_name,
            metadata=metadata,
        )

    def send_escalation(
        self, issue_id, message, bot_name, is_critical=False, metadata=None
    ):
        """Send an escalation alert (for bot escalations to humans)."""
        severity = "CRITICAL" if is_critical else "WARN"
        title = f"Escalation: {issue_id}"
        return self._send(
            source=bot_name,
            severity=severity,
            alert_type="escalation",
            title=title,
            message=message,
            bot_name=bot_name,
            metadata=metadata,
        )

    def send_generic(
        self,
        source,
        severity,
        alert_type,
        title,
        message,
        bot_name=None,
        metadata=None,
    ):
        """Send a raw alert with full control over all fields."""
        return self._send(
            source=source,
            severity=severity,
            alert_type=alert_type,
            title=title,
            message=message,
            bot_name=bot_name,
            metadata=metadata,
        )

    def send_nexus_health_alert(self, payload: dict[str, Any] | None) -> bool:
        """Map a Nexus Bus ``health.alert`` payload onto the n8n schema."""
        data = payload or {}
        bot_id = str(data.get("bot_id") or data.get("source") or "nexus")
        alert_type = str(data.get("alert_type") or "health.alert")
        message = str(data.get("message") or data.get("error_message") or alert_type)
        details = data.get("details")
        if not isinstance(details, dict):
            details = {}
        title = str(details.get("title") or f"{alert_type} ({bot_id})")
        metadata = {
            "nexus_event": "health.alert",
            "bot_id": bot_id,
            **details,
        }
        return self._send(
            source=f"nexus:{bot_id}",
            severity=normalize_severity(data.get("severity"), "WARN"),
            alert_type=alert_type,
            title=title,
            message=message,
            bot_name=bot_id,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_dispatcher_instance = None


def get_dispatcher():
    """Get or create a singleton AlertDispatcher instance."""
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = AlertDispatcher()
    return _dispatcher_instance


def forward_nexus_health_alert(payload: dict[str, Any] | None) -> bool:
    """Module-level helper for Nexus FleetBot ``_handle_health_alert``."""
    try:
        return get_dispatcher().send_nexus_health_alert(payload)
    except Exception as exc:
        print(f"[alert_dispatcher] Nexus forward failed: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main — send a test alert
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    print("Sending test alert to n8n Alert Aggregation Hub...")
    dispatcher = AlertDispatcher()
    sent = dispatcher.send_generic(
        source="alert-dispatcher",
        severity="INFO",
        alert_type="health_check",
        title="Test Alert",
        message="This is a test alert from alert_dispatcher.py __main__ block.",
        bot_name="Alert Dispatcher",
        metadata={"test": True, "pid": os.getpid()},
    )
    if sent:
        print("Test alert sent successfully.")
    else:
        print("Test alert was skipped (disabled or recently deduplicated).")
