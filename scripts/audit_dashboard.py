#!/usr/bin/env python3
"""
Audit Dashboard — Schubert Bot Ecosystem Monitor
=================================================
A FastAPI web application that provides a real-time dashboard for the
Schubert Bot V2 ecosystem. Reads from:

  - PostgreSQL (tango database): memory stats, entity breakdowns,
    event types, memory growth over time, top entities, recent events
  - Architect metrics JSON: LLM call counts, tool calls, latencies,
    auto-update history, heal events, escalations
  - systemd: service status for all core services
  - LiteLLM: model availability and endpoint health
  - Docker: container status

The dashboard auto-refreshes every 30 seconds. No external dependencies
beyond what's already in the venv (fastapi, uvicorn, psycopg2, aiohttp).

Usage:
    python3 audit_dashboard.py
    # Or via systemd: schubert-audit-dashboard.service

Configuration via environment variables:
    DASHBOARD_HOST  — bind address (default 127.0.0.1)
    DASHBOARD_PORT  — bind port (default 8096)
    POSTGRES_HOST   — Postgres socket path (default /var/run/postgresql)
    POSTGRES_DB     — database name (default tango)
    POSTGRES_USER   — database user (default root)
    LITELLM_URL     — LiteLLM endpoint (default http://127.0.0.1:4000/v1)
    LITELLM_MASTER_KEY — LiteLLM auth key
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8096"))

PG_HOST = os.environ.get("POSTGRES_HOST", "/var/run/postgresql")
PG_DB = os.environ.get("POSTGRES_DB", "tango")
PG_USER = os.environ.get("POSTGRES_USER", "root")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

LITELLM_URL = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

METRICS_FILE = "/opt/Project-Tango/scripts/.architect-metrics.json"
UPDATE_HISTORY_FILE = "/opt/Project-Tango/scripts/.architect-updates.json"

MONITORED_SERVICES = [
    ("schubert-bot", True),
    ("schubert-architect", True),
    ("github-mcp-server", True),
    ("gmail-mcp-freelance", False),
    ("caddy", True),
    ("cloudflared", True),
    ("ollama", False),
    ("docker", True),
    ("postgresql", True),
]

app = FastAPI(title="Schubert Audit Dashboard")

# ---------------------------------------------------------------------------
# Data collection helpers
# ---------------------------------------------------------------------------


def get_pg_conn():
    kwargs = {"host": PG_HOST, "dbname": PG_DB, "user": PG_USER}
    if PG_PASSWORD:
        kwargs["password"] = PG_PASSWORD
    return psycopg2.connect(**kwargs)


def run_cmd(cmd: str, timeout: int = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)


def collect_memory_stats() -> dict:
    """Collect memory statistics from Postgres."""
    stats: dict[str, Any] = {}
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memory_vectors")
            stats["vectors"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_entities")
            stats["entities"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_facts")
            stats["facts"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_events")
            stats["events"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_relationships")
            stats["relationships"] = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        stats["error"] = str(e)
    return stats


def collect_entity_breakdown() -> list[dict]:
    """Entity type breakdown for pie chart."""
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type, count(*) FROM memory_entities "
                "GROUP BY type ORDER BY count DESC"
            )
            rows = cur.fetchall()
        conn.close()
        return [{"label": r[0], "value": r[1]} for r in rows]
    except Exception:
        return []


def collect_event_breakdown() -> list[dict]:
    """Event type breakdown for bar chart."""
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, count(*) FROM memory_events "
                "GROUP BY event_type ORDER BY count DESC"
            )
            rows = cur.fetchall()
        conn.close()
        return [{"label": r[0], "value": r[1]} for r in rows]
    except Exception:
        return []


def collect_memory_growth() -> list[dict]:
    """Daily memory growth over last 30 days for line chart."""
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date_trunc('day', created_at) as day, count(*) "
                "FROM memory_events "
                "WHERE created_at > NOW() - INTERVAL '30 days' "
                "GROUP BY day ORDER BY day"
            )
            rows = cur.fetchall()
        conn.close()
        return [
            {"date": r[0].strftime("%Y-%m-%d"), "count": r[1]} for r in rows
        ]
    except Exception:
        return []


def collect_top_entities() -> list[dict]:
    """Top entities by fact count."""
    try:
        conn = get_pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT e.name, e.type, COUNT(f.id) as fact_count "
                "FROM memory_entities e "
                "LEFT JOIN memory_facts f ON f.entity_id = e.id "
                "GROUP BY e.id, e.name, e.type "
                "ORDER BY fact_count DESC LIMIT 15"
            )
            rows = cur.fetchall()
        conn.close()
        return [{"name": r["name"], "type": r["type"], "facts": r["fact_count"]} for r in rows]
    except Exception:
        return []


def collect_recent_events() -> list[dict]:
    """Recent memory events."""
    try:
        conn = get_pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT event_type, project, summary, "
                "array_to_string(entities, ', ') as entities_str, "
                "created_at "
                "FROM memory_events "
                "ORDER BY created_at DESC LIMIT 20"
            )
            rows = cur.fetchall()
        conn.close()
        return [
            {
                "event_type": r["event_type"],
                "project": r["project"] or "",
                "summary": (r["summary"] or "")[:120],
                "entities": r["entities_str"] or "",
                "timestamp": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
            }
            for r in rows
        ]
    except Exception:
        return []


def collect_service_status() -> list[dict]:
    """Check systemd service status."""
    services = []
    for svc_name, is_critical in MONITORED_SERVICES:
        code, status = run_cmd(f"systemctl is-active {svc_name} 2>/dev/null")
        active = status.strip() == "active"
        services.append(
            {
                "name": svc_name,
                "critical": is_critical,
                "status": status.strip() or "unknown",
                "active": active,
            }
        )
    return services


def collect_system_info() -> dict:
    """Collect system resource info."""
    info: dict[str, Any] = {}

    # Disk usage
    code, output = run_cmd("df -h / --output=pcent,avail 2>/dev/null | tail -1")
    if code == 0 and output:
        parts = output.strip().split()
        info["disk_pct"] = parts[0] if parts else "?"
        info["disk_avail"] = parts[1] if len(parts) > 1 else "?"

    # Memory usage
    code, output = run_cmd("free -h 2>/dev/null | grep Mem")
    if code == 0 and output:
        parts = output.strip().split()
        if len(parts) >= 4:
            info["mem_total"] = parts[1]
            info["mem_used"] = parts[2]
            info["mem_avail"] = parts[-1]

    # CPU load
    code, output = run_cmd("cat /proc/loadavg 2>/dev/null")
    if code == 0 and output:
        info["load_avg"] = output.strip().split()[:3]

    # Uptime
    code, output = run_cmd("uptime -p 2>/dev/null")
    if code == 0 and output:
        info["uptime"] = output.strip().replace("up ", "")

    # CPU usage
    code, output = run_cmd("top -bn1 | grep 'Cpu(s)' 2>/dev/null")
    if code == 0 and output:
        info["cpu_line"] = output.strip()

    return info


def collect_architect_metrics() -> dict:
    """Read the architect metrics JSON file."""
    try:
        with open(METRICS_FILE, "r") as f:
            data = json.load(f)

        result: dict[str, Any] = {"totals": data.get("totals", {})}

        # Process LLM latencies
        latencies = data.get("llm_latencies", [])
        if latencies:
            latency_values = [l["latency"] for l in latencies]
            result["llm_latency_avg"] = round(sum(latency_values) / len(latency_values), 2)
            result["llm_latency_max"] = round(max(latency_values), 2)
            result["llm_latency_min"] = round(min(latency_values), 2)
            result["llm_latency_count"] = len(latency_values)

            # Group by model
            by_model: dict[str, list[float]] = {}
            for l in latencies:
                model = l.get("model", "unknown")
                by_model.setdefault(model, []).append(l["latency"])
            result["llm_by_model"] = {
                m: {
                    "avg": round(sum(v) / len(v), 2),
                    "max": round(max(v), 2),
                    "count": len(v),
                }
                for m, v in by_model.items()
            }

        # Daily breakdown (last 7 days)
        daily = data.get("daily", {})
        if daily:
            sorted_days = sorted(daily.items(), key=lambda x: x[0], reverse=True)[:7]
            result["daily"] = dict(sorted_days)

        return result
    except FileNotFoundError:
        return {"error": "Metrics file not found", "totals": {}}
    except Exception as e:
        return {"error": str(e), "totals": {}}


def collect_update_history() -> list[dict]:
    """Read the architect auto-update history."""
    try:
        with open(UPDATE_HISTORY_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-10:]  # Last 10 updates
        elif isinstance(data, dict):
            history = data.get("history", [])
            return history[-10:] if history else []
        return []
    except Exception:
        return []


def collect_docker_status() -> list[dict]:
    """Check Docker container status."""
    code, output = run_cmd(
        "docker ps -a --format '{{.Names}}|{{.Status}}|{{.Ports}}' 2>/dev/null | head -20"
    )
    if code != 0 or not output:
        return []
    containers = []
    for line in output.strip().split("\n"):
        parts = line.split("|")
        if len(parts) >= 2:
            name = parts[0]
            status = parts[1]
            is_running = "Up" in status
            containers.append(
                {
                    "name": name,
                    "status": status,
                    "running": is_running,
                }
            )
    return containers


def collect_litellm_status() -> dict:
    """Check LiteLLM endpoint and available models."""
    result: dict[str, Any] = {"healthy": False, "models": []}
    try:
        import urllib.request

        url = f"{LITELLM_URL}/models"
        req = urllib.request.Request(url)
        if LITELLM_MASTER_KEY:
            req.add_header("Authorization", f"Bearer {LITELLM_MASTER_KEY}")

        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m.get("id", "?") for m in data.get("data", [])]
            result["healthy"] = True
            result["models"] = models[:20]
            result["model_count"] = len(models)
    except Exception as e:
        result["error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


def collect_change_log() -> list[dict]:
    """Recent change_log entries from all actors."""
    try:
        conn = get_pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, actor, action, target, description, intent, "
                "outcome, created_at "
                "FROM change_log "
                "ORDER BY created_at DESC LIMIT 25"
            )
            rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "actor": r["actor"] or "",
                "action": r["action"] or "",
                "target": (r["target"] or "")[:60],
                "description": (r["description"] or "")[:120],
                "outcome": r["outcome"] or "pending",
                "timestamp": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
            }
            for r in rows
        ]
    except Exception:
        return []


@app.get("/api/stats")
async def api_stats():
    """JSON API endpoint returning all dashboard data."""
    return {
        "memory": collect_memory_stats(),
        "entity_breakdown": collect_entity_breakdown(),
        "event_breakdown": collect_event_breakdown(),
        "memory_growth": collect_memory_growth(),
        "top_entities": collect_top_entities(),
        "recent_events": collect_recent_events(),
        "services": collect_service_status(),
        "system": collect_system_info(),
        "architect_metrics": collect_architect_metrics(),
        "update_history": collect_update_history(),
        "docker": collect_docker_status(),
        "litellm": collect_litellm_status(),
        "change_log": collect_change_log(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
async def api_health():
    """Simple health check."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Schubert Audit Dashboard</title>
<meta http-equiv="refresh" content="30">
<style>
  :root {
    --bg: #0f1117;
    --card-bg: #1a1d29;
    --card-border: #2a2e3f;
    --text: #e1e4ed;
    --text-dim: #8b8fa8;
    --accent: #5b8def;
    --accent-dim: #3a6bcf;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
    --orange: #fb923c;
    --purple: #c084fc;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    padding: 20px;
    min-height: 100vh;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--card-border);
  }
  .header h1 {
    font-size: 24px;
    font-weight: 600;
  }
  .header .meta {
    font-size: 13px;
    color: var(--text-dim);
    text-align: right;
  }
  .header .meta .refresh {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .header .meta .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
    margin-bottom: 20px;
  }
  .card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    padding: 20px;
  }
  .card h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-dim);
    margin-bottom: 16px;
  }
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 12px;
  }
  .stat {
    text-align: center;
    padding: 12px 8px;
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
  }
  .stat .value {
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
  }
  .stat .label {
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .service-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--card-border);
    font-size: 14px;
  }
  .service-row:last-child { border-bottom: none; }
  .service-name { font-weight: 500; }
  .service-name .critical {
    color: var(--orange);
    font-size: 11px;
    margin-left: 6px;
  }
  .badge {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .badge.active { background: rgba(74,222,128,0.15); color: var(--green); }
  .badge.inactive { background: rgba(248,113,113,0.15); color: var(--red); }
  .badge.warning { background: rgba(251,191,36,0.15); color: var(--yellow); }
  .table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .table th {
    text-align: left;
    color: var(--text-dim);
    padding: 8px;
    border-bottom: 1px solid var(--card-border);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.05em;
  }
  .table td {
    padding: 8px;
    border-bottom: 1px solid var(--card-border);
  }
  .table tr:hover { background: rgba(255,255,255,0.02); }
  .bar-chart {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .bar-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .bar-label {
    width: 130px;
    font-size: 13px;
    text-align: right;
    color: var(--text-dim);
    flex-shrink: 0;
  }
  .bar-track {
    flex: 1;
    height: 22px;
    background: rgba(255,255,255,0.05);
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    border-radius: 4px;
    display: flex;
    align-items: center;
    padding-left: 8px;
    font-size: 11px;
    font-weight: 600;
    color: var(--bg);
    transition: width 0.5s ease;
  }
  .bar-fill.blue { background: var(--accent); }
  .bar-fill.green { background: var(--green); }
  .bar-fill.purple { background: var(--purple); }
  .bar-fill.orange { background: var(--orange); }
  .bar-fill.yellow { background: var(--yellow); }
  .line-chart {
    height: 200px;
    position: relative;
  }
  .line-chart svg {
    width: 100%;
    height: 100%;
  }
  .latency-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    font-size: 13px;
    border-bottom: 1px solid var(--card-border);
  }
  .latency-row:last-child { border-bottom: none; }
  .latency-model { color: var(--purple); font-weight: 500; }
  .latency-vals { color: var(--text-dim); }
  .event-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .event-badge.conversation { background: rgba(91,141,239,0.15); color: var(--accent); }
  .event-badge.tool { background: rgba(192,132,252,0.15); color: var(--purple); }
  .event-badge.system { background: rgba(251,191,36,0.15); color: var(--yellow); }
  .event-badge.deployment { background: rgba(74,222,128,0.15); color: var(--green); }
  .event-badge.channel_creation { background: rgba(251,146,60,0.15); color: var(--orange); }
  .event-badge.project_management { background: rgba(248,113,113,0.15); color: var(--red); }
  .system-info {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    font-size: 13px;
  }
  .system-info .label { color: var(--text-dim); }
  .system-info .value { color: var(--text); font-weight: 500; }
  .docker-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    font-size: 13px;
    border-bottom: 1px solid var(--card-border);
  }
  .docker-row:last-child { border-bottom: none; }
  .footer {
    text-align: center;
    color: var(--text-dim);
    font-size: 12px;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--card-border);
  }
  .wide { grid-column: 1 / -1; }
  .error-text { color: var(--red); font-size: 13px; }
</style>
</head>
<body>

<div class="header">
  <h1>⚓ Schubert Audit Dashboard</h1>
  <div class="meta">
    <div class="refresh"><span class="dot"></span> Auto-refresh: 30s</div>
    <div id="timestamp"></div>
  </div>
</div>

<!-- Memory Stats -->
<div class="grid">
  <div class="card">
    <h2>Memory Store</h2>
    <div class="stat-grid" id="memory-stats"></div>
  </div>

  <!-- System Resources -->
  <div class="card">
    <h2>System Resources</h2>
    <div class="system-info" id="system-info"></div>
  </div>

  <!-- Service Status -->
  <div class="card">
    <h2>Service Status</h2>
    <div id="services"></div>
  </div>

  <!-- LiteLLM -->
  <div class="card">
    <h2>LiteLLM Proxy</h2>
    <div id="litellm"></div>
  </div>
</div>

<div class="grid">
  <!-- Entity Breakdown -->
  <div class="card">
    <h2>Entity Breakdown</h2>
    <div class="bar-chart" id="entity-breakdown"></div>
  </div>

  <!-- Event Type Breakdown -->
  <div class="card">
    <h2>Event Types</h2>
    <div class="bar-chart" id="event-breakdown"></div>
  </div>

  <!-- Memory Growth -->
  <div class="card">
    <h2>Memory Growth (30 days)</h2>
    <div class="line-chart" id="memory-growth"></div>
  </div>
</div>

<div class="grid">
  <!-- Top Entities -->
  <div class="card">
    <h2>Top Entities by Facts</h2>
    <table class="table" id="top-entities">
      <thead><tr><th>Entity</th><th>Type</th><th>Facts</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Architect Metrics -->
  <div class="card">
    <h2>Architect Bot Metrics</h2>
    <div class="stat-grid" id="architect-metrics"></div>
    <div style="margin-top:16px" id="llm-latencies"></div>
  </div>

  <!-- Docker -->
  <div class="card">
    <h2>Docker Containers</h2>
    <div id="docker"></div>
  </div>
</div>

<div class="grid">
  <!-- Recent Events -->
  <div class="card wide">
    <h2>Recent Memory Events</h2>
    <table class="table" id="recent-events">
      <thead><tr><th>Type</th><th>Project</th><th>Summary</th><th>Entities</th><th>Timestamp</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="grid">
  <!-- Auto-Update History -->
  <div class="card wide">
    <h2>Architect Auto-Update History</h2>
    <table class="table" id="update-history">
      <thead><tr><th>Timestamp</th><th>Target</th><th>Description</th><th>Result</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="grid">
  <!-- Change Log -->
  <div class="card wide">
    <h2>Change Log</h2>
    <table class="table" id="change-log">
      <thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Target</th><th>Description</th><th>Outcome</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="footer">
  Schubert Bot V2 Audit Dashboard &mdash; FastAPI + PostgreSQL + systemd
</div>

<script>
const API_URL = '/api/stats';

const BAR_COLORS = ['blue', 'green', 'purple', 'orange', 'yellow'];

async function loadData() {
  try {
    const resp = await fetch(API_URL);
    const data = await resp.json();
    renderAll(data);
  } catch (e) {
    document.querySelector('.header h1').textContent = '⚓ Schubert Audit Dashboard (Error loading data)';
    console.error('Failed to load:', e);
  }
}

function renderAll(data) {
  document.getElementById('timestamp').textContent =
    'Last updated: ' + new Date(data.timestamp).toLocaleString();

  renderMemoryStats(data.memory);
  renderSystemInfo(data.system);
  renderServices(data.services);
  renderLiteLLM(data.litellm);
  renderEntityBreakdown(data.entity_breakdown);
  renderEventBreakdown(data.event_breakdown);
  renderMemoryGrowth(data.memory_growth);
  renderTopEntities(data.top_entities);
  renderArchitectMetrics(data.architect_metrics);
  renderDocker(data.docker);
  renderRecentEvents(data.recent_events);
  renderUpdateHistory(data.update_history);
  renderChangeLog(data.change_log);
}

function renderMemoryStats(mem) {
  const el = document.getElementById('memory-stats');
  if (mem.error) { el.innerHTML = '<div class="error-text">' + mem.error + '</div>'; return; }
  const items = [
    {label:'Vectors', value:mem.vectors},
    {label:'Entities', value:mem.entities},
    {label:'Facts', value:mem.facts},
    {label:'Events', value:mem.events},
    {label:'Relationships', value:mem.relationships},
  ];
  el.innerHTML = items.map(s =>
    '<div class="stat"><div class="value">' + (s.value ?? 0).toLocaleString() +
    '</div><div class="label">' + s.label + '</div></div>'
  ).join('');
}

function renderSystemInfo(sys) {
  const el = document.getElementById('system-info');
  const items = [
    {label:'Disk', value:sys.disk_pct || '?'},
    {label:'Disk Avail', value:sys.disk_avail || '?'},
    {label:'Memory', value:(sys.mem_used || '?') + ' / ' + (sys.mem_total || '?')},
    {label:'Mem Avail', value:sys.mem_avail || '?'},
    {label:'Load Avg', value:(sys.load_avg||[]).join(' ') || '?'},
    {label:'Uptime', value:sys.uptime || '?'},
  ];
  el.innerHTML = items.map(s =>
    '<div><span class="label">' + s.label + ': </span><span class="value">' + s.value + '</span></div>'
  ).join('');
}

function renderServices(services) {
  const el = document.getElementById('services');
  el.innerHTML = services.map(s => {
    const badge = s.active ? 'active' : 'inactive';
    const crit = s.critical ? '<span class="critical">critical</span>' : '';
    return '<div class="service-row"><span class="service-name">' + s.name + crit +
      '</span><span class="badge ' + badge + '">' + s.status + '</span></div>';
  }).join('');
}

function renderLiteLLM(lt) {
  const el = document.getElementById('litellm');
  if (lt.error) {
    el.innerHTML = '<div class="error-text">Error: ' + lt.error + '</div>';
    return;
  }
  let html = '<div class="service-row"><span class="service-name">Endpoint</span>' +
    '<span class="badge ' + (lt.healthy ? 'active' : 'inactive') + '">' +
    (lt.healthy ? 'Healthy' : 'Down') + '</span></div>';
  html += '<div class="service-row"><span class="service-name">Models Available</span>' +
    '<span class="value">' + (lt.model_count || 0) + '</span></div>';
  if (lt.models && lt.models.length) {
    html += '<div style="margin-top:8px;font-size:12px;color:var(--text-dim)">' +
      lt.models.slice(0, 8).join(', ') + '</div>';
  }
  el.innerHTML = html;
}

function renderBarChart(containerId, data) {
  const el = document.getElementById(containerId);
  if (!data || data.length === 0) { el.innerHTML = '<div class="error-text">No data</div>'; return; }
  const maxVal = Math.max(...data.map(d => d.value), 1);
  el.innerHTML = data.map((d, i) => {
    const pct = (d.value / maxVal * 100).toFixed(1);
    const color = BAR_COLORS[i % BAR_COLORS.length];
    return '<div class="bar-row"><div class="bar-label">' + d.label +
      '</div><div class="bar-track"><div class="bar-fill ' + color +
      '" style="width:' + pct + '%">' + d.value + '</div></div></div>';
  }).join('');
}

function renderEntityBreakdown(data) { renderBarChart('entity-breakdown', data); }
function renderEventBreakdown(data) { renderBarChart('event-breakdown', data); }

function renderMemoryGrowth(growth) {
  const el = document.getElementById('memory-growth');
  if (!growth || growth.length === 0) { el.innerHTML = '<div class="error-text">No growth data</div>'; return; }

  const width = 100, height = 100;
  const maxCount = Math.max(...growth.map(g => g.count), 1);
  const points = growth.map((g, i) => {
    const x = (i / (growth.length - 1 || 1)) * width;
    const y = height - (g.count / maxCount) * (height - 10) - 5;
    return x.toFixed(2) + ',' + y.toFixed(2);
  });

  const linePath = 'M ' + points.join(' L ');
  const areaPath = linePath + ' L ' + width + ',' + height + ' L 0,' + height + ' Z';

  let labels = '';
  if (growth.length <= 10) {
    growth.forEach((g, i) => {
      const x = (i / (growth.length - 1 || 1)) * 100;
      labels += '<text x="' + x + '%" y="99%" font-size="6" fill="#8b8fa8" text-anchor="middle">' +
        g.date.slice(5) + '</text>';
    });
  } else {
    for (let i = 0; i < growth.length; i += Math.ceil(growth.length / 8)) {
      const x = (i / (growth.length - 1 || 1)) * 100;
      labels += '<text x="' + x + '%" y="99%" font-size="6" fill="#8b8fa8" text-anchor="middle">' +
        growth[i].date.slice(5) + '</text>';
    }
  }

  el.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none">' +
    '<defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0%" stop-color="#5b8def" stop-opacity="0.3"/>' +
    '<stop offset="100%" stop-color="#5b8def" stop-opacity="0"/>' +
    '</linearGradient></defs>' +
    '<path d="' + areaPath + '" fill="url(#areaGrad)"/>' +
    '<polyline points="' + points.join(' ') + '" fill="none" stroke="#5b8def" stroke-width="0.5" vector-effect="non-scaling-stroke"/>' +
    labels + '</svg>';
}

function renderTopEntities(entities) {
  const tbody = document.querySelector('#top-entities tbody');
  if (!entities || entities.length === 0) { tbody.innerHTML = '<tr><td colspan="3" class="error-text">No data</td></tr>'; return; }
  tbody.innerHTML = entities.map(e =>
    '<tr><td>' + e.name + '</td><td>' + e.type + '</td><td>' + e.facts + '</td></tr>'
  ).join('');
}

function renderArchitectMetrics(metrics) {
  const el = document.getElementById('architect-metrics');
  const t = metrics.totals || {};
  const items = [
    {label:'LLM Calls', value:t.llm_calls},
    {label:'Tool Calls', value:t.tool_calls},
    {label:'Agent Reqs', value:t.agent_requests},
    {label:'Auto-Updates', value:t.auto_updates},
    {label:'Heals', value:t.heal_events},
    {label:'Escalations', value:t.escalations},
    {label:'LLM Errors', value:t.llm_errors},
    {label:'Rollbacks', value:t.rollbacks},
  ];
  el.innerHTML = items.map(s =>
    '<div class="stat"><div class="value">' + (s.value ?? 0) + '</div><div class="label">' +
    s.label + '</div></div>'
  ).join('');

  // LLM latencies
  const latEl = document.getElementById('llm-latencies');
  if (metrics.llm_by_model) {
    let html = '<div style="font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-dim);margin-bottom:8px">LLM Latency by Model</div>';
    for (const [model, vals] of Object.entries(metrics.llm_by_model)) {
      html += '<div class="latency-row"><span class="latency-model">' + model +
        '</span><span class="latency-vals">avg ' + vals.avg + 's &middot; max ' +
        vals.max + 's &middot; n=' + vals.count + '</span></div>';
    }
    latEl.innerHTML = html;
  } else if (metrics.error) {
    latEl.innerHTML = '<div class="error-text">' + metrics.error + '</div>';
  }
}

function renderDocker(containers) {
  const el = document.getElementById('docker');
  if (!containers || containers.length === 0) { el.innerHTML = '<div class="error-text">No containers</div>'; return; }
  el.innerHTML = containers.map(c => {
    const badge = c.running ? 'active' : 'inactive';
    return '<div class="docker-row"><span>' + c.name + '</span>' +
      '<span class="badge ' + badge + '">' + c.status + '</span></div>';
  }).join('');
}

function renderRecentEvents(events) {
  const tbody = document.querySelector('#recent-events tbody');
  if (!events || events.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="error-text">No events</td></tr>'; return; }
  tbody.innerHTML = events.map(e => {
    return '<tr><td><span class="event-badge ' + e.event_type + '">' + e.event_type +
      '</span></td><td>' + e.project + '</td><td>' + e.summary +
      '</td><td style="font-size:12px;color:var(--text-dim)">' + e.entities +
      '</td><td style="font-size:12px;color:var(--text-dim)">' + e.timestamp + '</td></tr>';
  }).join('');
}

function renderUpdateHistory(history) {
  const tbody = document.querySelector('#update-history tbody');
  if (!history || history.length === 0) { tbody.innerHTML = '<tr><td colspan="4" class="error-text">No updates recorded</td></tr>'; return; }
  tbody.innerHTML = history.slice().reverse().map(h => {
    var success = h.success === true || h.result === 'success';
    var badge = success ? 'active' : 'inactive';
    return '<tr><td style="font-size:12px">' + (h.timestamp || h.ts || '') +
      '</td><td>' + (h.target || h.target_name || 'architect') +
      '</td><td>' + (h.description || h.change || '') +
      '</td><td><span class="badge ' + badge + '">' +
      (success ? 'Success' : 'Failed') + '</span></td></tr>';
  }).join('');
}

function renderChangeLog(changes) {
  const tbody = document.querySelector('#change-log tbody');
  if (!changes || changes.length === 0) { tbody.innerHTML = '<tr><td colspan="6" class="error-text">No changes logged yet</td></tr>'; return; }
  var actorColors = {'architect': 'blue', 'schubert': 'green', 'writer_agent': 'purple', 'autoupdater': 'orange', 'manual': 'yellow'};
  tbody.innerHTML = changes.map(function(c) {
    var outcomeBadge = c.outcome === 'success' ? 'active' : (c.outcome === 'failed' ? 'inactive' : '');
    var actorClass = actorColors[c.actor] || 'blue';
    return '<tr><td style="font-size:12px">' + (c.timestamp || '') +
      '</td><td><span class="badge ' + actorClass + '">' + (c.actor || '') + '</span></td>' +
      '<td>' + (c.action || '') +
      '</td><td style="font-size:12px">' + (c.target || '') +
      '</td><td>' + (c.description || '') +
      '</td><td><span class="badge ' + outcomeBadge + '">' + (c.outcome || 'pending') + '</span></td></tr>';
  }).join('');
}

loadData();
</script>

</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Schubert Audit Dashboard starting on {DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(f"  Postgres: {PG_DB} at {PG_HOST}")
    print(f"  Metrics:  {METRICS_FILE}")
    print(f"  LiteLLM:  {LITELLM_URL}")
    uvicorn.run(
        app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level="info",
    )
