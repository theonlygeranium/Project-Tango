"""Proctor tools — testing and QA operations."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

PROCTOR_TOOLS: list[Tool] = [
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
    Tool(
        name="write_file",
        description="Write content to a test file (test files only).",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Destination test file path relative to repo root.",
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
        name="query_change_log",
        description="Query the fleet change log for entries matching a search term.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to filter change log entries.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
]
