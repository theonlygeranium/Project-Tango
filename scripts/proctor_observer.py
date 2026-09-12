"""
Proctor Observer Module
=======================
Silent observation and performance monitoring for the Schubert Fleet.

Tracks all interactions between themightymaven and agent bots, collects
performance metrics, and generates optimization proposals for The Architect.
"""

import asyncio
import json
import logging
import os
import re
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

import asyncpg

# ── Service registry: single source of truth for service names ──────────────
try:
    from service_registry import AGENT_TO_SERVICE
    SERVICE_MAP = AGENT_TO_SERVICE
except ImportError:
    SERVICE_MAP = {
        "admiral": "schubert-bot.service",
        "architect": "schubert-architect.service",
        "proctor": "schubert-proctor.service",
        "dr_voss": "schubert-dr-voss.service",
        "quartermaster": "schubert-quartermaster.service",
        "cartographer": "schubert-cartographer.service",
        "cortex": "cortex-bot.service",
    }

logger = logging.getLogger("proctor-observer")

# ── Constants ────────────────────────────────────────────────────────────────

HUMAN_OPERATOR_ID = int(os.environ.get("ADMIN_USER_ID", "1075596247966167131"))

AGENT_BOT_IDS = {
    int(os.environ.get("SCHUBERT_BOT_ID", "1538476585445892179")): "admiral",
    int(os.environ.get("ARCHITECT_BOT_ID", "1538766501035642890")): "architect",
    int(os.environ.get("QUARTERMASTER_BOT_ID", "1538817623045832746")): "quartermaster",
    int(os.environ.get("CARTOGRAPHER_BOT_ID", "1538818587119067206")): "cartographer",
    int(os.environ.get("DR_VOSS_BOT_ID", "1539047086597873684")): "dr_voss",
    int(os.environ.get("PROCTOR_BOT_ID", "1539047471899086988")): "proctor",
    int(os.environ.get("CORTEX_BOT_ID", "1539172849569243217")): "cortex",
}

AGENT_CHANNEL_IDS = {
    int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "1538476446157115442")): "admiral",
    int(os.environ.get("ARCHITECT_CHANNEL_ID", "1539473266400432208")): "architect",
    int(os.environ.get("QUARTERMASTER_CHANNEL_ID", "1538818248542396428")): "quartermaster",
    int(os.environ.get("CARTOGRAPHER_CHANNEL_ID", "1538818895706718269")): "cartographer",
    int(os.environ.get("DR_VOSS_CHANNEL_ID", "1539104998821068880")): "dr_voss",
    int(os.environ.get("PROCTOR_CHANNEL_ID", "1539159059071111190")): "proctor",
    int(os.environ.get("CORTEX_CHANNEL_ID", "1539173946698498088")): "cortex",
}

DELEGATION_CHANNEL_ID = int(os.environ.get("PROCTOR_DELEGATION_CHANNEL_ID", "1539159059071111190"))
ANALYSIS_CHANNEL_ID = int(os.environ.get("PROCTOR_ANALYSIS_CHANNEL_ID", "1539159060568342539"))

SENIOR_STAFF_CHANNEL_ID = int(os.environ.get("SENIOR_STAFF_CHANNEL_ID", "1539023116968398911"))


# ── Error Details ────────────────────────────────────────────────────────────

@dataclass
class ErrorDetails:
    """Details about an error detected in agent output."""
    agent_name: str
    error_type: str
    error_message: str
    timestamp: str
    context: str = ""
    severity: str = "error"


def parse_error_from_message(content: str, agent_name: str = "unknown") -> Optional[ErrorDetails]:
    """Parse an error from a Discord message content."""
    error_patterns = [
        (r"Traceback.*", "python_traceback", "critical"),
        (r"Error:.*", "error_message", "error"),
        (r"Exception:.*", "exception", "error"),
        (r"ImportError:.*", "import_error", "critical"),
        (r"ModuleNotFoundError:.*", "module_not_found", "critical"),
        (r"FAILED.*", "service_failure", "error"),
        (r"timed out.*", "timeout", "warn"),
        (r"PermissionError:.*", "permission_error", "error"),
        (r"ConnectionError:.*", "connection_error", "error"),
    ]

    for pattern, error_type, severity in error_patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return ErrorDetails(
                agent_name=agent_name,
                error_type=error_type,
                error_message=match.group()[:500],
                timestamp=datetime.now(timezone.utc).isoformat(),
                context=content[:200],
                severity=severity,
            )
    return None


def parse_error_from_journal(log_line: str, agent_name: str = "unknown") -> Optional[ErrorDetails]:
    """Parse an error from a systemd journal log line."""
    return parse_error_from_message(log_line, agent_name)


# ── Performance Tracker ──────────────────────────────────────────────────────

class PerformanceTracker:
    """Tracks performance metrics for fleet agent interactions."""

    def __init__(self, db_pool: Optional[asyncpg.Pool] = None):
        self.db_pool = db_pool
        self._interactions: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._response_times: Dict[str, list] = defaultdict(list)

    async def record_interaction(
        self,
        agent_name: str,
        response_time: float,
        tool_calls: int = 0,
        error: bool = False,
        timestamp: Optional[datetime] = None,
    ):
        """Record a single agent interaction."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        self._interactions[agent_name].append({
            "agent": agent_name,
            "response_time": response_time,
            "tool_calls": tool_calls,
            "error": error,
            "timestamp": timestamp.isoformat(),
        })

        self._response_times[agent_name].append(response_time)

        if error:
            self._error_counts[agent_name] += 1

    def get_stats(self, agent_name: str) -> dict:
        """Get performance statistics for an agent."""
        times = self._response_times.get(agent_name, [])
        interactions = self._interactions.get(agent_name, [])

        if not times:
            return {
                "agent": agent_name,
                "total_interactions": 0,
                "avg_response_time": 0,
                "error_rate": 0,
            }

        return {
            "agent": agent_name,
            "total_interactions": len(interactions),
            "avg_response_time": statistics.mean(times),
            "median_response_time": statistics.median(times),
            "min_response_time": min(times),
            "max_response_time": max(times),
            "error_count": self._error_counts.get(agent_name, 0),
            "error_rate": self._error_counts.get(agent_name, 0) / len(interactions),
        }

    def get_all_stats(self) -> list[dict]:
        """Get performance statistics for all agents."""
        agents = set(self._interactions.keys()) | set(self._response_times.keys())
        return [self.get_stats(agent) for agent in sorted(agents)]

    def check_thresholds(self) -> list[dict]:
        """Check if any agents exceed performance thresholds."""
        alerts = []
        thresholds = {
            "simple_response": 4.0,
            "single_tool": 10.0,
            "multi_tool": 20.0,
            "error_rate": 0.10,
            "llm_timeout_rate": 0.05,
        }

        for agent_name in self._interactions:
            stats = self.get_stats(agent_name)
            if stats["error_rate"] > thresholds["error_rate"]:
                alerts.append({
                    "agent": agent_name,
                    "metric": "error_rate",
                    "value": stats["error_rate"],
                    "threshold": thresholds["error_rate"],
                    "severity": "warn",
                })
            if stats["avg_response_time"] > thresholds["simple_response"]:
                alerts.append({
                    "agent": agent_name,
                    "metric": "avg_response_time",
                    "value": stats["avg_response_time"],
                    "threshold": thresholds["simple_response"],
                    "severity": "warn",
                })

        return alerts
