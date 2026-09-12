"""Admiral tools — fleet command and orchestration operations."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

ADMIRAL_TOOLS: list[Tool] = [
    Tool(
        name="run_shell",
        description="Execute a shell command on the host system.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command.",
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="write_file",
        description="Write content to a file in the repository.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Destination file path relative to repo root.",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write.",
                },
            },
            "required": ["path", "content"],
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
        name="fleet_delegate",
        description="Delegate a task to a specific bot via the Nexus Bus.",
        parameters={
            "type": "object",
            "properties": {
                "target_bot": {
                    "type": "string",
                    "description": "ID of the bot to delegate the task to.",
                },
                "task_type": {
                    "type": "string",
                    "description": "Type of task to delegate.",
                },
                "description": {
                    "type": "string",
                    "description": "Task description for the target bot.",
                },
                "priority": {
                    "type": "string",
                    "description": "Task priority: 'low', 'medium', 'high', 'critical'.",
                },
            },
            "required": ["target_bot", "description"],
        },
    ),
    Tool(
        name="fleet_broadcast",
        description="Broadcast a message to all bots in the fleet.",
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message content to broadcast.",
                },
                "event_type": {
                    "type": "string",
                    "description": "Event type for the broadcast.",
                },
            },
            "required": ["message"],
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
