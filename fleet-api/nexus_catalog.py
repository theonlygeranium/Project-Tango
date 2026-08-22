"""Nexus Fleet tool catalog for the pre-Nexus Fleet Command UI.

The Cloudflare Pages app at ``command.schubert.life`` reads
``GET /api/fleet/config`` and renders ``bots.<id>.tools``. That list was
frozen before the Nexus rebuild (``src/bots/*/tools.py`` +
``fleet-manifest.yaml``). This module merges the Nexus catalog into the
existing UI contract without requiring a Pages redeploy.

Bot IDs in the UI / ``fleet-config.json`` stay canonical
(``dr_voss``, not ``voss``). Nexus aliases resolve to those IDs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# On-disk fleet-config.json still uses dr_voss. The Nexus UI uses voss.
BOT_ALIASES = {
    "voss": "dr_voss",
    "dr-voss": "dr_voss",
    "dr.voss": "dr_voss",
}

UI_ROSTER = [
    "admiral",
    "architect",
    "quartermaster",
    "cartographer",
    "voss",
    "proctor",
    "cortex",
    "sentinel",
]

# Nexus manifest bot_id -> fleet-config bot_id
NEXUS_TO_CONFIG = {
    "admiral": "admiral",
    "architect": "architect",
    "voss": "dr_voss",
    "cortex": "cortex",
    "quartermaster": "quartermaster",
    "cartographer": "cartographer",
    "proctor": "proctor",
    "sentinel": "sentinel",
}

# Tools registered in src/bots/<bot>/tools.py after the Nexus rebuild.
# Descriptions stay short — the UI shows id/name/source.
NEXUS_TOOLS: dict[str, list[dict[str, str]]] = {
    "admiral": [
        ("run_shell", "Execute a shell command on the host."),
        ("read_file", "Read a repository file."),
        ("write_file", "Write a repository file."),
        ("health_check", "Run a liveness/readiness/full health check."),
        ("fleet_delegate", "Delegate a task to another bot via the Nexus Bus."),
        ("fleet_broadcast", "Broadcast a message to the fleet."),
        ("service_status", "Check a systemd unit."),
        ("restart_service", "Restart a systemd unit."),
    ],
    "architect": [
        ("run_shell", "Execute a shell command on the host."),
        ("read_file", "Read a repository file."),
        ("write_file", "Write a repository file."),
        ("deploy_code", "Deploy a service to staging or production."),
        ("propagate_fix", "Propagate a fix across affected bots."),
        ("git_operations", "Run git status/diff/log/commit/push."),
        ("run_tests", "Run the test suite or a specific file."),
    ],
    "dr_voss": [
        ("health_check", "Run a liveness/readiness/full health check."),
        ("service_status", "Check a systemd unit."),
        ("restart_service", "Restart a systemd unit."),
        ("view_logs", "Tail recent journal logs for a service."),
        ("read_file", "Read a repository file."),
    ],
    "cortex": [
        ("web_search", "Search the web for a query."),
        ("scan_ai_trends", "Summarize recent AI industry trends."),
        ("benchmark_model", "Benchmark an LLM on a test suite."),
        ("analyze_bot_code", "Analyze a bot's source for quality/security."),
        ("read_file", "Read a repository file."),
        ("write_file", "Write a repository file."),
    ],
    "quartermaster": [
        ("docker", "Run docker ps/logs/inspect/restart."),
        ("caddy", "Validate or reload Caddy config."),
        ("cloudflare", "Cloudflare DNS, tunnel, and cache actions."),
        ("dns", "Lookup or update fleet DNS records."),
        ("service_status", "Check a systemd unit."),
        ("restart_service", "Restart a systemd unit."),
        ("run_shell", "Execute a shell command on the host."),
    ],
    "cartographer": [
        ("read_file", "Read a repository file."),
        ("write_file", "Write a documentation file."),
        ("query_change_log", "Search the fleet change log."),
        ("deploy_file", "Deploy a docs-only file."),
        ("wiki_publish", "Publish or update an Outline wiki page."),
    ],
    "proctor": [
        ("run_tests", "Run the test suite or a specific file."),
        ("write_file", "Write a test file."),
        ("read_file", "Read a repository file."),
        ("git_operations", "Run git status/diff/log/commit/push."),
        ("query_change_log", "Search the fleet change log."),
    ],
    "sentinel": [
        ("run_tests", "Run the test suite or a specific file."),
        ("write_file", "Write a test or repair file."),
        ("read_file", "Read a repository file."),
        ("git_operations", "Run git status/diff/log/commit/push."),
        ("generate_tests", "Generate tests for a target module."),
        ("repair_code", "Propose a repair for a failing test."),
    ],
}

# systemd names from fleet-manifest.yaml (without .service). Live units may
# still use the pre-Nexus names recorded in fleet-config identity.service.
NEXUS_SYSTEMD = {
    "admiral": "schubert-bot",
    "architect": "schubert-architect",
    "dr_voss": "schubert-dr-voss",
    "cortex": "schubert-cortex",
    "quartermaster": "schubert-quartermaster",
    "cartographer": "schubert-cartographer",
    "proctor": "schubert-proctor",
    "sentinel": "schubert-sentinel",
}


def canonicalize_bot_id(bot_id: str) -> str:
    """Map Nexus / informal IDs onto fleet-config keys."""
    key = (bot_id or "").strip().lower()
    return BOT_ALIASES.get(key, key)


def resolve_bot_id(bot_id: str, config: dict[str, Any]) -> str | None:
    """Return the fleet-config bot key, or None if unknown."""
    bots = config.get("bots") or {}
    canonical = canonicalize_bot_id(bot_id)
    if canonical in bots:
        return canonical
    if bot_id in bots:
        return bot_id
    return None


def nexus_tool_entries(bot_id: str) -> list[dict[str, Any]]:
    """Return Nexus tools for a canonical fleet-config bot id."""
    canonical = canonicalize_bot_id(bot_id)
    rows = NEXUS_TOOLS.get(canonical) or []
    return [
        {
            "id": name,
            "name": name,
            "source": "nexus",
            "enabled": True,
            "description": description,
        }
        for name, description in rows
    ]


def merge_tools(
    existing: list[Any] | None, bot_id: str
) -> list[dict[str, Any]]:
    """Union fleet-config tools with the Nexus catalog, preserving order."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in existing or []:
        if not isinstance(raw, dict):
            continue
        tool_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not tool_id or tool_id in seen:
            continue
        seen.add(tool_id)
        entry = dict(raw)
        entry.setdefault("id", tool_id)
        entry.setdefault("name", tool_id)
        entry.setdefault("source", "legacy")
        entry.setdefault("enabled", True)
        merged.append(entry)

    for entry in nexus_tool_entries(bot_id):
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        merged.append(entry)

    return merged


def enrich_bot(bot: dict[str, Any], bot_id: str) -> dict[str, Any]:
    """Return a copy of a bot config with Nexus tools merged in."""
    enriched = deepcopy(bot)
    enriched["tools"] = merge_tools(bot.get("tools"), bot_id)
    tags = list(enriched.get("meta", {}).get("featureTags") or [])
    if "nexus" not in tags:
        tags.append("nexus")
        if isinstance(enriched.get("meta"), dict):
            enriched["meta"] = {**enriched["meta"], "featureTags": tags}
    return enriched


def enrich_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of fleet-config with every bot's tools merged."""
    enriched = deepcopy(config)
    bots = enriched.get("bots") or {}
    for bot_id, bot in list(bots.items()):
        if isinstance(bot, dict):
            bots[bot_id] = enrich_bot(bot, bot_id)
    return enriched


def sentinel_stub() -> dict[str, Any]:
    """Minimal bot record so the UI can render an eighth card before deploy."""
    return {
        "meta": {
            "id": "sentinel",
            "name": "Sentinel",
            "role": "testing",
            "roleLabel": "Validation / QA",
            "avatar": "SN",
            "status": "offline",
            "scriptLines": 0,
            "featureTags": ["nexus", "testing", "not-deployed"],
        },
        "identity": {
            "name": "Sentinel",
            "discord_id": "",
            "channel_id": "",
            "service": "schubert-sentinel.service",
            "script": "src/bots/sentinel",
            "tier": "Tier 3 — Validation",
        },
        "llm": {
            "model": "writer/palmyra-x6",
            "coding_model": "writer/claude-sonnet-4-5",
            "temperature": 0.2,
            "max_tokens": 4096,
            "llm_timeout": 120,
            "max_iterations": 20,
            "agent_timeout": 300,
            "tool_output_limit": 4000,
            "shell_timeout": 120,
            "session_window": 20,
            "rate_limit_per_min": None,
        },
        "prompt": {
            "system_prompt": "You are Sentinel, the Nexus validation bot. Generate tests, repair failing code, and gate fleet rollouts.",
            "voice_prompt_addition": False,
            "coding_prompt_addition": True,
            "poll_prompt_addition": False,
            "meetscribe_prompt_addition": False,
        },
        "tools": [],
        "guardrails": {},
        "scheduler_enabled": False,
        "memory": {},
        "voice": {"enabled": False},
        "mcp": {"servers": []},
        "multi_agent": {
            "response_threshold": 0.9,
            "urgent_threshold": 0.95,
            "cooldown_seconds": 60,
            "fleet_delegation_role": "receive_only",
        },
        "self_healing": None,
        "self_improvement": None,
    }


def present_config(config: dict[str, Any]) -> dict[str, Any]:
    """Config payload for the UI: Nexus tools, voss id, and a Sentinel card."""
    presented = enrich_config(config)
    bots = presented.setdefault("bots", {})
    if "dr_voss" in bots and "voss" not in bots:
        voss = deepcopy(bots["dr_voss"])
        meta = dict(voss.get("meta") or {})
        meta["id"] = "voss"
        voss["meta"] = meta
        identity = dict(voss.get("identity") or {})
        if identity.get("name") == "Dr. Voss" or not identity.get("name"):
            identity["name"] = "Dr. Voss"
        voss["identity"] = identity
        bots["voss"] = voss
    if "sentinel" not in bots:
        bots["sentinel"] = enrich_bot(sentinel_stub(), "sentinel")
    presented["ui_roster"] = list(UI_ROSTER)
    return presented


def nexus_status(config: dict[str, Any], service_status: dict[str, str]) -> dict[str, Any]:
    """Summary payload for GET /api/nexus/status."""
    bots = config.get("bots") or {}
    roster = []
    for nexus_id, config_id in NEXUS_TO_CONFIG.items():
        bot = bots.get(config_id) or {}
        identity = bot.get("identity") or {}
        live_service = identity.get("service") or f"{NEXUS_SYSTEMD.get(config_id, '')}.service"
        tools = merge_tools(bot.get("tools"), config_id)
        roster.append(
            {
                "nexus_id": nexus_id,
                "config_id": config_id,
                "deployed_in_config": config_id in bots,
                "identity_service": live_service,
                "nexus_systemd": f"{NEXUS_SYSTEMD.get(config_id, '')}.service",
                "status": service_status.get(config_id, "unknown"),
                "tools": [t["id"] for t in tools],
            }
        )
    return {
        "architecture": "nexus-v2",
        "ui_compatible": True,
        "aliases": dict(BOT_ALIASES),
        "roster": roster,
        "notes": [
            "GET /api/fleet/config presents voss (alias of on-disk dr_voss) and sentinel.",
            "The shipped Pages app still hardcodes seven IDs; use the fleet-api UI.",
            "sentinel is catalog-only until schubert-sentinel.service exists.",
            "Live systemd units may still be the pre-Nexus script services.",
        ],
    }
