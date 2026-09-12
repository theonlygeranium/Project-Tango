"""Dr. Voss tools — health monitoring and diagnostics."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

DR_VOSS_TOOLS: list[Tool] = [
    Tool(
        name="health_check",
        description="Run a health check on a bot or service.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Bot ID or service name to check.",
                },
                "check_type": {
                    "type": "string",
                    "description": "Type of health check: 'liveness', 'readiness', 'full'.",
                },
            },
            "required": ["target"],
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
    Tool(
        name="view_logs",
        description="View recent logs for a service or bot.",
        parameters={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the service to view logs for.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to retrieve.",
                    "default": 50,
                },
                "level": {
                    "type": "string",
                    "description": "Log level filter: 'error', 'warning', 'info', 'debug'.",
                },
            },
            "required": ["service_name"],
        },
    ),
    Tool(
        name="read_file",
        description="Read the contents of a file from the repository.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root.",
                },
            },
            "required": ["path"],
        },
    ),
]
