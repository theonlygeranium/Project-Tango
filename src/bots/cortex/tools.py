"""Dr. Cortex tools — research and analysis operations."""

from __future__ import annotations

import logging

from nexus.bot.tools import Tool

logger = logging.getLogger(__name__)

DR_CORTEX_TOOLS: list[Tool] = [
    Tool(
        name="web_search",
        description="Search the web for information on a given query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="scan_ai_trends",
        description="Scan and summarize recent AI industry trends and developments.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category of trends: 'models', 'tooling', 'research', 'industry'.",
                },
                "since_days": {
                    "type": "integer",
                    "description": "Number of days to look back.",
                    "default": 7,
                },
            },
            "required": ["category"],
        },
    ),
    Tool(
        name="benchmark_model",
        description="Benchmark an LLM model on a set of test prompts.",
        parameters={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model identifier to benchmark.",
                },
                "test_suite": {
                    "type": "string",
                    "description": "Test suite to run for benchmarking.",
                },
            },
            "required": ["model"],
        },
    ),
    Tool(
        name="analyze_bot_code",
        description="Analyze a bot's source code for quality and improvement opportunities.",
        parameters={
            "type": "object",
            "properties": {
                "bot_id": {
                    "type": "string",
                    "description": "ID of the bot whose code to analyze.",
                },
                "focus": {
                    "type": "string",
                    "description": "Analysis focus: 'quality', 'performance', 'security', 'all'.",
                },
            },
            "required": ["bot_id"],
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
]
