"""Cartographer tools — documentation and knowledge management."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

CARTOGRAPHER_TOOLS: list[Tool] = [
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
    Tool(
        name="deploy_file",
        description="Deploy a documentation file to the repository (docs only).",
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
        name="write_file",
        description="Write content to a documentation file (docs only).",
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
        name="wiki_publish",
        description="Publish or update a wiki page with the given content.",
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the wiki page.",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content for the wiki page.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for the wiki page.",
                },
            },
            "required": ["title", "content"],
        },
    ),
]
