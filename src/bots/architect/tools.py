"""Architect tools — engineering and deployment operations."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

ARCHITECT_TOOLS: list[Tool] = [
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
        name="deploy_code",
        description="Deploy code changes to the target environment.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Deployment target: 'staging', 'production'.",
                },
                "service_name": {
                    "type": "string",
                    "description": "Name of the service to deploy.",
                },
            },
            "required": ["target", "service_name"],
        },
    ),
    Tool(
        name="propagate_fix",
        description="Propagate a fix across the fleet to all affected bots.",
        parameters={
            "type": "object",
            "properties": {
                "fix_id": {
                    "type": "string",
                    "description": "Identifier for the fix to propagate.",
                },
                "bot_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of bot IDs to apply the fix to.",
                },
            },
            "required": ["fix_id"],
        },
    ),
    Tool(
        name="git_operations",
        description="Execute git operations (status, diff, log, commit, push).",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Git subcommand to execute (e.g. 'status', 'diff').",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional arguments for the git command.",
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="run_tests",
        description="Run the test suite or a specific test file.",
        parameters={
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Path to the test file or directory to run.",
                },
                "marker": {
                    "type": "string",
                    "description": "Optional pytest marker to filter tests.",
                },
            },
            "required": ["test_path"],
        },
    ),
]
