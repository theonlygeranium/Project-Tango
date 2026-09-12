#!/usr/bin/env python3
"""
Service Registry & Alias Mapper
================================
Single source of truth for all systemd service names in the Project Tango fleet.

PROBLEM: Agents were guessing service names like "tango-admiral.service",
"admiral-bot.service", etc. — none of which exist. This caused failed
restarts, confused status checks, and general chaos.

SOLUTION: This module provides:
  1. VALID_SERVICES  — the canonical list of real systemd services
  2. ALIAS_MAP       — maps common wrong names to the correct service
  3. validate_service() — returns (valid_service, error_message)
  4. resolve_service()  — resolves an alias to the real service name
  5. AGENT_TO_SERVICE   — maps agent names to their controlling service

Usage:
    from service_registry import validate_service, resolve_service, VALID_SERVICES

    service = resolve_service(user_input)   # "tango-architect" → "schubert-architect.service"
    valid, err = validate_service(service)
    if not valid:
        return f"Error: {err}"

Author: The Architect
Updated: 2026-08-21 — Fixed to include per-agent services (they DO exist)
"""

from __future__ import annotations
from typing import Tuple, Optional


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL SERVICE LIST — these are the ONLY real systemd services
# ─────────────────────────────────────────────────────────────────────────────
VALID_SERVICES = {
    # Fleet bot services (each bot runs as its own systemd service)
    # NEVER start: architect-bot.service, proctor-bot.service, schubert-cortex.service (masked duplicates)
    "schubert-bot.service",          # Admiral Schubert
    "schubert-architect.service",    # The Architect
    "schubert-quartermaster.service", # Quartermaster
    "schubert-cartographer.service",  # Cartographer
    "schubert-dr-voss.service",       # Dr. Voss
    "schubert-proctor.service",        # The Proctor
    "cortex-bot.service",             # Dr. Cortex (legacy name, no schubert- prefix)
    # Infrastructure services
    "github-mcp-server.service",      # GitHub MCP server
    "gmail-mcp-freelance.service",    # Gmail MCP server
    "caddy.service",                  # Reverse proxy / web server
    "cloudflared.service",            # Cloudflare tunnel
    "ollama.service",                 # Local LLM inference
    "docker.service",                 # Container runtime
    "postgresql.service",             # Database
    "polyglot-litellm.service",       # LiteLLM proxy
    # Project Tango application services
    "tango-backend.service",          # FastAPI backend + LiveKit worker
    "tango-web.service",              # Next.js frontend
}


# ─────────────────────────────────────────────────────────────────────────────
# AGENT → SERVICE MAPPING
# Each agent runs as its own systemd service.
# ─────────────────────────────────────────────────────────────────────────────
AGENT_TO_SERVICE = {
    "admiral": "schubert-bot.service",
    "architect": "schubert-architect.service",
    "proctor": "schubert-proctor.service",
    "dr_voss": "schubert-dr-voss.service",
    "quartermaster": "schubert-quartermaster.service",
    "cartographer": "schubert-cartographer.service",
    "cortex": "cortex-bot.service",
}


# ─────────────────────────────────────────────────────────────────────────────
# ALIAS MAP — common wrong names → correct service name
# ─────────────────────────────────────────────────────────────────────────────
ALIAS_MAP = {
    # Tango-prefixed guesses (WRONG — use schubert- prefix)
    "tango-architect.service": "schubert-architect.service",
    "tango-architect": "schubert-architect.service",
    "tango-admiral.service": "schubert-bot.service",
    "tango-admiral": "schubert-bot.service",
    "tango-bot.service": "schubert-bot.service",
    "tango-bot": "schubert-bot.service",
    "tango-quartermaster.service": "schubert-quartermaster.service",
    "tango-quartermaster": "schubert-quartermaster.service",
    "tango-cartographer.service": "schubert-cartographer.service",
    "tango-cartographer": "schubert-cartographer.service",
    "tango-voss.service": "schubert-dr-voss.service",
    "tango-voss": "schubert-dr-voss.service",
    "tango-proctor.service": "schubert-proctor.service",
    "tango-proctor": "schubert-proctor.service",
    "tango-cortex.service": "cortex-bot.service",
    "tango-cortex": "cortex-bot.service",
    # Admiral-prefixed guesses (WRONG)
    "admiral-bot.service": "schubert-bot.service",
    "admiral-bot": "schubert-bot.service",
    "admiral.service": "schubert-bot.service",
    "admiral": "schubert-bot.service",
    # Bare agent names → correct per-agent services
    "architect.service": "schubert-architect.service",
    "architect": "schubert-architect.service",
    "proctor.service": "schubert-proctor.service",
    "proctor": "schubert-proctor.service",
    "quartermaster.service": "schubert-quartermaster.service",
    "quartermaster": "schubert-quartermaster.service",
    "cartographer.service": "schubert-cartographer.service",
    "cartographer": "schubert-cartographer.service",
    "dr-voss.service": "schubert-dr-voss.service",
    "dr-voss": "schubert-dr-voss.service",
    "voss.service": "schubert-dr-voss.service",
    "voss": "schubert-dr-voss.service",
    "cortex.service": "cortex-bot.service",
    "cortex": "cortex-bot.service",
    # Missing .service suffix
    "schubert-bot": "schubert-bot.service",
    "schubert-architect": "schubert-architect.service",
    "schubert-quartermaster": "schubert-quartermaster.service",
    "schubert-cartographer": "schubert-cartographer.service",
    "schubert-dr-voss": "schubert-dr-voss.service",
    "schubert-proctor": "schubert-proctor.service",
    # Duplicate legacy unit names (must never be started; resolve to canonical)
    "architect-bot.service": "schubert-architect.service",
    "architect-bot": "schubert-architect.service",
    "proctor-bot.service": "schubert-proctor.service",
    "proctor-bot": "schubert-proctor.service",
    "schubert-cortex.service": "cortex-bot.service",
    "schubert-cortex": "cortex-bot.service",
    "cortex-bot": "cortex-bot.service",
    "github-mcp-server": "github-mcp-server.service",
    "gmail-mcp-freelance": "gmail-mcp-freelance.service",
    "caddy": "caddy.service",
    "cloudflared": "cloudflared.service",
    "ollama": "ollama.service",
    "docker": "docker.service",
    "postgresql": "postgresql.service",
    "polyglot-litellm": "polyglot-litellm.service",
    # MCP server alias
    "mcp-server.service": "schubert-bot.service",
    "mcp-server": "schubert-bot.service",
}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def resolve_service(name: str) -> str:
    """
    Resolve a service name or alias to the canonical systemd service name.
    Falls through to the input if no alias matches.
    """
    if not name:
        return name
    # Try exact alias match
    if name in ALIAS_MAP:
        return ALIAS_MAP[name]
    # Try lowercase
    if name.lower() in ALIAS_MAP:
        return ALIAS_MAP[name.lower()]
    # If it's already valid, return as-is
    if name in VALID_SERVICES:
        return name
    # If it ends with .service but isn't recognized, return as-is
    # (validate_service will catch it)
    return name


def validate_service(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a service name. Returns (True, None) if valid,
    or (False, error_message) if invalid.
    """
    if not name:
        return False, "Service name is required."

    resolved = resolve_service(name)

    if resolved in VALID_SERVICES:
        return True, None

    # Build a helpful error message
    known = ", ".join(sorted(VALID_SERVICES))
    return False, (
        f"Unknown service '{name}'. "
        f"Valid services: {known}."
    )


def get_agent_service(agent_name: str) -> str:
    """Get the systemd service that controls a given agent."""
    return AGENT_TO_SERVICE.get(agent_name, "schubert-bot.service")


def list_services() -> list[str]:
    """Return sorted list of valid service names."""
    return sorted(VALID_SERVICES)
