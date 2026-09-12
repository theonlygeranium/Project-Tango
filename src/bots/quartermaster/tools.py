"""Quartermaster tools — infrastructure and logistics management."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

QUARTERMASTER_TOOLS: list[Tool] = [
    Tool(
        name="docker",
        description="Execute a Docker command (ps, logs, inspect, restart, etc.).",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Docker subcommand to execute (e.g. 'ps', 'logs').",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional arguments for the Docker command.",
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="caddy",
        description="Manage Caddy reverse proxy configuration and reload.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Caddy action: 'reload', 'validate', 'list', 'adapt'.",
                },
                "config_path": {
                    "type": "string",
                    "description": "Path to the Caddyfile or JSON config.",
                },
            },
            "required": ["action"],
        },
    ),
    Tool(
        name="cloudflare",
        description="Interact with Cloudflare API for DNS, tunnels, and cache.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Cloudflare action: 'purge_cache', 'list_zones', 'tunnel_status'.",
                },
                "zone_id": {
                    "type": "string",
                    "description": "Cloudflare zone ID for the action.",
                },
            },
            "required": ["action"],
        },
    ),
    Tool(
        name="dns",
        description="Query or update DNS records for fleet domains.",
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain name to query or update.",
                },
                "record_type": {
                    "type": "string",
                    "description": "DNS record type (A, AAAA, CNAME, MX, TXT).",
                },
                "action": {
                    "type": "string",
                    "description": "Action: 'lookup' or 'update'.",
                },
            },
            "required": ["domain", "action"],
        },
    ),
    Tool(
        name="service_status",
        description="Check the status of a systemd service.",
        parameters={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the systemd service to check.",
                },
            },
            "required": ["service_name"],
        },
    ),
    Tool(
        name="restart_service",
        description="Restart a systemd service.",
        parameters={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the systemd service to restart.",
                },
            },
            "required": ["service_name"],
        },
    ),
]
