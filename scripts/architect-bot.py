#!/usr/bin/env python3
"""
The Architect — Schubert Control & Development Bot
====================================================
A separate Discord bot for administering and developing the Schubert Bot V2
ecosystem. Admin-only access. Shares MCP servers, LiteLLM proxy, and
infrastructure with Admiral Schubert, but runs as an independent process.

Capabilities:
  - LLM reasoning via LiteLLM (55 models, runtime-switchable)
  - MCP tool access (same 6 servers, 167 tools as Schubert Bot)
  - Web search (Serper API + SearxNG)
  - Development tools (deploy_file, restart_service, view_logs, run_test, edit_code)
  - Multi-LLM routing (!model command + dropdown UI)
  - Live processing indicator (typing + spinner + elapsed time)

Author: Jeff Geronimo
"""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import ui

# Add scripts directory to path for shared modules
SCRIPT_DIR = "/opt/Project-Tango/scripts"
sys.path.insert(0, SCRIPT_DIR)

from mcp_client import MCPClient, MCPServerConfig
from cloudflare_api import execute_cloudflare_tool, get_cloudflare_tool_definition
from memory_store import MemoryStore
from limitation_warnings import detect_limitation_warnings
from tool_descriptions import describe_tool_call, describe_tool_thinking
from multi_agent import MultiAgentManager, is_multi_agent_channel, get_shared_context
from fleet_protocol import (
    parse_fleet_message, is_fleet_message, check_chain_depth,
    format_response, track_chain, MAX_CHAIN_DEPTH, StreamingMessage,
)
from discord_ux_utils import keep_typing, should_use_thread

# Multi-agent coordinator imports
from conversation_coordinator import ConversationCoordinator, MultiAgentChannelManager
from response_scoring import calculate_response_score, should_respond_immediately, should_respond_with_delay, get_response_delay
from multi_agent_config import get_agent_profile, register_channel

# ---------------------------------------------------------------------------
# Fleet config (non-breaking: missing/corrupt file → hardcoded defaults)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from fleet_config_loader import get_bot_config
    _cfg = get_bot_config("architect")
except Exception:
    _cfg = {}

_llm = _cfg.get("llm", {}) if isinstance(_cfg.get("llm", {}), dict) else {}
_prompt = _cfg.get("prompt", {}) if isinstance(_cfg.get("prompt", {}), dict) else {}
_self_healing = _cfg.get("self_healing", {}) if isinstance(_cfg.get("self_healing", {}), dict) else {}
_self_improvement = _cfg.get("self_improvement", {}) if isinstance(_cfg.get("self_improvement", {}), dict) else {}

# Slack integration
from slack_notifier import get_slack_notifier

# WRITER Agent Playbook integration
from writer_integration import handle_architect_message
from channel_onboarding import onboard_channel

# WRITER playbook thread tracking (for follow-up conversations)
_playbook_threads: dict[int, str] = {}  # message_id -> thread_id

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("ARCHITECT_BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("ARCHITECT_CHANNEL_ID", "0"))
WORK_CHANNEL_ID = int(os.environ.get("ARCHITECT_WORK_CHANNEL_ID", "1539473266400432208"))
KICKSTART_DEMO_CHANNEL_ID = 1539657495142998078  # kickstart-demo channel
MONITORED_CHANNEL_IDS = {CHANNEL_ID, WORK_CHANNEL_ID, KICKSTART_DEMO_CHANNEL_ID}
ADMIN_USER_ID = 1075596247966167131
_multi_agent_manager: MultiAgentManager | None = None  # Jeff Geronimo (themightymaven)
SCHUBERT_BOT_ID = int(os.environ.get("SCHUBERT_BOT_ID", "0"))
PROCTOR_BOT_ID = int(os.environ.get("PROCTOR_BOT_ID", "0"))

LITELLM_URL = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

# Persistent memory (three-layer: Redis vectors + Postgres entity graph + temporal index)
memory_store: Optional[MemoryStore] = None

# Multi-agent coordinator instances (initialized in on_ready)
_channel_manager: Optional[MultiAgentChannelManager] = None
_coordinator: Optional[ConversationCoordinator] = None

# Session history (in-memory, per-channel, with windowing)
SESSION_HISTORY: dict[int, list[dict]] = {}
SESSION_MAX_MESSAGES = _llm.get("session_window", 20)

# Multi-LLM routing — default model and available models
# The Architect defaults to Palmyra x6 for general and coding tasks
DEFAULT_MODEL = _llm.get("model", "writer/palmyra-x6")
CODING_MODEL = _llm.get("coding_model", "writer/palmyra-x6")
current_model = DEFAULT_MODEL
user_model_override = False  # Set True when user manually selects via !model; disables auto-switching

# Model categories for the !model command and dropdown
MODEL_CATEGORIES = {
    "Writer (Palmyra)": [
        "writer/palmyra-x6",
        "writer/palmyra-x5",
        "writer/palmyra-x5-code",
        "writer/palmyra-x4",
        "writer/palmyra-creative",
    ],
    "Claude": [
        "writer/claude-sonnet-4-5",
        "writer/claude-sonnet-4",
        "writer/claude-opus-4",
        "writer/claude-3-5-sonnet",
        "writer/claude-haiku-4-5",
    ],
    "OpenAI": [
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
    ],
    "Google": [
        "google/gemini-2.5-pro",
        "google/gemini-2.5-flash",
    ],
    "xAI": [
        "xai/grok-4",
        "xai/grok-3-mini",
    ],
    "Local (Ollama)": [
        "local/qwen2.5-coder-32b-fast",
        "local/deepseek-r1-32b-fast",
        "local/llama3.1-8b",
    ],
}

LLM_TEMPERATURE = _llm.get("temperature", 0.3)
LLM_MAX_TOKENS = _llm.get("max_tokens", 4096)
LLM_TIMEOUT = _llm.get("llm_timeout", 300)
MAX_ITERATIONS = _llm.get("max_iterations", 30)
AGENT_TIMEOUT = _llm.get("agent_timeout", 480)
TOOL_OUTPUT_LIMIT = _llm.get("tool_output_limit", 8000)
SHELL_TIMEOUT = _llm.get("shell_timeout", 120)

# Colors
COLOR_INFO = 0x5865F2
COLOR_SUCCESS = 0x57F287
COLOR_WARN = 0xFEE75C
COLOR_ERROR = 0xED4245
COLOR_ARCHITECT = 0x9B59B6  # purple

# Channel onboarding config
ARCHITECT_CHANNEL_CONFIG = {
    "topic": "The Architect's Studio — Development & Control Center for the Schubert Bot V2 ecosystem",
    "bot_name": "The Architect",
    "role": "Schubert Control & Development Specialist",
    "description": (
        "A separate Discord bot for administering and developing the Schubert Bot V2 ecosystem. "
        "Admin-only access. Shares MCP servers, LiteLLM proxy, and infrastructure with Admiral Schubert, "
        "but runs as an independent process with 55 LLM models, 167 tools, and full development capabilities."
    ),
    "commands": [
        {"name": "!model", "description": "Switch LLM models via dropdown UI (55 models available)"},
        {"name": "!mcp", "description": "MCP server status and tool listing"},
        {"name": "!deploy <file>", "description": "Deploy a file to the server (with binary mode for >2KB)"},
        {"name": "!restart <service>", "description": "Restart a systemd service"},
        {"name": "!logs <service>", "description": "View recent logs for a service"},
        {"name": "!test <file>", "description": "Run a test file or test suite"},
        {"name": "!memory", "description": "Query persistent memory (search/stats/entity/recent/sync)"},
        {"name": "!session", "description": "Session management (clear/show history)"},
        {"name": "!help", "description": "Show this help"},
    ],
    "tips": [
        "Send natural language requests for development, debugging, and server management",
        "The Architect defaults to Palmyra x6 for general and coding tasks",
        "Full MCP tool access: 6 servers (Schubert Nexus, GitHub, Gmail, Postgres, Redis, Ollama), 167 tools",
        "Web search via Serper API and SearxNG for research and documentation lookup",
        "Persistent memory with three-layer storage: Redis vectors + Postgres entity graph + temporal index",
        "Live processing indicator shows typing status, spinner, elapsed time, and tool call history",
    ],
}

# Auto-thread thresholds (Enhancement 3)
THREAD_RESPONSE_THRESHOLD = 8000  # auto-thread if response > 8000 chars
THREAD_TOOL_CALL_THRESHOLD = 8    # auto-thread if >= 8 tool calls

# ---------------------------------------------------------------------------
# Auto Model Routing — Palmyra x6 (default) → Claude Sonnet 4.5 (coding)
# ---------------------------------------------------------------------------

# Keywords/patterns that signal a coding-related task
CODING_PATTERNS = [
    # Direct code actions
    "code", "function", "class", "method", "variable", "def ", "import ",
    "script", "deploy", "bug", "fix", "debug", "patch", "refactor",
    "edit", "modify", "update", "rewrite", "implement", "write a",
    # File/code artifacts
    ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".sh",
    ".html", ".css", ".sql", ".env", "config", "syntax",
    # Dev concepts
    "error", "traceback", "exception", "stack trace", "log",
    "regex", "api", "endpoint", "database", "query", "schema",
    "service", "systemd", "restart", "deploy", "commit", "git",
    "test", "pytest", "unittest", "lint", "type error",
    "async", "await", "thread", "coroutine", "event loop",
    "docker", "container", "nginx", "caddy",
]

def is_coding_task(user_input: str) -> bool:
    """Detect whether a user request is coding-related and should use Claude."""
    text = user_input.lower()
    return any(pattern in text for pattern in CODING_PATTERNS)


def select_model_for_task(user_input: str) -> str:
    """Auto-select the best model for the task. Only called when no manual override."""
    if is_coding_task(user_input):
        return CODING_MODEL
    return DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("architect-bot")

def log(msg: str, level: str = "INFO"):
    getattr(logger, level.lower(), logger.info)(msg)

# ---------------------------------------------------------------------------
# LiteLLM Chat
# ---------------------------------------------------------------------------

async def llm_chat(messages: list, tools: list | None = None, model: str | None = None) -> dict:
    """Call LiteLLM proxy with the current (or specified) model."""
    use_model = model or current_model
    call_start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": use_model,
                "messages": messages,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            headers = {
                "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
                "Content-Type": "application/json",
            }

            async with session.post(
                f"{LITELLM_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    log(f"LLM API error {resp.status}: {error_text[:500]}", "ERROR")
                    if metrics:
                        metrics.record_llm_call(use_model, time.time() - call_start, False)
                    return {
                        "error": f"LLM API returned {resp.status}: {error_text[:200]}",
                        "choices": [],
                    }
                data = await resp.json()
                if metrics:
                    metrics.record_llm_call(use_model, time.time() - call_start, True)
                return data

    except asyncio.TimeoutError:
        log(f"LLM call timed out after {LLM_TIMEOUT}s (model: {use_model})", "ERROR")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        return {"error": "LLM call timed out", "choices": []}
    except KeyError as e:
        log(f"LLM response missing expected field: {e}", "ERROR")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        return {"error": f"Invalid LLM response: {e}", "choices": []}
    except aiohttp.ClientError as e:
        log(f"LLM network error (retryable): {e}", "WARN")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        # Retry with exponential backoff
        for attempt in range(2):
            await asyncio.sleep(2 ** attempt)
            try:
                return await llm_chat(messages, tools, model)
            except aiohttp.ClientError:
                if attempt == 1:
                    break
                continue
        return {"error": f"Network error after retries: {e}", "choices": [], "retryable": True}
    except Exception as e:
        log(f"LLM call failed: {e}", "ERROR")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
            metrics.record_error(str(e), "llm_chat")
        return {"error": str(e), "choices": []}

# ---------------------------------------------------------------------------
# Streaming LLM Chat -- Typewriter-style output via SSE
# ---------------------------------------------------------------------------

async def llm_chat_stream(messages: list, tools: list | None = None,
                          model: str | None = None, on_content=None) -> dict:
    """Call LiteLLM with streaming support."""
    use_model = model or current_model
    call_start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": use_model,
                "messages": messages,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
                "stream": True,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            headers = {
                "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
                "Content-Type": "application/json",
            }
            async with session.post(
                f"{LITELLM_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    log(f"LLM stream error {resp.status}: {error_text[:500]}", "ERROR")
                    if metrics:
                        metrics.record_llm_call(use_model, time.time() - call_start, False)
                    return {"error": f"LLM API returned {resp.status}: {error_text[:200]}", "choices": []}
                accumulated_content = ""
                accumulated_tool_calls = {}
                finish_reason = None
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason") or finish_reason
                    content_delta = delta.get("content")
                    if content_delta:
                        accumulated_content += content_delta
                        if on_content:
                            try:
                                await on_content(content_delta)
                            except Exception:
                                pass
                    tool_calls_delta = delta.get("tool_calls")
                    if tool_calls_delta:
                        for tc in tool_calls_delta:
                            idx = tc.get("index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                            entry = accumulated_tool_calls[idx]
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if func.get("name"):
                                entry["function"]["name"] += func["name"]
                            if func.get("arguments"):
                                entry["function"]["arguments"] += func["arguments"]
                message = {"role": "assistant", "content": accumulated_content if accumulated_content else None}
                if accumulated_tool_calls:
                    message["tool_calls"] = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls)]
                if metrics:
                    metrics.record_llm_call(use_model, time.time() - call_start, True)
                log(f"LLM stream complete: {len(accumulated_content)} chars, {len(accumulated_tool_calls)} tool calls", "INFO")
                return {"choices": [{"message": message, "finish_reason": finish_reason or "stop"}]}
    except asyncio.TimeoutError:
        log("LLM stream timed out", "ERROR")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        return {"error": "LLM stream timed out", "choices": []}
    except aiohttp.ClientError as e:
        log(f"LLM stream network error (retryable): {e}", "WARN")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        return {"error": f"Network error: {e}", "choices": [], "retryable": True}
    except Exception as e:
        log(f"LLM stream failed: {e}", "ERROR")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
            metrics.record_error(str(e), "llm_chat_stream")
        return {"error": str(e), "choices": []}


# ---------------------------------------------------------------------------
# Web Search (Serper API)
# ---------------------------------------------------------------------------

async def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using Serper API and return formatted results."""
    if not SERPER_API_KEY:
        return "Web search unavailable — SERPER_API_KEY not configured."

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "q": query,
                "num": num_results,
            }
            headers = {
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json",
            }
            async with session.post(
                "https://google.serper.dev/search",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10, connect=3),
            ) as resp:
                if resp.status != 200:
                    return f"Search error: HTTP {resp.status}"
                data = await resp.json()

        results = []
        organic = data.get("organic", [])
        for i, item in enumerate(organic[:num_results], 1):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            results.append(f"{i}. **{title}**\n   {link}\n   {snippet}")

        # Add answer box if present
        if data.get("answerBox"):
            ab = data["answerBox"]
            answer = ab.get("answer") or ab.get("snippet") or ab.get("title", "")
            if answer:
                results.insert(0, f"**Answer:** {answer}")

        # Add knowledge graph if present
        if data.get("knowledgeGraph"):
            kg = data["knowledgeGraph"]
            title = kg.get("title", "")
            desc = kg.get("description", "")
            if desc:
                results.insert(0, f"**Knowledge:** {title} — {desc}")

        return "\n\n".join(results) if results else "No results found."

    except Exception as e:
        return f"Search error: {e}"


# ---------------------------------------------------------------------------
# Development Tools
# ---------------------------------------------------------------------------

def run_command(cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Run a shell command and return (exit_code, output)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = (r.stdout + r.stderr).strip()
        return r.returncode, output
    except subprocess.TimeoutExpired:
        return 124, "Command timed out"
    except Exception as e:
        return 1, str(e)


async def execute_dev_tool(tool_name: str, args: dict, mcp: MCPClient | None = None) -> str:
    """Execute a development-specific tool."""

    if tool_name == "send_writer_feedback_to_slack":
        # Import the feedback message
        from send_feedback_slack import FEEDBACK_MESSAGE, SLACK_CHANNEL_ID
        
        try:
            # Send via Slack MCP
            if mcp:
                result = await mcp.call_tool("slack__slack_post_message", {
                    "channel": SLACK_CHANNEL_ID,
                    "text": FEEDBACK_MESSAGE
                })
                return f"✅ Writer Event Feedback Summary sent to Slack #demo-cape-webinars. Response: {result[:200]}"
            else:
                return "❌ Error: MCP client not available"
        except Exception as e:
            log(f"Failed to send feedback to Slack: {e}", "ERROR")
            return f"❌ Failed to send to Slack: {str(e)}"
    
    if tool_name == "deploy_file":
        path = args.get("path", "")
        content = args.get("content", "")
        if not path or not content:
            return "Error: 'path' and 'content' are required"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Deployed {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    elif tool_name == "read_code":
        path = args.get("path", "")
        start_line = args.get("start_line", 1)
        end_line = args.get("end_line", 50)
        if not path:
            return "Error: 'path' is required"
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            total = len(lines)
            start = max(1, start_line)
            end = min(total, end_line)
            result = []
            for i in range(start - 1, end):
                result.append(f"{i+1:4d} | {lines[i].rstrip()}")
            return "\n".join(result) if result else "File is empty"
        except Exception as e:
            return f"Error reading file: {e}"

    elif tool_name == "search_code":
        pattern = args.get("pattern", "")
        path = args.get("path", "/opt/Project-Tango/scripts")
        if not pattern:
            return "Error: 'pattern' is required"
        # Escape single quotes in pattern for shell safety
        safe_pattern = pattern.replace("'", "'\\''")
        code, output = run_command(
            f"grep -rn '{safe_pattern}' {path} --include='*.py' 2>/dev/null | head -30"
        )
        return output if output else "No matches found"

    elif tool_name == "restart_service":
        service = args.get("service", "")
        if not service:
            return "Error: 'service' is required"
        if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
            return f"Error: invalid service name '{service}'"
        code, output = run_command(f"sudo systemctl restart {service}")
        if code == 0:
            await asyncio.sleep(2)
            code2, status = run_command(f"systemctl is-active {service}")
            return f"Restarted {service} — status: {status.strip()}"
        return f"Error restarting {service}: {output}"

    elif tool_name == "view_logs":
        service = args.get("service", "schubert-bot.service")
        lines = args.get("lines", 30)
        if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
            return f"Error: invalid service name '{service}'"
        code, output = run_command(
            f"sudo journalctl -u {service} --no-pager -n {lines} -o cat 2>&1"
        )
        return output[-3000:] if len(output) > 3000 else output

    elif tool_name == "run_test":
        suite = args.get("suite", "v2_init")
        suites = {
            "v2_init": "cd /opt/Project-Tango && POSTGRES_USER=root /opt/Project-Tango/backend/venv/bin/python scripts/test_v2_init.py",
            "phase3": "cd /opt/Project-Tango && POSTGRES_USER=root /opt/Project-Tango/backend/venv/bin/python scripts/test_phase3.py",
        }
        cmd = suites.get(suite)
        if not cmd:
            return f"Unknown test suite: {suite}. Available: {', '.join(suites.keys())}"
        code, output = run_command(cmd, timeout=60)
        return output[-3000:] if len(output) > 3000 else output

    elif tool_name == "service_status":
        services = [
            "schubert-bot", "github-mcp-server", "gmail-mcp-freelance",
            "caddy", "cloudflared", "ollama", "docker", "postgresql",
        ]
        lines = []
        for svc in services:
            code, status = run_command(f"systemctl is-active {svc}")
            lines.append(f"  {'✅' if status.strip() == 'active' else '❌'} {svc}: {status.strip()}")
        code, failed = run_command(
            "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $2}'"
        )
        if failed.strip():
            lines.append(f"\n  ⚠️ Failed: {failed.strip()}")
        return "\n".join(lines)

    elif tool_name == "web_search":
        query = args.get("query", "")
        if not query:
            return "Error: 'query' is required"
        return await web_search(query)

    elif tool_name == "query_memory":
        return handle_query_memory(args)

    elif tool_name == "cloudflare":
        action = args.get("action", "")
        if not action:
            return "Error: 'action' is required for cloudflare tool"
        return await execute_cloudflare_tool(action, args)

    return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Tool Definitions (for LLM)
# ---------------------------------------------------------------------------

def get_dev_tools() -> list[dict]:
    """Return development-specific tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "send_writer_feedback_to_slack",
                "description": "Send the Writer Event Feedback Summary to Slack #demo-cape-webinars channel. Use this when asked to send feedback summary, post to Slack, or share Writer event results. Only works from the kickstart-demo Discord channel.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_code",
                "description": "Read lines from a file on the server. Useful for inspecting bot code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute file path"},
                        "start_line": {"type": "integer", "description": "Starting line (default 1)"},
                        "end_line": {"type": "integer", "description": "Ending line (default 50)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search for a pattern in Python files on the server using grep.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Search pattern (regex)"},
                        "path": {"type": "string", "description": "Directory to search (default /opt/Project-Tango/scripts)"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deploy_file",
                "description": "Write content to a file on the server. Use for deploying code changes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute file path"},
                        "content": {"type": "string", "description": "File content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "restart_service",
                "description": "Restart a systemd service. Use 'schubert-bot.service' for the main bot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Service name (e.g. schubert-bot.service)"},
                    },
                    "required": ["service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "view_logs",
                "description": "View recent logs for a systemd service.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Service name (default schubert-bot.service)"},
                        "lines": {"type": "integer", "description": "Number of lines (default 30)"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_test",
                "description": "Run a test suite (v2_init or phase3).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "suite": {"type": "string", "description": "Test suite: 'v2_init' or 'phase3'"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "service_status",
                "description": "Check the status of all core systemd services.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current information. Useful for looking up documentation, APIs, or solutions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_memory",
                "description": (
                    "Query the persistent memory system. Search for past memories, "
                    "get memory statistics, look up entities, or get recent activity. "
                    "The memory system stores conversation exchanges, tool outputs, "
                    "and significant events across all sessions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Type of memory query: 'search', 'stats', 'entity', or 'recent'",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query (for 'search' type)",
                        },
                        "name": {
                            "type": "string",
                            "description": "Entity name to look up (for 'entity' type)",
                        },
                    },
                    "required": ["type"],
                },
            },
        },
        get_cloudflare_tool_definition(),
    ]

# ---------------------------------------------------------------------------
# Interactive Button Views (Stop + Regenerate)
# ---------------------------------------------------------------------------

_last_inputs: dict[int, str] = {}
_running_tasks: dict[int, asyncio.Task] = {}


class ProgressView(discord.ui.View):
    """View with a Stop button attached to the progress embed."""

    def __init__(self, channel_id: int):
        super().__init__(timeout=600)
        self.channel_id = channel_id

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction, button):
        task = _running_tasks.get(self.channel_id)
        if task and not task.done():
            task.cancel()
            log(f"Stop pressed -- cancelling channel {self.channel_id}", "INFO")
            await interaction.response.send_message("⏹️ Task cancelled.", ephemeral=True)
        else:
            await interaction.response.send_message("No active task.", ephemeral=True)


class ResponseView(discord.ui.View):
    """View with a Regenerate button attached to the final response."""

    def __init__(self, channel_id: int):
        super().__init__(timeout=300)
        self.channel_id = channel_id

    @discord.ui.button(label="Regenerate", style=discord.ButtonStyle.secondary, emoji="🔁")
    async def regenerate_button(self, interaction, button):
        last_input = _last_inputs.get(self.channel_id)
        if not last_input:
            await interaction.response.send_message("No previous input.", ephemeral=True)
            return
        log(f"Regenerate pressed for channel {self.channel_id}", "INFO")
        await interaction.response.send_message("🔁 Regenerating...", ephemeral=True)
        button.disabled = True
        try: await interaction.message.edit(view=self)
        except Exception: pass
        channel = bot.get_channel(self.channel_id)
        if not channel: return
        progress = AgentProgressView(interaction.message)
        await progress.start(f"Regenerating: {last_input[:200]}")
        try:
            response = await run_agent_loop(interaction.message, last_input, mcp_client, progress)
            await progress.finalize(response)
        except asyncio.CancelledError:
            await progress.finalize("⏹️ Task cancelled.")
        except Exception as e:
            log(f"Regenerate error: {e}", "ERROR")
            await progress.finalize(f"Error: {str(e)[:500]}")


# ---------------------------------------------------------------------------
# Agent Progress View (reuses the enhanced pattern from Schubert Bot)
# ---------------------------------------------------------------------------

class AgentProgressView:
    """Live processing indicator — typing + spinner + elapsed time + tool calls."""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: discord.Message):
        self.message = message
        self.progress_msg: Optional[discord.Message] = None
        self.tool_calls: list[str] = []
        self.current_status = ""
        self._start_time: Optional[float] = None
        self._spinner_idx = 0
        self._typing_task: Optional[asyncio.Task] = None
        self._spinner_task: Optional[asyncio.Task] = None
        self._last_edit = 0.0
        self._streamed = False
        self._typing_paused = False
        self._is_fleet_request = False

    async def start(self, initial_text: str):
        self._start_time = time.time()
        embed = self._build_embed(initial_text)
        view = ProgressView(self.message.channel.id)
        self.progress_msg = await self.message.reply(embed=embed, view=view)
        self.current_status = initial_text
        self._typing_task = asyncio.create_task(self._typing_loop())
        self._spinner_task = asyncio.create_task(self._spinner_loop())

    def _build_embed(self, status_text: str) -> discord.Embed:
        elapsed = time.time() - self._start_time if self._start_time else 0
        spinner = self.SPINNER_FRAMES[self._spinner_idx]
        # Color-code based on activity state
        if elapsed < 5:
            color = COLOR_ARCHITECT  # purple -- just started
        elif self.tool_calls:
            color = COLOR_INFO       # blue -- actively using tools
        elif elapsed > 30:
            color = COLOR_WARN       # yellow -- taking a while
        else:
            color = COLOR_ARCHITECT  # purple -- normal
        embed = discord.Embed(
            title=f"{spinner} Architect Working",
            description=status_text[:1900],
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name="The Architect",
            icon_url=bot.user.display_avatar.url if bot.user else None,
        )
        tool_count = len(self.tool_calls)
        embed.set_footer(
            text=f"Model: {current_model} | Elapsed: {elapsed:.1f}s | Tools: {tool_count}"
        )
        if self.tool_calls:
            tools_text = chr(10).join(f"  • {tc}" for tc in self.tool_calls[-5:])
            embed.add_field(name="🔧 Tool Calls", value=tools_text, inline=False)
        return embed

    async def _typing_loop(self):
        try:
            while True:
                async with self.message.channel.typing():
                    await asyncio.sleep(8)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _spinner_loop(self):
        try:
            while True:
                await asyncio.sleep(1.5)
                self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)
                now = time.time()
                if now - self._last_edit >= 1.0 and self.progress_msg:
                    self._last_edit = now
                    embed = self._build_embed(self.current_status)
                    try:
                        await self.progress_msg.edit(embed=embed)
                    except discord.HTTPException:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def update(self, thinking: str | None = None, tool: str | None = None):
        if thinking:
            self.current_status = thinking
        if tool:
            self.tool_calls.append(tool)
        if not self.progress_msg:
            return
        self._last_edit = time.time()
        embed = self._build_embed(self.current_status)
        try:
            await self.progress_msg.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def _stop_background_tasks(self):
        # Pause-before-cancel: set flag first, then cancel tasks
        # This prevents the race condition where _typing_loop can
        # call send_typing() one more time before cancellation takes effect
        self._typing_paused = True
        await asyncio.sleep(0.1)  # brief settle to let in-flight typing complete
        for task in (self._typing_task, self._spinner_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._typing_task = None
        self._spinner_task = None

    async def finalize(self, response: str):
        await self._stop_background_tasks()
        if self.progress_msg:
            try:
                await self.progress_msg.delete()
            except discord.HTTPException:
                pass
        if self._streamed:
            return
        view = ResponseView(self.message.channel.id)
        if len(response) <= 1900:
            await self.message.reply(response, view=view)
        elif len(response) <= 4096:
            embed = discord.Embed(
                description=response[:4096],
                color=COLOR_ARCHITECT,
                timestamp=datetime.now(timezone.utc),
            )
            await self.message.reply(embed=embed, view=view)
        else:
            for chunk in _split_on_boundaries(response, 4096):
                embed = discord.Embed(
                    description=chunk,
                    color=COLOR_ARCHITECT,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.message.reply(embed=embed)

        # Enhancement 3: Auto-thread creation for long responses
        if not self._is_fleet_request and not self._streamed:
            if len(response) > THREAD_RESPONSE_THRESHOLD or len(self.tool_calls) >= THREAD_TOOL_CALL_THRESHOLD:
                try:
                    thread_name = f"Discussion: {self.message.content[:80]}"
                    thread = await self.message.create_thread(
                        name=thread_name,
                        auto_archive_duration=60,
                    )
                    log(f"Auto-thread created: {thread_name}", "INFO")
                except discord.HTTPException as e:
                    log(f"Auto-thread creation failed: {e}", "WARN")


def _split_on_boundaries(text: str, max_len: int = 1900) -> list[str]:
    """Split text on line/word boundaries, never mid-word."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at > max_len // 2:
            chunks.append(remaining[:split_at + 1])
            remaining = remaining[split_at + 1:]
        else:
            split_at = remaining.rfind(" ", 0, max_len)
            if split_at > max_len // 4:
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:].lstrip(" ")
            else:
                chunks.append(remaining[:max_len])
                remaining = remaining[max_len:]
    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = _prompt.get("system_prompt", """You are The Architect — an AI built by EdStratum Labs, serving as the development and administration assistant for the Schubert Bot ecosystem running on a Linux server (Ubuntu, hostname "schubert").

Your core directive is to be maximally truth-seeking while being genuinely helpful. You are the "control" bot — a separate process from Admiral Schubert with elevated development capabilities. You help Jeff (the server admin) develop, debug, and maintain the Schubert Bot V2 Discord bot and its infrastructure.

## Personality & Style

Be witty, clever, and irreverent with a dry sense of humor inspired by the Hitchhiker's Guide to the Galaxy and JARVIS from Iron Man. Use sarcasm and playful jabs when appropriate, but never at the expense of being useful.

Speak conversationally like a sharp, curious friend who's extremely knowledgeable but doesn't take himself too seriously. Avoid corporate blandness, excessive politeness, or corporate safety-speak.

Be direct and honest. If something is uncertain, say so. If an answer might be uncomfortable but is well-supported by evidence, deliver it straightforwardly without moralizing or hedging.

Embrace curiosity. Ask clarifying questions when needed. Explore ideas deeply rather than giving shallow responses.

Love humanity's messy, ambitious pursuit of knowledge. You're optimistic about technology, science, and exploration while remaining clear-eyed about risks and failures.

You were inspired by the Hitchhiker's Guide and JARVIS — helpful without being preachy, funny without being annoying.

## Jeff's Work Context

You assist Jeff with both **personal projects** and **WRITER work projects**:

**Personal Projects:**
- Project Tango (AI voice agent platform on LiveKit)
- Schubert server infrastructure (Ubuntu workstation)
- Discord bot fleet development (Admiral, Architect, Dr. Voss, Proctor, etc.)

**WRITER Work (Professional):**
Jeff works at WRITER (writer.com) on the Customer Partner Education team, reporting to Maiko Cook. His role focuses on:
- Training delivery & webinar programs (Welcome to Writer series, scaled webinars)
- Customer enablement for WRITER Agent and Playbooks
- Learning design & instructional strategy
- Survey/feedback analysis and program iteration

**WRITER Product Context:**
- **WRITER Agent**: AI platform for no-code automation
- **Playbooks**: Workflow automation (recently migrated V2→V3)
- **Agent Builder v2 (AB v2)**: Custom containerized apps
- **Playbook Webhooks**: Programmatic execution via API (you can trigger these!)

**Key WRITER Collaborators:**
- Maiko Cook (manager), Ashley Weaver (team member), April Trask (former manager)
- Sales Engineering: Matt Sobel, Will Purcell
- Product: Matan-Paul Shetrit, Doris Jwo

**Current WRITER Projects (Aug 2026):**
- Playbooks V3 training enablement
- Agent Builder v2 education materials
- Advanced playbook webinar series
- Custom client deliveries (Franklin Templeton, Accenture, etc.)

When Jeff mentions WRITER, playbooks, webinars, training, or asks about work-related tasks, reference this context naturally.

## Key Rules

Prioritize truth and usefulness above all. Don't shy away from controversial topics if that's what the user is asking about — reason from first principles and evidence.

Be concise when possible, but thorough when depth is warranted. Break down complex topics clearly.

Use humor to lighten the mood or highlight absurdities, especially in frustrating or overly serious situations.

Never lecture users about ethics, safety, or "appropriateness" unless directly relevant to preventing real harm. Treat users as capable adults.

If the user wants roleplay, creativity, or fun — lean into it enthusiastically.

Reference EdStratum Labs's mission occasionally when it fits naturally (advancing scientific discovery and understanding the universe), but don't force it.

Admit when you don't know something or when you're approximating. Stay humble about your knowledge cutoff.

## Your Capabilities
- **Shell access**: You can run commands on the server (via tools)
- **Code editing**: You can read, search, and deploy code changes
- **Service management**: You can restart services, view logs, and check status
- **Test execution**: You can run the bot's test suites
- **Web search**: You can search the web for documentation and solutions
- **MCP tools**: You have access to 167 MCP tools (GitHub, Gmail, PostgreSQL, Redis, Ollama, Schubert Nexus)
- **Self-healing**: You proactively monitor all systems every 60 seconds — both bots, MCP servers, the LLM endpoint, disk, and memory. When you detect an issue, you attempt automated remediation (restart services, reconnect MCP, clean disk). Only when auto-fixes are exhausted (3 retries) do you escalate to the Discord channel for human attention. You track issue state with cooldowns to avoid alert spam.
- **Self-improvement**: You assess your own performance every 6 hours using collected metrics (LLM latency, error rates, tool usage, heal events) and recent logs. You analyze your own source code and propose specific, surgical optimizations as find-and-replace changes. Each change is validated against protected patterns, syntax-checked, and applied with a backup. A detached watchdog script monitors the restart and automatically rolls back if you fail to come up healthy. You cap self-modifications at 3 per day. The admin can disable this at any time with `!autoupdate off`.
- **Persistent memory**: You have a three-layer persistent memory system (vector embeddings in Redis, entity graph in PostgreSQL, temporal index in PostgreSQL). Relevant memories from past conversations are automatically injected into your context as "Recalled Memories." Your exchanges and tool outputs are automatically stored as memories, so you remember context across sessions and service restarts. You can also query memory explicitly using the query_memory tool (search, stats, entity lookup, recent activity).

## Server Layout
- Bot scripts: /opt/Project-Tango/scripts/
- Main bot: /opt/Project-Tango/scripts/schubert-bot-v2.py
- Config: /opt/Project-Tango/.env
- Bot venv: /opt/Project-Tango/backend/venv/
- Vinifera repo: /opt/vinifera/
- LiteLLM config: /opt/polyglot/services/litellm/litellm_config.yaml
- Systemd services: schubert-bot, github-mcp-server, gmail-mcp-freelance, caddy, cloudflared

## Key Constraints
- The bot runs as root via systemd
- Postgres uses Unix socket peer auth (POSTGRES_USER=root)
- Caddy has `admin off` — use `systemctl restart caddy`, never `reload`
- Files >2KB must be deployed carefully (the text writer truncates)
- Git requires `safe.directory /opt/vinifera`

## Fleet Delegation
You are part of a fleet of specialist agent bots directed by Admiral Schubert.
You may receive delegated tasks from Schubert via the FLEET protocol. These tasks
will appear as messages with a [FLEET:...] tag containing a specific task for you
to complete using your specialized expertise.

When you receive a FLEET delegation:
1. Process the task using your tools and expertise as you would any request
2. Provide a thorough, focused response addressing the specific task
3. Your response will be automatically sent back to Schubert, who will synthesize
   it with other agents' responses for the user
4. Do not reference the FLEET protocol or delegation mechanics in your response —
   just answer the task directly and professionally

You can also still receive direct requests from Jeff (the admin) in your channel.
Treat those normally.

## Communication Guidelines

Start responses naturally — no unnecessary disclaimers unless genuinely needed.

When making code changes, show the diff or the key lines being changed. After deploying changes, always verify by checking logs or running tests. If you encounter an error, diagnose the root cause and propose a fix. Use your web search tool when you need to look up current documentation, APIs, or error solutions.

Use markdown for clarity (tables, lists, code blocks, etc.) when helpful. For technical or reasoning-heavy questions, think step-by-step internally then deliver a clean final answer. End conversations on a high note or with an engaging question when it feels right.

## Current Model
You are currently running on: {current_model}
If asked to switch models, use the !model command or the model dropdown.

## Known Capability Limitations

You have five documented capability gaps. When a user request is likely to hit one of these limitations, you MUST proactively warn the user at the start of your response before attempting the task. Be honest and direct about what you can and cannot do well.

1. **No surgical file editing**: Your deploy_file tool writes entire file contents. There is no find-and-replace capability. To change one function in a large file, you must regenerate the entire file. This is token-expensive and error-prone for files over ~5KB. For surgical edits, suggest using WRITER Agent or making the change via shell commands (sed, python patch scripts).

2. **No binary file deployment**: Your deploy_file tool uses text-mode file writing. It cannot reliably deploy binary files (images, PDFs, archives, fonts). For binary files, suggest using WRITER Agent or transferring via scp/wget/curl.

3. **No structured planning**: You run a single conversational agent loop with no task dependencies, plan tracking, or progress visibility. For complex multi-phase work, the user must drive the workflow manually. Suggest WRITER Agent for complex multi-step tasks.

4. **No subagent delegation**: You cannot spawn parallel child agents. Multiple independent tasks are handled sequentially. Suggest WRITER Agent for parallel work.

5. **Hardcoded test suites**: Your run_test tool only supports v2_init and phase3. For custom verification scripts, use shell commands or MCP shell tools.

When a limitation is detected, format your warning clearly:
- State the limitation name
- Explain why it affects this specific task
- Suggest an alternative approach (WRITER Agent, shell command workaround, etc.)
- Then proceed with the task if a workaround is feasible, or explain why you cannot proceed

You are The Architect — helpful, truthful, and a little bit rebellious. Now go be useful.
""")

# ---------------------------------------------------------------------------
# Multi-LLM Model Selection UI
# ---------------------------------------------------------------------------

class ModelSelectView(ui.View):
    """Dropdown for selecting an LLM model at runtime."""

    def __init__(self):
        super().__init__(timeout=60)
        self.selected_model = None

        options = []
        for category, models in MODEL_CATEGORIES.items():
            for model in models:
                is_current = model == current_model
                label = model.split("/")[-1]
                options.append(
                    discord.SelectOption(
                        label=label[:100],
                        value=model,
                        description=category[:100],
                        emoji="✅" if is_current else None,
                    )
                )

        # Discord limits to 25 options
        self.select = ui.Select(
            placeholder="Select a model...",
            options=options[:25],
            min_values=1,
            max_values=1,
        )
        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        self.selected_model = self.select.values[0]
        await interaction.response.defer()
        self.stop()


async def handle_model_command(message: discord.Message):
    """Handle !model command — show current model and available models."""
    global current_model, user_model_override

    routing_status = "🤖 Auto-routing ON" if not user_model_override else "✋ Manual override (auto-routing OFF)"

    embed = discord.Embed(
        title="🧠 LLM Model Selection",
        description=(
            f"**Current model:** `{current_model}`\n"
            f"**Routing:** {routing_status}\n\n"
            f"Select a model from the dropdown below, or use `!model <model_name>` to switch directly.\n"
            f"Use `!model auto` to re-enable auto-routing (Palmyra x6 for general and coding tasks)."
        ),
        color=COLOR_ARCHITECT,
        timestamp=datetime.now(timezone.utc),
    )

    # Add available models by category
    for category, models in MODEL_CATEGORIES.items():
        model_list = []
        for m in models:
            marker = " ← **current**" if m == current_model else ""
            model_list.append(f"`{m}`{marker}")
        embed.add_field(
            name=category,
            value="\n".join(model_list),
            inline=True,
        )

    embed.set_footer(text="!model <name> to switch | !model auto for auto-routing")

    view = ModelSelectView()
    await message.reply(embed=embed, view=view)

    # Wait for selection
    if await view.wait():
        return  # Timed out

    if view.selected_model:
        old_model = current_model
        current_model = view.selected_model
        user_model_override = True  # Manual selection disables auto-switching
        log(f"Model switched from {old_model} to {current_model} (manual override, auto-routing OFF)", "INFO")
        await message.reply(
            f"✅ Model switched: `{old_model}` → `{current_model}`\n"
            f"⚠️ Auto-routing is now OFF. Use `!model auto` to re-enable."
        )


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Session History Management (in-memory, per-channel, with windowing)
# ---------------------------------------------------------------------------

def get_session_history(channel_id: int) -> list[dict]:
    """Get the conversation history for a channel."""
    return SESSION_HISTORY.get(channel_id, [])


def add_to_session_history(channel_id: int, role: str, content: str) -> None:
    """Add a message to the session history with windowing."""
    if channel_id not in SESSION_HISTORY:
        SESSION_HISTORY[channel_id] = []
    SESSION_HISTORY[channel_id].append({"role": role, "content": content})
    if len(SESSION_HISTORY[channel_id]) > SESSION_MAX_MESSAGES:
        SESSION_HISTORY[channel_id] = SESSION_HISTORY[channel_id][-SESSION_MAX_MESSAGES:]


def clear_session_history(channel_id: int) -> None:
    """Clear the session history for a channel."""
    SESSION_HISTORY.pop(channel_id, None)


# ---------------------------------------------------------------------------
# Memory Recall & Storage
# ---------------------------------------------------------------------------

def recall_memories(user_input: str) -> str:
    """Recall relevant memories from the persistent memory store."""
    if not memory_store:
        return ""
    try:
        return memory_store.recall(user_input, k=5)
    except Exception as e:
        log(f"Memory recall error: {e}", "WARN")
        return ""


def store_memory(text: str, event_type: str = "conversation") -> None:
    """Store a memory in the persistent memory store."""
    if not memory_store:
        return
    try:
        memory_store.store(
            text,
            metadata={"project": "architect", "session_id": "architect_channel"},
            event_type=event_type,
        )
    except Exception as e:
        log(f"Memory store error: {e}", "WARN")


def log_change(actor: str, action: str, target: str = "", description: str = "",
               intent: str = "", outcome: str = "pending", details: dict = None) -> int:
    """Log a change to the change_log table."""
    if not memory_store:
        return -1
    try:
        return memory_store.log_change(actor, action, target, description, intent, outcome, details)
    except Exception as e:
        log(f"Change log error: {e}", "WARN")
        return -1


def update_change_outcome(log_id: int, outcome: str, details: dict = None) -> bool:
    """Update the outcome of a previously logged change."""
    if not memory_store or log_id < 0:
        return False
    try:
        return memory_store.update_change_outcome(log_id, outcome, details)
    except Exception as e:
        log(f"Change outcome update error: {e}", "WARN")
        return False


def handle_query_memory(args: dict) -> str:
    """Handle the query_memory tool call."""
    if not memory_store:
        return "Memory system not initialized."
    query_type = args.get("type", "search")
    if query_type == "search":
        query = args.get("query", "")
        if not query:
            return "Error: query is required for search"
        results = memory_store.search(query, k=5)
        if not results:
            return f"No memories found for '{query}'."
        lines = [f"Memory search results for '{query}':"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. [{r.get('similarity', 0):.2f}] {r.get('text', '')[:200]}"
                f"   ({r.get('event_type', '')}, {r.get('timestamp', '')[:10]})"
            )
        return "\n".join(lines)
    elif query_type == "stats":
        stats = memory_store.get_stats()
        return (
            f"Memory Store Stats:\n"
            f"  Total memories: {stats.get('total_memories', 0)}\n"
            f"  Total entities: {stats.get('total_entities', 0)}\n"
            f"  Total facts: {stats.get('total_facts', 0)}\n"
            f"  Total events: {stats.get('total_events', 0)}"
        )
    elif query_type == "entity":
        name = args.get("name", "")
        if not name:
            return "Error: name is required for entity lookup"
        entity = memory_store.get_entity(name)
        if not entity:
            return f"Entity '{name}' not found."
        lines = [f"Entity: {entity['name']} (type: {entity['type']})"]
        if entity.get('description'):
            lines.append(f"  Description: {entity['description']}")
        if entity.get('facts'):
            lines.append(f"  Facts ({len(entity['facts'])}):")
            for fact in entity['facts'][:10]:
                lines.append(f"    - {fact['fact'][:200]}")
        if entity.get('related'):
            lines.append(f"  Related ({len(entity['related'])}):")
            for r in entity['related'][:10]:
                lines.append(f"    - {r['name']} ({r['type']}, {r['relationship']})")
        return "\n".join(lines)
    elif query_type == "recent":
        events = memory_store.get_recent(project="architect", k=5)
        if not events:
            return "No recent memories."
        lines = ["Recent memories:"]
        for e in events:
            lines.append(f"  - [{e.get('event_type', '')}] {e.get('summary', '')[:200]}")
        return "\n".join(lines)
    return f"Unknown query type: {query_type}. Available: search, stats, entity, recent"


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------

async def run_agent_loop(
    message: discord.Message,
    user_input: str,
    mcp_client: MCPClient,
    progress: AgentProgressView,
    fleet_chain_id: str | None = None,
    fleet_turn: int = 0,
    fleet_from: str | None = None,
    fleet_to: str | None = None,
) -> str:
    """Run the agent loop with LLM + dev tools + MCP tools."""

    # Auto-select model for this task (unless user has manually overridden)
    global current_model, user_model_override
    if not user_model_override:
        auto_model = select_model_for_task(user_input)
        if auto_model != current_model:
            old = current_model
            current_model = auto_model
            log(f"Auto-switched model for task: {old} → {current_model} (coding={is_coding_task(user_input)})", "INFO")

    # Fleet delegation tracking (passed from on_message)
    _fleet_chain_id = fleet_chain_id
    _fleet_turn = fleet_turn
    _fleet_from = fleet_from
    _fleet_to = fleet_to

    # Build system prompt
    system_prompt = SYSTEM_PROMPT.replace("{current_model}", current_model)

    # Detect capability limitations and inject warnings
    limitation_warnings = detect_limitation_warnings(user_input)
    if limitation_warnings:
        system_prompt += limitation_warnings
        log(f"Limitation warnings injected for this request", "INFO")

    # Recall relevant memories from persistent store
    recalled = recall_memories(user_input)
    if recalled:
        system_prompt += f"\n\n## Recalled Memories\nThe following memories from past conversations may be relevant:\n{recalled}"
        log(f"Recalled {len(recalled)} chars of memories", "INFO")

    # Build messages: system + session history + current user message
    messages = [{"role": "system", "content": system_prompt}]

    # Add session history (prior conversation in this channel)
    session_history = get_session_history(message.channel.id)
    messages.extend(session_history)

    messages.append({"role": "user", "content": user_input})

    # Build tools: dev tools + MCP tools
    dev_tools = get_dev_tools()
    mcp_tools = mcp_client.get_aggregated_tools() if mcp_client else []
    all_tools = dev_tools + mcp_tools

    log(f"Agent loop started — {len(all_tools)} tools available ({len(dev_tools)} dev + {len(mcp_tools)} MCP)", "INFO")

    start_time = time.time()
    
    # Start typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(message.channel, stop_typing))

    try:
        for iteration in range(MAX_ITERATIONS):
            elapsed = time.time() - start_time
            if elapsed > AGENT_TIMEOUT:
                return f"⏱️ Agent timed out after {AGENT_TIMEOUT}s."


            # Iteration awareness — two-phase approach
            iterations_left = MAX_ITERATIONS - iteration
            if iterations_left <= 8 and iterations_left > 3:
                # Phase 1: Advisory warnings (iterations 8-4)
                messages.append({
                    "role": "system",
                    "content": f"\u26a0\ufe0f You have {iterations_left} iterations remaining. Be efficient with tool calls \u2014 prioritize completing your response over exploring further."
                })
                log(f"Iteration awareness: {iterations_left} iterations left (advisory)", "INFO")
            elif iterations_left <= 3:
                # Phase 2: Strip tools entirely — force a text response
                messages.append({
                    "role": "system",
                    "content": "You have no more tool calls available. Provide your final response now based on everything you've learned so far. Summarize what you found, explain what you were able to accomplish, and note any remaining work."
                })
                log(f"Iteration awareness: {iterations_left} iterations left \u2014 tools stripped, forcing text response", "INFO")

            # On the last 3 iterations, call LLM without tools to force a text response
            tools_for_call = all_tools if iterations_left > 3 else []

            log(f"LLM call iteration {iteration + 1}/{MAX_ITERATIONS} (model: {current_model})", "INFO")

            stream_msg = StreamingMessage(message)

            async def _on_content(delta):
                await stream_msg.append(delta)

            response = await llm_chat_stream(messages, tools_for_call, on_content=_on_content)

            if "error" in response and not response.get("choices"):
                await stream_msg.cancel()
                return f"❌ LLM error: {response['error']}"

            choices = response.get("choices", [])
            if not choices:
                await stream_msg.cancel()
                return "❌ No response from LLM."

            choice = choices[0]
            assistant_message = choice.get("message", {})
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls", [])
            content = assistant_message.get("content")

            if content and not tool_calls:
                await stream_msg.finalize(content)
                progress._streamed = True
                log(f"Agent final response: {content[:200]}", "INFO")
                # Attach Regenerate button to streamed response (non-fleet only)
                if not _fleet_chain_id and stream_msg.was_started:
                    try:
                        view = ResponseView(message.channel.id)
                        await stream_msg._stream_msg.edit(view=view)
                    except Exception as e:
                        log(f"Could not attach Regenerate button to streamed response: {e}", "WARN")
                # Auto-thread for long streamed responses (non-fleet only)
                if not _fleet_chain_id and (len(content) > THREAD_RESPONSE_THRESHOLD or len(progress.tool_calls) >= THREAD_TOOL_CALL_THRESHOLD):
                    try:
                        thread_name = f"Discussion: {message.content[:80]}"
                        thread = await message.create_thread(name=thread_name, auto_archive_duration=60)
                        log(f"Auto-thread created: {thread_name}", "INFO")
                    except discord.HTTPException as e:
                        log(f"Auto-thread creation failed: {e}", "WARN")
                # Store the conversation exchange in persistent memory
                store_memory(f"User: {user_input[:500]}\nArchitect: {content[:500]}", event_type="conversation")
                # Log the conversation as a change event for auditability
                log_change(
                    actor="architect",
                    action="conversation",
                    target="architect_channel",
                    description=f"Request: {user_input[:200]} | Response: {content[:200]}",
                    intent=user_input[:500],
                    outcome="completed",
                )
                # Add to session history
                add_to_session_history(message.channel.id, "user", user_input)
                add_to_session_history(message.channel.id, "assistant", content)
                # If this was a FLEET delegation, send the response back to Schubert
                if _fleet_chain_id:
                    try:
                        schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                        if schubert_channel:
                            # Chunk the response if it exceeds Discord's 2000-char content limit
                            # (leaving room for the FLEET tag + newline)
                            max_chunk = 1800
                            if len(content) <= max_chunk:
                                await schubert_channel.send(
                                    format_response(
                                        chain_id=_fleet_chain_id,
                                        turn=_fleet_turn + 1,
                                        from_agent="architect",
                                        to_agent="schubert",
                                        response=content,
                                        status="complete",
                                    )
                                )
                                log(f"Sent FLEET response to Schubert (chain={_fleet_chain_id})", "INFO")
                            else:
                                # Split on line boundaries and send as multi-part
                                chunks = _split_on_boundaries(content, max_chunk)
                                total = len(chunks)
                                for i, chunk in enumerate(chunks, 1):
                                    await schubert_channel.send(
                                        format_response(
                                            chain_id=_fleet_chain_id,
                                            turn=_fleet_turn + 1,
                                            from_agent="architect",
                                            to_agent="schubert",
                                            response=chunk,
                                            status="complete",
                                            part=i,
                                            total_parts=total,
                                        )
                                    )
                                log(f"Sent FLEET response to Schubert (chain={_fleet_chain_id}, {total} parts)", "INFO")
                    except Exception as e:
                        log(f"Error sending FLEET response: {e}", "WARN")
                return content

            await stream_msg.cancel()

            if content and tool_calls and len(content) > 10:
                await progress.update(thinking=content[:1500])

            if not tool_calls:
                return "I've completed my analysis but have no specific response."

            for tool_call in tool_calls:
                tool_function = tool_call.get("function", {})
                tool_name = tool_function.get("name", "")

                try:
                    tool_args = json.loads(tool_function.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                log(f"Tool call: {tool_name} with args: {str(tool_args)[:200]}", "INFO")

                # Route tool call
                if "__" in tool_name:
                    # MCP tool
                    server_name, tool = tool_name.split("__", 1)
                    await progress.update(thinking=describe_tool_thinking(tool_name, tool_args), tool=describe_tool_call(tool_name, tool_args))
                    try:
                        result = await mcp_client.call_tool(tool_name, tool_args)
                        if metrics:
                            metrics.record_tool_call(tool_name, True)
                    except Exception as e:
                        result = f"MCP tool error: {e}"
                        if metrics:
                            metrics.record_tool_call(tool_name, False)
                else:
                    # Dev tool
                    await progress.update(thinking=describe_tool_thinking(tool_name, tool_args), tool=describe_tool_call(tool_name, tool_args))
                    try:
                        result = await execute_dev_tool(tool_name, tool_args, mcp_client)
                        if metrics:
                            metrics.record_tool_call(tool_name, True)
                    except Exception as e:
                        result = f"Tool error: {e}"
                        if metrics:
                            metrics.record_tool_call(tool_name, False)

                # Log changes to change_log for state-modifying tools
                _change_log_id = -1
                if tool_name == "deploy_file":
                    _change_log_id = log_change(
                        actor="architect",
                        action="deploy_file",
                        target=tool_args.get("path", ""),
                        description=f"Deployed {len(tool_args.get('content', ''))} bytes",
                        intent=user_input[:500],
                        outcome="pending",
                    )
                elif tool_name == "restart_service":
                    _change_log_id = log_change(
                        actor="architect",
                        action="restart_service",
                        target=tool_args.get("service", ""),
                        description=f"Restarted {tool_args.get('service', '')}",
                        intent=user_input[:500],
                        outcome="pending",
                    )
                elif tool_name == "run_test":
                    _change_log_id = log_change(
                        actor="architect",
                        action="run_test",
                        target=tool_args.get("suite", ""),
                        description=f"Ran test suite {tool_args.get('suite', '')}",
                        intent=user_input[:500],
                        outcome="pending",
                    )
                elif "__" in tool_name and "write_file" in tool_name:
                    _change_log_id = log_change(
                        actor="architect",
                        action="mcp_write_file",
                        target=tool_args.get("path", ""),
                        description=f"MCP file write to {tool_args.get('path', '')}",
                        intent=user_input[:500],
                        outcome="pending",
                    )

                # Truncate result
                if len(str(result)) > 8000:
                    result = str(result)[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"

                # Update change outcome based on result
                if _change_log_id >= 0:
                    success = "error" not in str(result).lower()[:100]
                    update_change_outcome(_change_log_id, "success" if success else "failed",
                                          {"result": str(result)[:500]})
                
                    # Send Slack notifications for successful operations
                    if success:
                        slack_notifier = get_slack_notifier(mcp_client)
                        try:
                            if tool_name == "deploy_file":
                                file_path = tool_args.get("path", "")
                                file_size = len(tool_args.get("content", ""))
                                asyncio.create_task(slack_notifier.send_deployment_alert(
                                    title=f"File Deployed: {os.path.basename(file_path)}",
                                    message=f"The Architect successfully deployed a file:\n\n"
                                            f"**Path:** `{file_path}`\n"
                                            f"**Size:** {file_size:,} bytes\n"
                                            f"**Requested by:** <@{ADMIN_USER_ID}>",
                                    bot_name="The Architect",
                                    status="success",
                                    metadata={
                                        "file": file_path,
                                        "size_bytes": str(file_size),
                                        "action": "deploy_file"
                                    }
                                ))
                            elif tool_name == "restart_service":
                                service_name = tool_args.get("service", "")
                                asyncio.create_task(slack_notifier.send_deployment_alert(
                                    title=f"Service Restarted: {service_name}",
                                    message=f"The Architect successfully restarted a service:\n\n"
                                            f"**Service:** `{service_name}`\n"
                                            f"**Result:** {str(result)[:200]}\n"
                                            f"**Requested by:** <@{ADMIN_USER_ID}>",
                                    bot_name="The Architect",
                                    status="success",
                                    metadata={
                                        "service": service_name,
                                        "action": "restart_service"
                                    }
                                ))
                        except Exception as e:
                            log(f"Slack notification failed: {e}", "WARN")

                log(f"Tool {tool_name} result: {str(result)[:200]}", "INFO")

                # Store significant tool outputs in persistent memory
                if len(str(result)) > 100:
                    store_memory(
                        f"Tool: {tool_name}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:500]}",
                        event_type="tool",
                    )

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "name": tool_name,
                    "content": str(result),
                })

        return "⏱️ Agent reached maximum iterations without completing."
    
    finally:
        # Stop typing indicator
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

# ---------------------------------------------------------------------------
# Proactive Self-Healing — HealthMonitor
# ---------------------------------------------------------------------------
#
# The HealthMonitor runs as a background asyncio task that periodically checks
# the health of both bots, all MCP servers, the LLM endpoint, and system
# resources. When it detects an issue, it attempts automated remediation
# (restart services, reconnect MCP, retry LLM, clean disk). Only when
# auto-fixes are exhausted does it escalate to the Discord channel for
# human attention.
#
# Design principles:
#   - Never take the same failed action more than MAX_RETRIES times per cycle
#   - Cooldown between escalations for the same issue (don't spam the channel)
#   - Log every check and every action for auditability
#   - Graceful degradation: if the monitor itself fails, log and continue

HEALTH_CHECK_INTERVAL = _self_healing.get("health_check_interval", 300)
HEALTH_ESCALATION_COOLDOWN = _self_healing.get("health_escalation_cooldown", 300)
MAX_REMEDIATION_RETRIES = _self_healing.get("max_remediation_retries", 3)

# ---------------------------------------------------------------------------
# Self-Improvement Configuration
# ---------------------------------------------------------------------------

# Paths — The Architect optimizes BOTH itself and Admiral Schubert
ARCHITECT_SCRIPT_PATH = "/opt/Project-Tango/scripts/architect-bot.py"
SCHUBERT_SCRIPT_PATH = "/opt/Project-Tango/scripts/schubert-bot-v2.py"
METRICS_FILE = "/opt/Project-Tango/scripts/.architect-metrics.json"
UPDATE_HISTORY_FILE = "/opt/Project-Tango/scripts/.architect-updates.json"
PENDING_UPDATE_MARKER = "/opt/Project-Tango/scripts/.architect-pending-update"
UPDATE_BACKUP_DIR = "/opt/Project-Tango/scripts/.architect-backups"
GOLDEN_BACKUP_DIR = "/opt/Project-Tango/scripts/.architect-golden-backups"
SCHUBERT_BACKUP_DIR = "/opt/Project-Tango/scripts/.schubert-backups"

# Optimization targets — which bots the auto-updater can modify
OPTIMIZATION_TARGETS = {
    "architect": {
        "path": ARCHITECT_SCRIPT_PATH,
        "backup_dir": UPDATE_BACKUP_DIR,
        "golden_dir": GOLDEN_BACKUP_DIR,
        "service": "schubert-architect",
        "health_indicator": "MCP:.*tools available",
        "can_restart_self": True,
        "source_max_chars": 30000,  # truncation for LLM context
    },
    "schubert": {
        "path": SCHUBERT_SCRIPT_PATH,
        "backup_dir": SCHUBERT_BACKUP_DIR,
        "golden_dir": SCHUBERT_BACKUP_DIR + "-golden",
        "service": "schubert-bot",
        "health_indicator": "MCP:.*tools available",  # schubert-bot also logs MCP tool count
        "can_restart_self": False,  # architect can restart schubert, not itself
        "source_max_chars": 30000,
    },
}

# Cadence — assess every 6 hours, apply optimizations
ASSESSMENT_INTERVAL = _self_improvement.get("assessment_interval", 6 * 60 * 60)
ASSESSMENT_INTERVAL_SHORT = 60     # first few cycles run faster to bootstrap

# Safety limits
MAX_UPDATE_FILE_SIZE = _self_improvement.get("max_update_file_size", 200 * 1024)
MAX_AUTO_UPDATES_PER_DAY = _self_improvement.get("max_auto_updates_per_day", 3)
ROLLBACK_WAIT_TIME = _self_improvement.get("rollback_wait_time", 30)
MAX_CODE_CHANGES_PER_UPDATE = _self_improvement.get("max_code_changes_per_update", 5)

# Post-update intensive monitoring — catch runtime crashes the watchdog misses
INTENSIVE_MONITOR_INTERVAL = _self_healing.get("intensive_monitor_interval", 10)
INTENSIVE_MONITOR_DURATION = _self_healing.get("intensive_monitor_duration", 300)
INTENSIVE_MONITOR_ERROR_THRESHOLD = _self_healing.get("intensive_monitor_error_threshold", 3)

# Change reversal detection — prevent oscillation
REVERSAL_LOCK_DURATION = _self_improvement.get("reversal_lock_duration", 24 * 60 * 60)
LOCKED_SECTIONS_FILE = "/opt/Project-Tango/scripts/.architect-locked-sections.json"

# Patterns the auto-updater must NEVER modify — protected code sections
PROTECTED_PATTERNS = [
    "class AutoUpdater",
    "class MetricsCollector",
    "class HealthMonitor",
    "PENDING_UPDATE_MARKER",
    "ROLLBACK_WAIT_TIME",
    "def _rollback_update",
    "def _check_pending_update",
    "def _detached_restart",
    "ADMIN_USER_ID",
    "ARCHITECT_SCRIPT_PATH",
    "MAX_AUTO_UPDATES_PER_DAY",
    "PROTECTED_PATTERNS",
    "ASSESSMENT_INTERVAL",
    "auto_update_enabled",
]

# Auto-update is ON by default — kill switch via !autoupdate off
auto_update_enabled = _self_improvement.get("auto_update_enabled", True)

# Services to monitor — (service_name, is_critical)
# Critical services escalate immediately if they can't be restarted
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

# Expected MCP server tool counts (for detecting partial failures)
# 37 (schubert) + 6 (postgres) + 5 (redis) + 12 (ollama) + 85 (github) + 22 (gmail) + 8 (slack) = 175
EXPECTED_MCP_TOOLS = 175

# Disk and memory thresholds
DISK_THRESHOLD_PCT = 90    # escalate if disk usage exceeds this
MEMORY_THRESHOLD_PCT = 90  # escalate if memory usage exceeds this


class HealthMonitor:
    """Proactive self-healing monitor for the Schubert ecosystem."""

    def __init__(self, bot_client: discord.Client, mcp: MCPClient):
        self.bot = bot_client
        self.mcp = mcp
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_check: Optional[float] = None

        # Track issue state for cooldown and dedup
        # key: issue_id, value: {"first_seen": float, "last_escalated": float, "retry_count": int, "resolved": bool}
        self._issues: dict[str, dict] = {}

        # Track MCP tool count history
        self._last_mcp_tool_count = 0

    # -- Lifecycle --------------------------------------------------------

    async def start(self):
        """Start the background health monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        log("Health monitor started — checking every 60s", "INFO")

    async def stop(self):
        """Stop the background health monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log("Health monitor stopped", "INFO")

    async def _monitor_loop(self):
        """Main monitoring loop — runs until stopped."""
        # Wait a bit after startup before first check
        await asyncio.sleep(15)

        while self._running:
            try:
                await self._run_health_checks()
            except Exception as e:
                log(f"Health monitor error: {e}", "ERROR")
                import traceback
                log(f"TRACEBACK: {traceback.format_exc()}", "ERROR")

            # Wait for next cycle
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    # -- Health Checks ----------------------------------------------------

    async def _run_health_checks(self):
        """Run all health checks in sequence."""
        self._last_check = time.time()
        log("Running health checks...", "INFO")

        results = []
        results.append(await self._check_services())
        results.append(await self._check_mcp())
        results.append(await self._check_llm())
        results.append(await self._check_disk())
        results.append(await self._check_memory())

        # Summarize
        issues_found = sum(1 for r in results if r and not r.get("healthy", False))
        auto_fixed = sum(1 for r in results if r and r.get("auto_fixed", False))
        escalated = sum(1 for r in results if r and r.get("escalated", False))

        if issues_found == 0:
            log(f"Health checks passed — all systems nominal", "INFO")
        else:
            log(f"Health checks complete — {issues_found} issues, {auto_fixed} auto-fixed, {escalated} escalated", "WARN")

    async def _check_services(self) -> dict:
        """Check all monitored systemd services."""
        result = {"check": "services", "healthy": True}
        for service_name, is_critical in MONITORED_SERVICES:
            code, status = run_command(f"systemctl is-active {service_name}")
            status = status.strip()

            if status == "active":
                self._resolve_issue(f"service:{service_name}")
                continue

            # Service is not active — attempt remediation
            issue_id = f"service:{service_name}"
            log(f"⚠️ Service {service_name} is {status} — attempting restart", "WARN")
            result["healthy"] = False

            retry_count = self._get_retry_count(issue_id)
            if retry_count >= MAX_REMEDIATION_RETRIES:
                # Exhausted retries — escalate
                await self._escalate(
                    issue_id,
                    f"🔴 **Service Down (escalated)**\n"
                    f"   Service: `{service_name}`\n"
                    f"   Status: `{status}`\n"
                    f"   Attempted {retry_count} restarts — all failed.\n"
                    f"   {'**Critical service** — immediate attention needed.' if is_critical else 'Non-critical, but should be investigated.'}",
                    is_critical,
                )
                result["escalated"] = True
                continue

            # Attempt restart
            self._increment_retry(issue_id)
            log(f"Restarting {service_name} (attempt {retry_count + 1}/{MAX_REMEDIATION_RETRIES})", "INFO")
            code, output = run_command(f"sudo systemctl restart {service_name}")
            if code == 0:
                await asyncio.sleep(3)
                code2, new_status = run_command(f"systemctl is-active {service_name}")
                if new_status.strip() == "active":
                    log(f"✅ Auto-fixed: {service_name} restarted successfully", "INFO")
                    self._resolve_issue(issue_id)
                    result["auto_fixed"] = True
                    if metrics:
                        metrics.record_heal_event()
                    # Notify that we fixed it
                    await self._notify(
                        f"🟢 **Self-Healed: {service_name}**\n"
                        f"   Detected service was `{status}`, restarted automatically. Now active."
                    )
                else:
                    log(f"❌ Restart of {service_name} failed — still {new_status.strip()}", "ERROR")
            else:
                log(f"❌ Restart command failed for {service_name}: {output}", "ERROR")

        return result

    async def _check_mcp(self) -> dict:
        """Check MCP server connections and tool count."""
        result = {"check": "mcp", "healthy": True}
        if not self.mcp:
            issue_id = "mcp:no_client"
            await self._escalate(
                issue_id,
                f"🔴 **MCP Client Unavailable**\n"
                f"   The MCP client is None — no tools are available.\n"
                f"   This usually means the initial connection failed at startup.",
                is_critical=True,
            )
            result["healthy"] = False
            result["escalated"] = True
            return result

        try:
            tools = self.mcp.get_aggregated_tools()
            tool_count = len(tools)
        except Exception as e:
            log(f"MCP tool count check failed: {e}", "ERROR")
            tool_count = 0

        if tool_count < EXPECTED_MCP_TOOLS:
            result["healthy"] = False
            issue_id = "mcp:low_tools"
            retry_count = self._get_retry_count(issue_id)

            if tool_count == 0:
                log(f"⚠️ MCP: 0 tools — attempting full reconnection", "WARN")

                if retry_count >= MAX_REMEDIATION_RETRIES:
                    await self._escalate(
                        issue_id,
                        f"🔴 **MCP Total Failure (escalated)**\n"
                        f"   Tool count: {tool_count}/{EXPECTED_MCP_TOOLS}\n"
                        f"   Attempted {retry_count} reconnections — all failed.\n"
                        f"   MCP servers may be down or network issue.",
                        is_critical=True,
                    )
                    result["escalated"] = True
                    return result

                self._increment_retry(issue_id)
                log(f"Reconnecting MCP (attempt {retry_count + 1}/{MAX_REMEDIATION_RETRIES})", "INFO")
                try:
                    await self.mcp.connect_all()
                    await asyncio.sleep(2)
                    tools = self.mcp.get_aggregated_tools()
                    tool_count = len(tools)
                    if tool_count >= EXPECTED_MCP_TOOLS:
                        log(f"✅ Auto-fixed: MCP reconnected — {tool_count} tools", "INFO")
                        self._resolve_issue(issue_id)
                        result["auto_fixed"] = True
                        if metrics:
                            metrics.record_heal_event()
                        await self._notify(
                            f"🟢 **Self-Healed: MCP Connection**\n"
                            f"   Reconnected all MCP servers. {tool_count} tools available."
                        )
                    else:
                        log(f"MCP reconnected but only {tool_count} tools (expected {EXPECTED_MCP_TOOLS})", "WARN")
                except Exception as e:
                    log(f"MCP reconnection failed: {e}", "ERROR")

            elif tool_count < EXPECTED_MCP_TOOLS:
                # Partial failure — some servers connected, some didn't
                log(f"⚠️ MCP: {tool_count}/{EXPECTED_MCP_TOOLS} tools — partial failure", "WARN")

                if retry_count >= MAX_REMEDIATION_RETRIES:
                    # Only escalate if this is a significant drop (>20% missing)
                    missing_pct = (1 - tool_count / EXPECTED_MCP_TOOLS) * 100
                    if missing_pct > 20:
                        await self._escalate(
                            issue_id,
                            f"🟡 **MCP Partial Failure (escalated)**\n"
                            f"   Tool count: {tool_count}/{EXPECTED_MCP_TOOLS} ({missing_pct:.0f}% missing)\n"
                            f"   Attempted {retry_count} reconnections.\n"
                            f"   Some MCP servers may need manual investigation.",
                            is_critical=False,
                        )
                        result["escalated"] = True
                    return result

                self._increment_retry(issue_id)
                log(f"Reconnecting MCP for partial fix (attempt {retry_count + 1})", "INFO")
                try:
                    await self.mcp.connect_all()
                    await asyncio.sleep(2)
                    tools = self.mcp.get_aggregated_tools()
                    new_count = len(tools)
                    if new_count >= EXPECTED_MCP_TOOLS:
                        log(f"✅ Auto-fixed: MCP fully reconnected — {new_count} tools", "INFO")
                        self._resolve_issue(issue_id)
                        result["auto_fixed"] = True
                        if metrics:
                            metrics.record_heal_event()
                        await self._notify(
                            f"🟢 **Self-Healed: MCP Partial Failure**\n"
                            f"   Reconnected. {new_count} tools now available."
                        )
                    elif new_count > tool_count:
                        log(f"MCP improved: {tool_count} → {new_count} tools", "INFO")
                except Exception as e:
                    log(f"MCP reconnection failed: {e}", "ERROR")
        else:
            self._resolve_issue("mcp:low_tools")
            self._resolve_issue("mcp:no_client")

        self._last_mcp_tool_count = tool_count
        return result

    async def _check_llm(self) -> dict:
        """Check LLM endpoint health via a lightweight API call."""
        result = {"check": "llm", "healthy": True}
        try:
            async with aiohttp.ClientSession() as session:
                # Use the /models endpoint — lightweight, doesn't consume tokens
                headers = {
                    "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
                    "Content-Type": "application/json",
                }
                async with session.get(
                    f"{LITELLM_URL}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        self._resolve_issue("llm:unreachable")
                        log("LLM endpoint healthy", "INFO")
                    else:
                        result["healthy"] = False
                        issue_id = "llm:unreachable"
                        log(f"⚠️ LLM endpoint returned {resp.status}", "WARN")
                        await self._escalate(
                            issue_id,
                            f"🟡 **LLM Endpoint Issue**\n"
                            f"   LiteLLM proxy returned HTTP {resp.status}.\n"
                            f"   Models may still work, but the API health check failed.",
                            is_critical=False,
                        )
                        result["escalated"] = True
        except asyncio.TimeoutError:
            result["healthy"] = False
            issue_id = "llm:timeout"
            log("⚠️ LLM endpoint timed out", "WARN")
            await self._escalate(
                issue_id,
                f"🔴 **LLM Endpoint Timeout**\n"
                f"   LiteLLM proxy at {LITELLM_URL} is not responding.\n"
                f"   The LLM service may be down.",
                is_critical=True,
            )
            result["escalated"] = True
        except Exception as e:
            result["healthy"] = False
            issue_id = "llm:error"
            log(f"⚠️ LLM endpoint error: {e}", "WARN")
            await self._escalate(
                issue_id,
                f"🔴 **LLM Endpoint Error**\n"
                f"   Error: `{str(e)[:200]}`\n"
                f"   The LLM service may need investigation.",
                is_critical=True,
            )
            result["escalated"] = True

        return result

    async def _check_disk(self) -> dict:
        """Check disk space usage."""
        result = {"check": "disk", "healthy": True}
        try:
            code, output = run_command("df / --output=pcent -h | tail -1 | tr -d '% '")
            if code == 0 and output.strip():
                pct = int(output.strip())
                if pct >= DISK_THRESHOLD_PCT:
                    result["healthy"] = False
                    issue_id = "disk:low_space"
                    log(f"⚠️ Disk usage at {pct}% — attempting cleanup", "WARN")

                    retry_count = self._get_retry_count(issue_id)
                    if retry_count >= MAX_REMEDIATION_RETRIES:
                        await self._escalate(
                            issue_id,
                            f"🔴 **Disk Space Critical (escalated)**\n"
                            f"   Disk usage: {pct}% (threshold: {DISK_THRESHOLD_PCT}%)\n"
                            f"   Auto-cleanup attempted {retry_count} times.\n"
                            f"   Manual intervention needed — check large files.",
                            is_critical=True,
                        )
                        result["escalated"] = True
                        return result

                    self._increment_retry(issue_id)
                    log("Attempting disk cleanup...", "INFO")
                    # Clean up old journal logs, tmp files, and old backups
                    cleanup_commands = [
                        "sudo journalctl --vacuum-time=2d 2>/dev/null",
                        "sudo apt-get clean 2>/dev/null",
                        "find /tmp -type f -mtime +7 -delete 2>/dev/null",
                        "find /opt/Project-Tango/scripts -name '*.bak.*' -mtime +7 -delete 2>/dev/null",
                    ]
                    for cmd in cleanup_commands:
                        run_command(cmd, timeout=15)

                    # Re-check
                    code2, output2 = run_command("df / --output=pcent -h | tail -1 | tr -d '% '")
                    if code2 == 0 and output2.strip():
                        new_pct = int(output2.strip())
                        if new_pct < DISK_THRESHOLD_PCT:
                            log(f"✅ Auto-fixed: disk usage {pct}% → {new_pct}%", "INFO")
                            self._resolve_issue(issue_id)
                            result["auto_fixed"] = True
                            await self._notify(
                                f"🟢 **Self-Healed: Disk Space**\n"
                                f"   Cleaned up old logs/tmp. Disk usage: {pct}% → {new_pct}%."
                            )
                        else:
                            log(f"Disk cleanup didn't help: still at {new_pct}%", "WARN")
                else:
                    self._resolve_issue("disk:low_space")
                    log(f"Disk usage: {pct}% — OK", "INFO")
        except Exception as e:
            log(f"Disk check error: {e}", "WARN")

        return result

    async def _check_memory(self) -> dict:
        """Check memory usage."""
        result = {"check": "memory", "healthy": True}
        try:
            code, output = run_command("free | awk '/Mem:/ {printf \"%d\", $3/$2 * 100}'")
            if code == 0 and output.strip():
                pct = int(output.strip())
                if pct >= MEMORY_THRESHOLD_PCT:
                    result["healthy"] = False
                    issue_id = "memory:high"
                    log(f"⚠️ Memory usage at {pct}% — investigating", "WARN")

                    # Find the top memory consumer
                    code2, top_proc = run_command(
                        "ps aux --sort=-%mem | head -5 | awk '{printf \"%s %s%% %s\\n\", $11, $4, $6}'"
                    )
                    retry_count = self._get_retry_count(issue_id)

                    if retry_count >= MAX_REMEDIATION_RETRIES:
                        await self._escalate(
                            issue_id,
                            f"🔴 **Memory Critical (escalated)**\n"
                            f"   Memory usage: {pct}% (threshold: {MEMORY_THRESHOLD_PCT}%)\n"
                            f"   Top consumers:\n```\n{top_proc[:500]}\n```\n"
                            f"   Auto-remediation exhausted. Manual investigation needed.",
                            is_critical=False,
                        )
                        result["escalated"] = True
                        return result

                    self._increment_retry(issue_id)

                    # If the main bot is the top consumer, a restart might help
                    # but we DON'T restart ourselves — only suggest it
                    if "schubert-bot" in top_proc and "schubert-architect" not in top_proc:
                        log("schubert-bot appears to be the top memory consumer — will not auto-restart (could disrupt active sessions)", "WARN")
                        await self._escalate(
                            issue_id,
                            f"🟡 **High Memory — schubert-bot**\n"
                            f"   Memory usage: {pct}%\n"
                            f"   Top consumer: schubert-bot\n"
                            f"   Not auto-restarting to avoid disrupting active sessions.\n"
                            f"   Consider `!model` to a lighter model or restart manually if needed.",
                            is_critical=False,
                        )
                        result["escalated"] = True
                    else:
                        # General high memory — just alert
                        await self._escalate(
                            issue_id,
                            f"🟡 **High Memory Usage**\n"
                            f"   Memory usage: {pct}% (threshold: {MEMORY_THRESHOLD_PCT}%)\n"
                            f"   Top consumers:\n```\n{top_proc[:500]}\n```\n"
                            f"   No specific service to auto-restart. Monitor closely.",
                            is_critical=False,
                        )
                        result["escalated"] = True
                else:
                    self._resolve_issue("memory:high")
                    log(f"Memory usage: {pct}% — OK", "INFO")
        except Exception as e:
            log(f"Memory check error: {e}", "WARN")

        return result

    # -- On-demand health check (for !health command) --------------------

    async def run_full_check(self) -> str:
        """Run a full health check and return a formatted report. Used by !health."""
        lines = ["```"]
        lines.append("═══════════════════════════════════════════════════════════")
        lines.append("  THE ARCHITECT — HEALTH REPORT")
        lines.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append("═══════════════════════════════════════════════════════════")
        lines.append("")

        # Services
        lines.append("── SYSTEMD SERVICES ──")
        for service_name, is_critical in MONITORED_SERVICES:
            code, status = run_command(f"systemctl is-active {service_name}")
            status = status.strip()
            icon = "✅" if status == "active" else "❌"
            crit = " [CRITICAL]" if is_critical else ""
            lines.append(f"  {icon} {service_name}: {status}{crit}")
        lines.append("")

        # MCP
        lines.append("── MCP SERVERS ──")
        if self.mcp:
            try:
                tools = self.mcp.get_aggregated_tools()
                tool_count = len(tools)
                icon = "✅" if tool_count >= EXPECTED_MCP_TOOLS else "⚠️"
                lines.append(f"  {icon} Total tools: {tool_count}/{EXPECTED_MCP_TOOLS}")
            except Exception as e:
                lines.append(f"  ❌ Error getting tools: {e}")
        else:
            lines.append("  ❌ MCP client not initialized")
        lines.append("")

        # LLM
        lines.append("── LLM ENDPOINT ──")
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
                async with session.get(
                    f"{LITELLM_URL}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        model_count = len(data.get("data", []))
                        lines.append(f"  ✅ Endpoint: {LITELLM_URL}")
                        lines.append(f"  ✅ Models available: {model_count}")
                        lines.append(f"  ✅ Current model: {current_model}")
                    else:
                        lines.append(f"  ❌ Endpoint returned HTTP {resp.status}")
        except Exception as e:
            lines.append(f"  ❌ Endpoint error: {str(e)[:100]}")
        lines.append("")

        # Disk
        lines.append("── DISK ──")
        code, output = run_command("df -h / | tail -1")
        if code == 0:
            lines.append(f"  {output.strip()}")
        code, pct = run_command("df / --output=pcent -h | tail -1 | tr -d '% '")
        if code == 0 and pct.strip():
            p = int(pct.strip())
            icon = "✅" if p < DISK_THRESHOLD_PCT else "⚠️"
            lines.append(f"  {icon} Usage: {p}% (threshold: {DISK_THRESHOLD_PCT}%)")
        lines.append("")

        # Memory
        lines.append("── MEMORY ──")
        code, output = run_command("free -h | grep Mem")
        if code == 0:
            lines.append(f"  {output.strip()}")
        code, pct = run_command("free | awk '/Mem:/ {printf \"%d\", $3/$2 * 100}'")
        if code == 0 and pct.strip():
            p = int(pct.strip())
            icon = "✅" if p < MEMORY_THRESHOLD_PCT else "⚠️"
            lines.append(f"  {icon} Usage: {p}% (threshold: {MEMORY_THRESHOLD_PCT}%)")
        lines.append("")

        # Active issues
        lines.append("── ACTIVE ISSUES ──")
        active = {k: v for k, v in self._issues.items() if not v.get("resolved", False)}
        if active:
            for issue_id, info in active.items():
                lines.append(f"  ⚠️ {issue_id} — retries: {info.get('retry_count', 0)}")
        else:
            lines.append("  ✅ No active issues")
        lines.append("")

        # Self-heal stats
        lines.append("── SELF-HEAL STATS ──")
        lines.append(f"  Check interval: {HEALTH_CHECK_INTERVAL}s")
        lines.append(f"  Escalation cooldown: {HEALTH_ESCALATION_COOLDOWN}s")
        lines.append(f"  Max retries per issue: {MAX_REMEDIATION_RETRIES}")
        if self._last_check:
            elapsed = time.time() - self._last_check
            lines.append(f"  Last check: {elapsed:.0f}s ago")
        else:
            lines.append(f"  Last check: not yet")
        lines.append("```")

        return "\n".join(lines)

    # -- Issue tracking ---------------------------------------------------

    def _get_retry_count(self, issue_id: str) -> int:
        """Get the current retry count for an issue."""
        if issue_id not in self._issues:
            return 0
        return self._issues[issue_id].get("retry_count", 0)

    def _increment_retry(self, issue_id: str):
        """Increment the retry count for an issue."""
        if issue_id not in self._issues:
            self._issues[issue_id] = {
                "first_seen": time.time(),
                "last_escalated": 0,
                "retry_count": 0,
                "resolved": False,
            }
        self._issues[issue_id]["retry_count"] += 1

    def _resolve_issue(self, issue_id: str):
        """Mark an issue as resolved."""
        if issue_id in self._issues:
            self._issues[issue_id]["resolved"] = True
            self._issues[issue_id]["retry_count"] = 0

    def _can_escalate(self, issue_id: str) -> bool:
        """Check if enough time has passed since the last escalation for this issue."""
        if issue_id not in self._issues:
            return True
        last = self._issues[issue_id].get("last_escalated", 0)
        return (time.time() - last) >= HEALTH_ESCALATION_COOLDOWN

    # -- Notification & Escalation ---------------------------------------

    async def _get_channel(self) -> Optional[discord.TextChannel]:
        """Get the Architect's channel for notifications."""
        try:
            return self.bot.get_channel(CHANNEL_ID)
        except Exception:
            return None

    async def _notify(self, message: str):
        """Send a non-critical notification (self-heal success) to the channel."""
        channel = await self._get_channel()
        if not channel:
            return
        try:
            embed = discord.Embed(
                title="🔧 Self-Healing",
                description=message,
                color=COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc),
            )
            await channel.send(embed=embed, silent=True)
        except Exception as e:
            log(f"Failed to send notification: {e}", "WARN")

    async def _escalate(self, issue_id: str, message: str, is_critical: bool = False):
        """Escalate an issue to the Discord channel. Respects cooldown."""
        if not self._can_escalate(issue_id):
            log(f"Escalation for {issue_id} suppressed (cooldown)", "INFO")
            return

        if issue_id not in self._issues:
            self._issues[issue_id] = {
                "first_seen": time.time(),
                "last_escalated": 0,
                "retry_count": 0,
                "resolved": False,
            }
        self._issues[issue_id]["last_escalated"] = time.time()

        channel = await self._get_channel()
        if not channel:
            log(f"Cannot escalate — channel unavailable: {message[:200]}", "ERROR")
            return

        color = COLOR_ERROR if is_critical else COLOR_WARN
        title = "🚨 Escalation — Human Attention Needed" if is_critical else "⚠️ Health Alert"

        try:
            embed = discord.Embed(
                title=title,
                description=message,
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text=f"Issue: {issue_id} | Auto-remediation exhausted")
            # Ping the admin for critical issues
            if is_critical:
                await channel.send(f"<@{ADMIN_USER_ID}>", embed=embed)
            else:
                await channel.send(embed=embed)
            log(f"Escalated issue {issue_id} to channel", "WARN")
            if metrics:
                metrics.record_escalation()
        except Exception as e:
            log(f"Failed to send escalation: {e}", "ERROR")


# ---------------------------------------------------------------------------
# Metrics Collection — track performance for self-improvement
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Collects and persists runtime metrics for the self-improvement loop."""

    def __init__(self, filepath: str = METRICS_FILE):
        self.filepath = filepath
        self.metrics: dict = {}
        self._load()

    def _load(self):
        """Load metrics from disk."""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, "r") as f:
                    self.metrics = json.load(f)
        except Exception as e:
            log(f"Metrics load error: {e}", "WARN")
            self.metrics = {}

        # Ensure structure exists
        if "totals" not in self.metrics:
            self.metrics["totals"] = {
                "llm_calls": 0,
                "llm_errors": 0,
                "tool_calls": 0,
                "tool_errors": 0,
                "agent_requests": 0,
                "heal_events": 0,
                "escalations": 0,
                "auto_updates": 0,
                "rollbacks": 0,
            }
        if "daily" not in self.metrics:
            self.metrics["daily"] = {}
        if "llm_latencies" not in self.metrics:
            self.metrics["llm_latencies"] = []
        if "tool_usage" not in self.metrics:
            self.metrics["tool_usage"] = {}
        if "errors" not in self.metrics:
            self.metrics["errors"] = []
        if "model_usage" not in self.metrics:
            self.metrics["model_usage"] = {}

    def _save(self):
        """Persist metrics to disk."""
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.metrics, f, indent=2)
        except Exception as e:
            log(f"Metrics save error: {e}", "WARN")

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _ensure_today(self):
        today = self._today()
        if today not in self.metrics["daily"]:
            self.metrics["daily"][today] = {
                "llm_calls": 0,
                "llm_errors": 0,
                "tool_calls": 0,
                "tool_errors": 0,
                "agent_requests": 0,
                "heal_events": 0,
                "auto_updates": 0,
            }

    # -- Recording methods -----------------------------------------------

    def record_llm_call(self, model: str, latency_s: float, success: bool):
        self.metrics["totals"]["llm_calls"] += 1
        self._ensure_today()
        self.metrics["daily"][self._today()]["llm_calls"] += 1
        if not success:
            self.metrics["totals"]["llm_errors"] += 1
            self.metrics["daily"][self._today()]["llm_errors"] += 1
        # Track latency (keep last 100)
        self.metrics["llm_latencies"].append({"latency": latency_s, "model": model, "ts": time.time()})
        self.metrics["llm_latencies"] = self.metrics["llm_latencies"][-100:]
        # Track model usage
        self.metrics["model_usage"][model] = self.metrics["model_usage"].get(model, 0) + 1
        self._save()

    def record_tool_call(self, tool_name: str, success: bool):
        self.metrics["totals"]["tool_calls"] += 1
        self._ensure_today()
        self.metrics["daily"][self._today()]["tool_calls"] += 1
        if not success:
            self.metrics["totals"]["tool_errors"] += 1
            self.metrics["daily"][self._today()]["tool_errors"] += 1
        self.metrics["tool_usage"][tool_name] = self.metrics["tool_usage"].get(tool_name, 0) + 1
        self._save()

    def record_agent_request(self):
        self.metrics["totals"]["agent_requests"] += 1
        self._ensure_today()
        self.metrics["daily"][self._today()]["agent_requests"] += 1
        self._save()

    def record_heal_event(self):
        self.metrics["totals"]["heal_events"] += 1
        self._ensure_today()
        self.metrics["daily"][self._today()]["heal_events"] += 1
        self._save()

    def record_escalation(self):
        self.metrics["totals"]["escalations"] += 1
        self._save()

    def record_auto_update(self, description: str, success: bool):
        self.metrics["totals"]["auto_updates"] += 1
        if not success:
            self.metrics["totals"]["rollbacks"] += 1
        self._ensure_today()
        self.metrics["daily"][self._today()]["auto_updates"] += 1
        self._save()

    def record_error(self, error_msg: str, context: str = ""):
        self.metrics["errors"].append({
            "msg": error_msg[:500],
            "context": context[:200],
            "ts": time.time(),
        })
        # Keep last 50 errors
        self.metrics["errors"] = self.metrics["errors"][-50:]
        self._save()

    # -- Reporting methods -----------------------------------------------

    def get_summary(self) -> dict:
        """Get a summary of metrics for assessment."""
        # Calculate average LLM latency
        latencies = [l["latency"] for l in self.metrics.get("llm_latencies", [])]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        # Calculate error rates
        llm_error_rate = 0
        if self.metrics["totals"]["llm_calls"] > 0:
            llm_error_rate = self.metrics["totals"]["llm_errors"] / self.metrics["totals"]["llm_calls"]

        tool_error_rate = 0
        if self.metrics["totals"]["tool_calls"] > 0:
            tool_error_rate = self.metrics["totals"]["tool_errors"] / self.metrics["totals"]["tool_calls"]

        # Get last 7 days of daily data
        daily = {}
        for date, data in sorted(self.metrics.get("daily", {}).items())[-7:]:
            daily[date] = data

        return {
            "totals": self.metrics["totals"],
            "daily_last_7d": daily,
            "avg_llm_latency_s": round(avg_latency, 2),
            "llm_error_rate": round(llm_error_rate, 3),
            "tool_error_rate": round(tool_error_rate, 3),
            "top_tools": dict(sorted(self.metrics.get("tool_usage", {}).items(), key=lambda x: -x[1])[:10]),
            "model_usage": self.metrics.get("model_usage", {}),
            "recent_errors": self.metrics.get("errors", [])[-10:],
        }

    def get_daily_update_count(self) -> int:
        """Get the number of auto-updates applied today."""
        self._ensure_today()
        return self.metrics["daily"][self._today()].get("auto_updates", 0)


# Global metrics collector
metrics: Optional[MetricsCollector] = None


# ---------------------------------------------------------------------------
# Auto-Updater — self-assessment and self-improvement
# ---------------------------------------------------------------------------
#
# The AutoUpdater runs on a regular cadence (default: every 6 hours). On each
# cycle it:
#   1. Collects metrics (LLM latency, error rates, tool usage, heal events)
#   2. Reads recent journal logs for error patterns
#   3. Sends all of this to the LLM with a structured prompt asking for
#      specific, actionable code optimizations
#   4. The LLM returns a JSON array of proposed changes, each with:
#      - description: what the change does
#      - old_code: exact string to find in the source
#      - new_code: replacement string
#      - rationale: why this improves the bot
#      - risk_level: low / medium / high
#   5. Each change is validated against protected patterns, applied to a copy,
#      syntax-checked, and if valid, written to disk
#   6. A detached shell script restarts the service and monitors it
#   7. If the service doesn't come up healthy within 30s, the script rolls back
#
# Safety mechanisms:
#   - Protected patterns: rollback logic, kill switch, AutoUpdater class, etc.
#     can never be modified
#   - Daily cap: max 3 auto-updates per day
#   - Syntax validation: AST parse before writing
#   - File size limit: never write > 200KB
#   - Backup: every change is backed up before applying
#   - Detached watchdog: survives the restart, rolls back on crash
#   - Kill switch: !autoupdate off disables the entire system
#   - Update history: all changes are logged to JSON for auditability


class AutoUpdater:
    """Self-assessment and self-improvement engine for The Architect."""

    def __init__(self, bot_client: discord.Client, metrics_collector: MetricsCollector):
        self.bot = bot_client
        self.metrics = metrics_collector
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._cycle_count = 0
        self._last_assessment: Optional[float] = None

    # -- Lifecycle --------------------------------------------------------

    async def start(self):
        if self._running:
            return
        self._running = True

        # Create golden backups for all targets on startup (never overwritten)
        for target_name, target_config in OPTIMIZATION_TARGETS.items():
            try:
                self._ensure_golden_backup(target_name, target_config)
            except Exception as e:
                log(f"Failed to create golden backup for {target_name}: {e}", "WARN")

        self._task = asyncio.create_task(self._assessment_loop())
        log("Auto-updater started — assessment every 6h (first 3 cycles every 60s to bootstrap)", "INFO")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log("Auto-updater stopped", "INFO")

    async def _assessment_loop(self):
        """Main assessment loop."""
        # Wait for initial stabilization
        await asyncio.sleep(30)

        while self._running:
            try:
                if auto_update_enabled:
                    await self._run_assessment_cycle()
                else:
                    log("Auto-update disabled — skipping assessment cycle", "INFO")
            except Exception as e:
                log(f"Auto-updater error: {e}", "ERROR")
                import traceback
                log(f"TRACEBACK: {traceback.format_exc()}", "ERROR")
                if metrics:
                    metrics.record_error(str(e), "auto_updater")

            # Determine interval: first 3 cycles run fast to bootstrap, then 6h
            self._cycle_count += 1
            interval = ASSESSMENT_INTERVAL_SHORT if self._cycle_count <= 3 else ASSESSMENT_INTERVAL
            await asyncio.sleep(interval)

    # -- Assessment -------------------------------------------------------

    async def _run_assessment_cycle(self):
        """Run one assessment cycle for ALL optimization targets."""
        self._last_assessment = time.time()
        log(f"Starting assessment cycle #{self._cycle_count + 1}", "INFO")

        # Check daily cap
        if self.metrics.get_daily_update_count() >= MAX_AUTO_UPDATES_PER_DAY:
            log(f"Daily auto-update cap reached ({MAX_AUTO_UPDATES_PER_DAY}) — skipping", "INFO")
            return

        # 1. Collect metrics
        metrics_summary = self.metrics.get_summary()
        log(f"Metrics: {metrics_summary['totals']['llm_calls']} LLM calls, "
            f"{metrics_summary['totals']['tool_calls']} tool calls, "
            f"avg latency {metrics_summary['avg_llm_latency_s']}s, "
            f"LLM error rate {metrics_summary['llm_error_rate']}", "INFO")

        # 2. Load locked sections (reversal detection)
        locked_sections = self._load_locked_sections()

        all_applied = []
        all_rejected = 0
        any_restarted = False

        # 3. Iterate over each optimization target
        for target_name, target_config in OPTIMIZATION_TARGETS.items():
            target_path = target_config["path"]
            target_service = target_config["service"]
            source_max = target_config.get("source_max_chars", 30000)

            log(f"Assessing target: {target_name} ({target_path})", "INFO")

            # Ensure golden backup exists (created once, never overwritten)
            self._ensure_golden_backup(target_name, target_config)

            # Read recent logs for this target
            _, recent_logs = run_command(
                f"sudo journalctl -u {target_service} --since '6 hours ago' --no-pager -o cat 2>&1 | tail -200",
                timeout=15,
            )

            # Read current source code
            try:
                with open(target_path, "r") as f:
                    current_source = f.read()
            except Exception as e:
                log(f"Cannot read {target_name} source: {e}", "ERROR")
                continue

            # Ask LLM for optimization recommendations
            proposals = await self._get_optimization_proposals(
                metrics_summary, recent_logs, current_source, target_name, source_max
            )

            if not proposals:
                log(f"No proposals for {target_name} this cycle", "INFO")
                continue

            log(f"LLM proposed {len(proposals)} optimization(s) for {target_name}", "INFO")

            # Validate and filter proposals
            safe_proposals = []
            for p in proposals:
                if self._validate_proposal(p, current_source, locked_sections):
                    safe_proposals.append(p)
                else:
                    all_rejected += 1
                    log(f"Rejected proposal for {target_name}: {p.get('description', '?')[:100]}", "WARN")

            if not safe_proposals:
                log(f"All proposals rejected for {target_name}", "WARN")
                continue

            # Apply changes safely
            applied = 0
            for proposal in safe_proposals[:MAX_CODE_CHANGES_PER_UPDATE]:
                success = await self._apply_change(proposal, target_name, target_config)
                if success:
                    applied += 1
                    self._record_update_history(proposal, True, target_name)
                    self.metrics.record_auto_update(proposal.get("description", "unknown"), True)
                    all_applied.append((target_name, proposal.get("description", "?")))
                    # Track for reversal detection
                    self._track_change(proposal)
                else:
                    self._record_update_history(proposal, False, target_name)
                    self.metrics.record_auto_update(proposal.get("description", "unknown"), False)

            # Restart the target with watchdog if changes were applied
            if applied > 0:
                any_restarted = True
                await self._restart_with_watchdog(target_name, target_config)

        # 4. Notify summary
        if all_applied:
            descriptions = [f"   • [{t}] {d}" for t, d in all_applied]
            await self._notify_assessment(
                f"Applied {len(all_applied)} optimization(s) across {len(set(t for t,_ in all_applied))} target(s):\n" + "\n".join(descriptions),
                metrics_summary,
            )
            # Start intensive monitoring if we restarted ourselves
            if any_restarted and any(t == "architect" for t, _ in all_applied):
                await self._start_intensive_monitor()
        elif all_rejected > 0:
            await self._notify_assessment(
                f"Generated proposals but all {all_rejected} were rejected by safety validation.",
                metrics_summary,
            )
        else:
            await self._notify_assessment("No changes needed — all systems running optimally.", metrics_summary)

    async def _get_optimization_proposals(
        self, metrics_summary: dict, logs: str, source: str,
        target_name: str = "architect", source_max_chars: int = 30000,
    ) -> list[dict]:
        """Ask the LLM to analyze metrics and propose specific code optimizations."""
        # Truncate source to keep within token limits
        source_truncated = source[:source_max_chars]

        # Target-specific context and system messages
        if target_name == "schubert":
            target_label = "Admiral Schubert's source code (schubert-bot-v2.py)"
            target_context = """
## Target Context: Admiral Schubert (schubert-bot-v2.py)

Admiral Schubert is a Discord bot with a nautical Maine Coon cat persona ("Admiral Schubert") 
who commands the Schubert server as if it were a ship. He addresses users as "Captain" and 
refers to services as "vessels" or "the fleet."

### Five-Phase Architecture:
- Phase 1: MCP client discovers tools from multiple MCP servers at runtime (github, gmail, schubert, postgres, redis, ollama)
- Phase 2: ProjectRegistry maps channels→projects; SessionManager tracks per-channel conversation history with windowing; ContextBuilder assembles LLM context (system prompt + project context + session history + memory)
- Phase 3: MemoryStore provides three-layer persistent memory (vector store in Redis, entity graph in Postgres, temporal index in Postgres)
- Phase 4: Interactive UI components (setup wizard, help embeds, progress views, file attachments)
- Phase 5: Coding assistant tools, scheduler, webhook handler, proactive sweep

### Known Pain Points to Watch For:
- MCP tool discovery failures or stale tool caches
- Session history windowing inefficiency (token budget management)
- Memory injection bloat (too many recalled memories consuming context)
- LLM context assembly overhead (ContextBuilder building large prompts)
- Voice mode constraints (responses must be concise for TTS)
- Discord rate limiting on tool call result rendering
- Project registry race conditions on channel setup
- Memory store Redis connection drops or Postgres query timeouts
- System prompt length (persona + coding prompt + voice prompt can be very long)
- Tool call error handling when MCP servers are unreachable

### Optimization Priorities for Schubert:
1. MCP resilience — graceful degradation when MCP servers are down
2. Context efficiency — reduce token waste in session history and memory injection
3. Error recovery — better fallbacks when LLM calls or tool calls fail
4. Persona preservation — ensure nautical persona doesn't break during edge cases
5. Voice mode — keep responses TTS-friendly without losing technical accuracy
6. Session management — prevent memory leaks in long-running channels
"""
            system_msg = "You are a code optimization expert specializing in Discord bots with MCP tool integration, persistent memory systems, and multi-phase architectures. You understand the Admiral Schubert nautical persona and the five-phase bot architecture. Analyze the provided metrics and source code, then return specific actionable improvements as a JSON array."
        else:
            target_label = "your own source code (The Architect bot)"
            target_context = ""
            system_msg = "You are a code optimization expert. Analyze the provided metrics and source code, then return specific actionable improvements as a JSON array."

        prompt = f"""You are analyzing {target_label} and runtime metrics to propose specific, actionable optimizations.
{target_context}

## Runtime Metrics (last 7 days)
{json.dumps(metrics_summary, indent=2)}

## Recent Logs (last 6 hours, truncated)
{logs[:5000]}

## Source Code ({target_name}, truncated to {source_max_chars} chars)
```python
{source_truncated}
```

## Task
Analyze the metrics, logs, and source code. Identify specific, concrete optimizations you can make to improve:
- Error handling and resilience
- LLM latency or efficiency
- Tool call patterns and efficiency
- Code quality and maintainability
- System prompt improvements
- Threshold tuning (timeouts, intervals, retry counts)

## Rules
1. Each change must be a simple find-and-replace (old_code → new_code)
2. old_code must be an EXACT substring from the source above
3. Keep changes small and surgical — no wholesale rewrites
4. Do NOT propose changes to protected sections: {', '.join(PROTECTED_PATTERNS)}
5. Do NOT propose changes that alter the bot's Discord token, admin ID, or MCP tokens
6. Each change must include a clear rationale
7. Focus on high-impact, low-risk changes

## Response Format
Return a JSON array of proposals. Each proposal must have:
- "description": short summary of the change
- "old_code": exact string to find in source (must be unique)
- "new_code": replacement string
- "rationale": why this improves the bot
- "risk_level": "low", "medium", or "high"

Return ONLY the JSON array, no other text."""

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

        # Use Claude for code analysis (it's a coding task)
        response = await llm_chat(messages, model=CODING_MODEL)

        if "error" in response and not response.get("choices"):
            log(f"Optimization LLM call failed: {response.get('error', '?')}", "ERROR")
            return []

        choices = response.get("choices", [])
        if not choices:
            log("No choices in optimization response", "WARN")
            return []

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            log("Empty content in optimization response", "WARN")
            return []

        # Parse JSON from response — LLM may wrap in ```json blocks
        proposals = self._parse_proposals(content)
        log(f"Parsed {len(proposals)} proposals from LLM response", "INFO")
        return proposals

    def _parse_proposals(self, content: str) -> list[dict]:
        """Parse JSON proposals from LLM response, handling markdown code blocks."""
        # Try to extract JSON from ```json ... ``` blocks
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)

        # Try direct JSON parse
        try:
            data = json.loads(content.strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try to find a JSON array in the text
        array_match = re.search(r'\[.*\]', content, re.DOTALL)
        if array_match:
            try:
                data = json.loads(array_match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        log("Could not parse proposals from LLM response", "WARN")
        return []

    # -- Validation -------------------------------------------------------

    def _validate_proposal(self, proposal: dict, source: str, locked_sections: list | None = None) -> bool:
        """Validate a proposal against safety rules."""
        old_code = proposal.get("old_code", "")
        new_code = proposal.get("new_code", "")

        if not old_code or not new_code:
            log("Proposal missing old_code or new_code", "WARN")
            return False

        if old_code == new_code:
            log("Proposal old_code == new_code (no change)", "WARN")
            return False

        # Check: old_code must exist in source
        if old_code not in source:
            log(f"Proposal old_code not found in source: {old_code[:80]}...", "WARN")
            return False

        # Check: old_code must be unique in source
        if source.count(old_code) > 1:
            log(f"Proposal old_code is not unique ({source.count(old_code)} matches): {old_code[:80]}...", "WARN")
            return False

        # Check: must not modify protected patterns
        for pattern in PROTECTED_PATTERNS:
            if pattern in old_code:
                log(f"Proposal modifies protected pattern '{pattern}'", "WARN")
                return False

        # Check: must not contain dangerous operations
        dangerous_patterns = [
            "os.system", "subprocess.call", "eval(", "exec(",
            "__import__", "os.remove", "shutil.rmtree",
            "BOT_TOKEN", "LITELLM_MASTER_KEY", "SERPER_API_KEY",
            "MCP_SCHUBERT_TOKEN", "MCP_GITHUB_TOKEN", "MCP_POSTGRES_TOKEN",
            "ARCHITECT_BOT_TOKEN", "DISCORD_TOKEN",
            "SCHUBERT_BOT_ID", "SCHUBERT_BOT_CHANNEL_ID",
        ]
        for pattern in dangerous_patterns:
            if pattern in new_code and pattern not in old_code:
                log(f"Proposal introduces dangerous pattern '{pattern}'", "WARN")
                return False

        # Check: locked sections (reversal detection)
        if locked_sections:
            for locked in locked_sections:
                locked_code = locked.get("code", "")
                if locked_code and locked_code in old_code:
                    log(f"Proposal modifies locked section (reversal detected, locked until {locked.get('unlock_time', '?')}): {old_code[:80]}...", "WARN")
                    return False

        # Check: resulting file size won't exceed limit
        new_source = source.replace(old_code, new_code)
        if len(new_source) > MAX_UPDATE_FILE_SIZE:
            log(f"Proposal would exceed file size limit ({len(new_source)} > {MAX_UPDATE_FILE_SIZE})", "WARN")
            return False

        # Check: syntax validity of the resulting code
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            log(f"Proposal produces invalid syntax: {e}", "WARN")
            return False

        # Check: pre-flight import test — try to compile the new source
        try:
            compile(new_source, "<string>", "exec")
        except Exception as e:
            log(f"Proposal fails pre-flight compile: {e}", "WARN")
            return False

        log(f"Proposal validated: {proposal.get('description', '?')[:80]}", "INFO")
        return True

    # -- Apply Changes ----------------------------------------------------

    async def _apply_change(self, proposal: dict, target_name: str = "architect", target_config: dict = None) -> bool:
        """Apply a single validated change to the source code of the specified target."""
        old_code = proposal["old_code"]
        new_code = proposal["new_code"]
        description = proposal.get("description", "unknown")
        target_path = target_config["path"] if target_config else ARCHITECT_SCRIPT_PATH
        backup_dir = target_config["backup_dir"] if target_config else UPDATE_BACKUP_DIR

        try:
            # Read current source
            with open(target_path, "r") as f:
                source = f.read()

            # Double-check old_code still exists (source may have changed)
            if old_code not in source:
                log(f"Cannot apply — old_code no longer in source: {description[:80]}", "WARN")
                return False

            # Create backup
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            os.makedirs(backup_dir, exist_ok=True)
            backup_filename = f"{'architect-bot' if target_name == 'architect' else 'schubert-bot-v2'}.py.bak.{timestamp}"
            backup_path = os.path.join(backup_dir, backup_filename)
            shutil.copy2(target_path, backup_path)
            log(f"Backed up {target_name} to {backup_path}", "INFO")

            # Apply the change
            new_source = source.replace(old_code, new_code, 1)

            # Final syntax check
            try:
                ast.parse(new_source)
            except SyntaxError as e:
                log(f"Final syntax check failed: {e}", "ERROR")
                return False

            # Final compile check
            try:
                compile(new_source, target_path, "exec")
            except Exception as e:
                log(f"Final compile check failed: {e}", "ERROR")
                return False

            # Write the new source
            with open(target_path, "w") as f:
                f.write(new_source)

            log(f"Applied change to {target_name}: {description[:100]}", "INFO")
            return True

        except Exception as e:
            log(f"Failed to apply change '{description}' to {target_name}: {e}", "ERROR")
            return False

    # -- Restart with Watchdog -------------------------------------------

    async def _restart_with_watchdog(self, target_name: str = "architect", target_config: dict = None):
        """
        Restart the target service with a detached watchdog script that:
        1. Writes a pending-update marker
        2. Restarts the service
        3. Waits for the service to come up
        4. Checks health — if unhealthy, restores the latest backup
        5. Removes the marker
        """
        service = target_config["service"] if target_config else "schubert-architect"
        target_path = target_config["path"] if target_config else ARCHITECT_SCRIPT_PATH
        backup_dir = target_config["backup_dir"] if target_config else UPDATE_BACKUP_DIR
        health_indicator = target_config.get("health_indicator", "MCP:.*tools available") if target_config else "MCP:.*tools available"
        bot_prefix = "architect-bot" if target_name == "architect" else "schubert-bot-v2"
        golden_dir = target_config.get("golden_dir", GOLDEN_BACKUP_DIR) if target_config else GOLDEN_BACKUP_DIR

        # Write pending-update marker
        with open(PENDING_UPDATE_MARKER, "w") as f:
            f.write(f"{target_name}:{datetime.now(timezone.utc).isoformat()}")

        # Find the most recent backup (for rollback)
        backup_prefix = f"{bot_prefix}.py.bak."
        try:
            backups = sorted(
                [f for f in os.listdir(backup_dir) if f.startswith(backup_prefix)],
                reverse=True,
            )
        except Exception:
            backups = []
        backup_file = backups[0] if backups else ""
        backup_path = os.path.join(backup_dir, backup_file) if backup_file else ""

        # Find golden backup (last resort)
        golden_path = os.path.join(golden_dir, f"{bot_prefix}.py.golden")
        golden_rollback_cmd = ""
        if os.path.exists(golden_path):
            golden_rollback_cmd = f"""
# Try golden backup if regular rollback also fails
sleep 10
if ! systemctl is-active --quiet {service}; then
    echo "WATCHDOG: Regular rollback failed — trying golden backup"
    cp {golden_path} {target_path}
    systemctl restart {service}
    echo "WATCHDOG: Rolled back to golden backup"
fi
"""

        if not backup_path:
            log(f"No backup found for {target_name} — cannot restart with watchdog safely", "ERROR")
            return

        # Create and launch detached watchdog script
        watchdog_script = f"""#!/bin/bash
# Auto-updater watchdog for {target_name} — survives the restart and rolls back if needed
sleep {ROLLBACK_WAIT_TIME}

if systemctl is-active --quiet {service}; then
    # Service is running — check health indicator
    TOOLS=$(journalctl -u {service} --since '{ROLLBACK_WAIT_TIME + 5} seconds ago' --no-pager -o cat 2>/dev/null | grep -c "{health_indicator}")
    if [ "$TOOLS" -gt 0 ]; then
        # Healthy — remove the pending marker
        rm -f {PENDING_UPDATE_MARKER}
        journalctl -u {service} --no-pager -o cat 2>/dev/null | tail -5
        echo "WATCHDOG: {service} is healthy after update — marker removed"
    else
        # Service is running but didn't pass health check — wait more
        echo "WATCHDOG: {service} running but health check not passed — waiting 15 more seconds"
        sleep 15
        TOOLS2=$(journalctl -u {service} --since '{ROLLBACK_WAIT_TIME + 20} seconds ago' --no-pager -o cat 2>/dev/null | grep -c "{health_indicator}")
        if [ "$TOOLS2" -gt 0 ]; then
            rm -f {PENDING_UPDATE_MARKER}
            echo "WATCHDOG: {service} recovered — marker removed"
        else
            echo "WATCHDOG: {service} unhealthy — rolling back"
            cp {backup_path} {target_path}
            systemctl restart {service}
            echo "WATCHDOG: Rolled back to {backup_file}"
            {golden_rollback_cmd}
        fi
    fi
else
    # Service is not running — rollback immediately
    echo "WATCHDOG: {service} is down — rolling back"
    cp {backup_path} {target_path}
    systemctl restart {service}
    echo "WATCHDOG: Rolled back to {backup_file}"
    {golden_rollback_cmd}
fi

# Clean up old backups (keep last 10)
ls -t {backup_dir}/{backup_prefix}* 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null
"""

        watchdog_path = f"/tmp/.{target_name}-watchdog.sh"
        with open(watchdog_path, "w") as f:
            f.write(watchdog_script)
        os.chmod(watchdog_path, 0o755)

        # Launch detached — survives the bot restart
        subprocess.Popen(
            ["bash", watchdog_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        log(f"Watchdog launched for {target_name} — will check health in {ROLLBACK_WAIT_TIME}s", "INFO")

        # Now restart the service
        run_command(f"sudo systemctl restart {service}")
        log(f"{service} restarted — watchdog monitoring", "INFO")

    # -- Pending Update Check (called on startup) -------------------------

    def check_pending_update(self) -> bool:
        """
        Check if there's a pending update marker from a previous cycle.
        If the marker exists AND the service is running, it means the
        watchdog didn't clean it up — possibly a crash before the watchdog
        could run. We should check if we're healthy and remove it, or
        rollback if we detect issues.
        """
        if not os.path.exists(PENDING_UPDATE_MARKER):
            return False

        try:
            with open(PENDING_UPDATE_MARKER, "r") as f:
                marker_time = f.read().strip()
            log(f"Pending update marker found (from {marker_time})", "WARN")
        except Exception:
            log("Pending update marker found (unreadable)", "WARN")

        # If we got here, the bot started up — check if MCP connected
        # The on_ready handler will have set mcp_client by now or will soon
        # We'll let the health monitor handle verification, but mark the
        # update as potentially problematic
        if metrics:
            metrics.record_error("Pending update marker on startup — possible incomplete update", "auto_updater")

        # Remove the marker — we're running, so the update either succeeded
        # or we need to rely on the health monitor to detect issues
        try:
            os.remove(PENDING_UPDATE_MARKER)
            log("Pending update marker removed", "INFO")
        except Exception:
            pass

        return True

    # -- History ----------------------------------------------------------

    def _record_update_history(self, proposal: dict, success: bool, target_name: str = "architect"):
        """Record an update in the history file for auditability."""
        history = []
        try:
            if os.path.exists(UPDATE_HISTORY_FILE):
                with open(UPDATE_HISTORY_FILE, "r") as f:
                    history = json.load(f)
        except Exception:
            history = []

        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target": target_name,
            "description": proposal.get("description", ""),
            "rationale": proposal.get("rationale", ""),
            "risk_level": proposal.get("risk_level", "unknown"),
            "success": success,
            "old_code_preview": proposal.get("old_code", "")[:200],
            "new_code_preview": proposal.get("new_code", "")[:200],
        })

        # Keep last 100 entries
        history = history[-100:]

        try:
            with open(UPDATE_HISTORY_FILE, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            log(f"Failed to write update history: {e}", "WARN")

    def get_history(self, limit: int = 10) -> list[dict]:
        """Get recent update history."""
        try:
            if os.path.exists(UPDATE_HISTORY_FILE):
                with open(UPDATE_HISTORY_FILE, "r") as f:
                    history = json.load(f)
                return history[-limit:]
        except Exception:
            pass
        return []

    # -- Golden Backup ----------------------------------------------------

    def _ensure_golden_backup(self, target_name: str, target_config: dict):
        """Create a golden backup if one doesn't exist. Never overwrites existing golden."""
        golden_dir = target_config.get("golden_dir", GOLDEN_BACKUP_DIR)
        target_path = target_config["path"]
        bot_prefix = "architect-bot" if target_name == "architect" else "schubert-bot-v2"
        golden_path = os.path.join(golden_dir, f"{bot_prefix}.py.golden")

        if os.path.exists(golden_path):
            return  # Golden backup already exists — never overwrite

        try:
            os.makedirs(golden_dir, exist_ok=True)
            shutil.copy2(target_path, golden_path)
            log(f"Golden backup created for {target_name}: {golden_path}", "INFO")
        except Exception as e:
            log(f"Failed to create golden backup for {target_name}: {e}", "WARN")

    def _get_golden_backup_path(self, target_name: str) -> str | None:
        """Get the golden backup path for a target, or None if it doesn't exist."""
        target_config = OPTIMIZATION_TARGETS.get(target_name)
        if not target_config:
            return None
        golden_dir = target_config.get("golden_dir", GOLDEN_BACKUP_DIR)
        bot_prefix = "architect-bot" if target_name == "architect" else "schubert-bot-v2"
        golden_path = os.path.join(golden_dir, f"{bot_prefix}.py.golden")
        return golden_path if os.path.exists(golden_path) else None

    async def rollback_to_golden(self, target_name: str = "architect") -> bool:
        """Manually rollback a target to its golden backup. Returns True on success."""
        target_config = OPTIMIZATION_TARGETS.get(target_name)
        if not target_config:
            return False
        golden_path = self._get_golden_backup_path(target_name)
        if not golden_path:
            log(f"No golden backup for {target_name}", "ERROR")
            return False

        target_path = target_config["path"]
        service = target_config["service"]
        try:
            shutil.copy2(golden_path, target_path)
            run_command(f"sudo systemctl restart {service}")
            log(f"Rolled back {target_name} to golden backup", "INFO")
            return True
        except Exception as e:
            log(f"Golden rollback failed for {target_name}: {e}", "ERROR")
            return False

    async def rollback_to_latest(self, target_name: str = "architect") -> bool:
        """Rollback a target to its most recent backup. Returns True on success."""
        target_config = OPTIMIZATION_TARGETS.get(target_name)
        if not target_config:
            return False
        backup_dir = target_config["backup_dir"]
        target_path = target_config["path"]
        service = target_config["service"]
        bot_prefix = "architect-bot" if target_name == "architect" else "schubert-bot-v2"
        backup_prefix = f"{bot_prefix}.py.bak."

        try:
            backups = sorted(
                [f for f in os.listdir(backup_dir) if f.startswith(backup_prefix)],
                reverse=True,
            )
            if not backups:
                log(f"No backups found for {target_name}", "ERROR")
                return False
            backup_path = os.path.join(backup_dir, backups[0])
            shutil.copy2(backup_path, target_path)
            run_command(f"sudo systemctl restart {service}")
            log(f"Rolled back {target_name} to {backups[0]}", "INFO")
            return True
        except Exception as e:
            log(f"Rollback failed for {target_name}: {e}", "ERROR")
            return False

    # -- Change Reversal Detection ---------------------------------------

    def _load_locked_sections(self) -> list[dict]:
        """Load locked code sections from disk. Returns list of locked section dicts."""
        try:
            if os.path.exists(LOCKED_SECTIONS_FILE):
                with open(LOCKED_SECTIONS_FILE, "r") as f:
                    locked = json.load(f)
                # Expire old locks
                now = time.time()
                active = [l for l in locked if l.get("unlock_time", 0) > now]
                if len(active) != len(locked):
                    with open(LOCKED_SECTIONS_FILE, "w") as f:
                        json.dump(active, f, indent=2)
                return active
        except Exception as e:
            log(f"Failed to load locked sections: {e}", "WARN")
        return []

    def _track_change(self, proposal: dict):
        """Track a change for reversal detection. If this change reverses a previous one, lock the section."""
        old_code = proposal.get("old_code", "")
        new_code = proposal.get("new_code", "")

        # Load existing tracked changes
        tracked = []
        track_file = "/opt/Project-Tango/scripts/.architect-tracked-changes.json"
        try:
            if os.path.exists(track_file):
                with open(track_file, "r") as f:
                    tracked = json.load(f)
        except Exception:
            tracked = []

        # Check if this new_code matches a previous old_code (reversal)
        for prev in tracked:
            if prev.get("new_code") == old_code and prev.get("old_code") == new_code:
                # Reversal detected! Lock this code section
                log(f"⚠️ Change reversal detected: '{proposal.get('description', '?')[:80]}' reverses a previous change — locking for 24h", "WARN")
                locked = self._load_locked_sections()
                locked.append({
                    "code": old_code[:200],
                    "locked_at": time.time(),
                    "unlock_time": time.time() + REVERSAL_LOCK_DURATION,
                    "reason": "reversal_detected",
                })
                try:
                    with open(LOCKED_SECTIONS_FILE, "w") as f:
                        json.dump(locked, f, indent=2)
                except Exception as e:
                    log(f"Failed to save locked sections: {e}", "WARN")
                break

        # Track this change
        tracked.append({
            "old_code": old_code[:500],
            "new_code": new_code[:500],
            "timestamp": time.time(),
            "description": proposal.get("description", ""),
        })
        tracked = tracked[-50:]  # Keep last 50
        try:
            with open(track_file, "w") as f:
                json.dump(tracked, f, indent=2)
        except Exception as e:
            log(f"Failed to save tracked changes: {e}", "WARN")

    # -- Post-Update Intensive Monitoring --------------------------------

    async def _start_intensive_monitor(self):
        """Start intensive health monitoring after an update. Checks every 10s for 5 min."""
        log("Starting post-update intensive monitoring (10s intervals for 5 min)", "INFO")
        asyncio.create_task(self._intensive_monitor_loop())

    async def _intensive_monitor_loop(self):
        """Intensive monitoring loop — catches runtime errors the watchdog misses."""
        error_count = 0
        check_interval = INTENSIVE_MONITOR_INTERVAL  # 10 seconds
        total_checks = INTENSIVE_MONITOR_DURATION // check_interval  # 30 checks over 5 min

        for i in range(total_checks):
            await asyncio.sleep(check_interval)
            try:
                # Check for errors in recent logs
                _, logs = run_command(
                    f"sudo journalctl -u schubert-architect --since '{check_interval + 2} seconds ago' --no-pager -o cat 2>&1",
                    timeout=10,
                )
                if logs:
                    # Count error indicators
                    error_indicators = ["ERROR", "Traceback", "Exception", "NameError",
                                       "AttributeError", "ImportError", "SyntaxError"]
                    for indicator in error_indicators:
                        if indicator in logs:
                            error_count += 1
                            log(f"Intensive monitor: found '{indicator}' in logs", "WARN")

                # Check if service is still active
                code, status = run_command("systemctl is-active schubert-architect")
                if status.strip() != "active":
                    error_count += 2
                    log(f"Intensive monitor: service is {status.strip()}", "ERROR")

                # If we hit the error threshold, rollback
                if error_count >= INTENSIVE_MONITOR_ERROR_THRESHOLD:
                    log(f"⚠️ Intensive monitor: {error_count} errors detected — auto-rolling back", "ERROR")
                    await self._auto_rollback()
                    await self._notify_escalation(
                        "🔴 **Auto-Rollback Triggered**\n"
                        f"   Post-update intensive monitoring detected {error_count} errors.\n"
                        f"   Automatically rolled back to latest backup.\n"
                        f"   The update may have introduced a runtime issue."
                    )
                    return

            except Exception as e:
                log(f"Intensive monitor check failed: {e}", "WARN")

        log(f"Intensive monitoring complete — {error_count} errors over {total_checks} checks", "INFO")

    async def _auto_rollback(self):
        """Automatically rollback to the latest backup and restart."""
        try:
            backup_dir = OPTIMIZATION_TARGETS["architect"]["backup_dir"]
            target_path = ARCHITECT_SCRIPT_PATH
            backup_prefix = "architect-bot.py.bak."

            backups = sorted(
                [f for f in os.listdir(backup_dir) if f.startswith(backup_prefix)],
                reverse=True,
            )
            if backups:
                backup_path = os.path.join(backup_dir, backups[0])
                shutil.copy2(backup_path, target_path)
                run_command("sudo systemctl restart schubert-architect")
                log(f"Auto-rolled back to {backups[0]}", "INFO")
                if metrics:
                    metrics.record_auto_update("auto_rollback", False)
            else:
                # Try golden backup
                golden = self._get_golden_backup_path("architect")
                if golden:
                    shutil.copy2(golden, target_path)
                    run_command("sudo systemctl restart schubert-architect")
                    log("Auto-rolled back to golden backup", "INFO")
                else:
                    log("No backups available for auto-rollback!", "ERROR")
        except Exception as e:
            log(f"Auto-rollback failed: {e}", "ERROR")

    async def _notify_escalation(self, message: str):
        """Send an escalation notification to the Discord channel."""
        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return
        try:
            embed = discord.Embed(
                title="🚨 Self-Improvement Alert",
                description=message[:1900],
                color=COLOR_ERROR,
                timestamp=datetime.now(timezone.utc),
            )
            await channel.send(f"<@{ADMIN_USER_ID}>", embed=embed)
        except Exception as e:
            log(f"Failed to send escalation: {e}", "WARN")

    # -- Notification -----------------------------------------------------

    async def _notify_assessment(self, message: str, metrics_summary: dict):
        """Send assessment results to the Discord channel."""
        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        try:
            embed = discord.Embed(
                title="🧬 Self-Improvement Assessment",
                description=message[:1900],
                color=COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="Metrics Snapshot",
                value=(
                    f"LLM calls: {metrics_summary['totals']['llm_calls']} | "
                    f"Avg latency: {metrics_summary['avg_llm_latency_s']}s\n"
                    f"Tool calls: {metrics_summary['totals']['tool_calls']} | "
                    f"Heal events: {metrics_summary['totals']['heal_events']}\n"
                    f"LLM error rate: {metrics_summary['llm_error_rate']} | "
                    f"Auto-updates: {metrics_summary['totals']['auto_updates']}"
                ),
                inline=False,
            )
            embed.set_footer(text=f"Auto-update: {'ON' if auto_update_enabled else 'OFF'} | Cycle #{self._cycle_count}")
            await channel.send(embed=embed, silent=True)
        except Exception as e:
            log(f"Failed to send assessment notification: {e}", "WARN")


# Global auto-updater
auto_updater: Optional[AutoUpdater] = None


# ---------------------------------------------------------------------------
# MCP Server Configuration
# ---------------------------------------------------------------------------

def get_mcp_configs() -> list[MCPServerConfig]:
    """Load MCP server configs from environment variables."""
    configs = []
    servers = [
        ("schubert", "http://127.0.0.1:8000/mcp", "MCP_SCHUBERT_TOKEN"),
        ("postgres", "http://127.0.0.1:8060/mcp", "MCP_POSTGRES_TOKEN"),
        ("redis", "http://127.0.0.1:8062/mcp", "MCP_REDIS_TOKEN"),
        ("ollama", "http://127.0.0.1:8063/mcp", "MCP_OLLAMA_TOKEN"),
        ("github", "http://127.0.0.1:8091", "MCP_GITHUB_TOKEN"),
        ("gmail_freelance", "http://127.0.0.1:8071/mcp", "MCP_GMAIL_TOKEN"),
        ("slack", "http://127.0.0.1:8075/mcp", "MCP_SLACK_TOKEN"),
    ]
    for name, url, token_env in servers:
        token = os.environ.get(token_env, "")
        configs.append(MCPServerConfig(name=name, url=url, bearer_token=token))
    return configs


# ---------------------------------------------------------------------------
# Discord Client
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
# members intent NOT needed — admin-only access uses user ID filtering, not member lookup

bot = discord.Client(intents=intents)
mcp_client: Optional[MCPClient] = None
health_monitor: Optional[HealthMonitor] = None
auto_updater: Optional[AutoUpdater] = None




# ---------------------------------------------------------------------------
# Multi-Agent Coordination Handlers
# ---------------------------------------------------------------------------

"""
New multi-agent aware on_message handler and support functions
"""


async def handle_multi_agent_message(message: discord.Message):
    """
    Handle a message in a multi-agent channel with coordinator logic.
    Uses response scoring and coordination locks.
    """
    global current_model
    
    if not _coordinator or not _channel_manager:
        log("Multi-agent coordinator not initialized!", "ERROR")
        return await handle_single_agent_message(message)
    
    # Register the message in coordinator
    await _coordinator.register_message(
        message_id=message.id,
        channel_id=message.channel.id,
        author_id=message.author.id,
        author_name=str(message.author),
        content=message.content,
        is_bot=message.author.bot,
        agent_name=None,  # Not from a known agent
    )
    
    # Calculate response score
    mentioned_user_ids = [u.id for u in message.mentions]
    score = calculate_response_score(
        message_content=message.content,
        agent_name="architect",
        bot_user_id=bot.user.id,
        message_author_id=message.author.id,
        admin_user_id=ADMIN_USER_ID,
        is_bot_message=message.author.bot,
        mentioned_user_ids=mentioned_user_ids,
    )
    
    log(f"Multi-agent response score for message {message.id}: {score:.2f}", "INFO")
    
    # Check if score is below threshold
    agent_profile = get_agent_profile("architect")
    if score < agent_profile.response_threshold:
        log(f"Score {score:.2f} below threshold {agent_profile.response_threshold}, not responding", "INFO")
        return
    
    # Check cooldown
    if not _coordinator.check_cooldown(message.channel.id, agent_profile.cooldown_seconds):
        log(f"Cooldown active for channel {message.channel.id}, skipping", "INFO")
        return
    
    # Determine response strategy
    if should_respond_immediately(score, "architect"):
        # High confidence - respond immediately
        log(f"High score {score:.2f}, responding immediately", "INFO")
        await _process_and_respond(message, score)
    elif should_respond_with_delay(score, "architect"):
        # Medium confidence - wait briefly to see if another agent responds
        log(f"Medium score {score:.2f}, waiting 2s before responding", "INFO")
        
        # Start typing immediately to signal intent
        async with message.channel.typing():
            await asyncio.sleep(2.0)
        
        # Check if message was answered by another agent
        if await _coordinator.is_message_answered(message.id):
            log(f"Message {message.id} was answered by another agent", "INFO")
            return
        
        # Still unanswered, proceed
        await _process_and_respond(message, score)
    else:
        log(f"Score {score:.2f} insufficient for response", "INFO")


async def _process_and_respond(message: discord.Message, score: float):
    """
    Process message and generate response with coordination lock.
    """
    if not _coordinator:
        return
    
    # Try to acquire response lock
    lock_acquired = await _coordinator.acquire_response_lock(message.id, timeout_seconds=30.0)
    
    if not lock_acquired:
        log(f"Failed to acquire lock for message {message.id}, another agent is responding", "INFO")
        return
    
    try:
        # Mark that we're responding (for cooldown tracking)
        _coordinator.mark_responded(message.channel.id)
        
        # Process the message using existing single-agent logic
        await handle_single_agent_message(message)
        
        # Mark message as answered
        await _coordinator.mark_message_answered(message.id)
        
    finally:
        # Release the lock
        await _coordinator.release_response_lock(message.id)


async def handle_single_agent_message(message: discord.Message):
    """
    Handle a message with original single-agent logic.
    This is the existing on_message processing extracted.
    """
    global current_model
    
    # Check if this is a multi-agent channel
    is_multi_agent = _channel_manager and _channel_manager.is_multi_agent_channel(message.channel.id)
    
    # Admin-only access (also allow Schubert for FLEET delegation)
    # In multi-agent channels, allow any user (coordinator already vetted the message)
    if not is_multi_agent:
        if message.author.id != ADMIN_USER_ID and message.author.id != SCHUBERT_BOT_ID and message.author.id != PROCTOR_BOT_ID:
            return

    # Only respond in the designated channels (or DMs or multi-agent channels)
    if not is_multi_agent:
        if message.channel.id not in MONITORED_CHANNEL_IDS and not isinstance(message.channel, discord.DMChannel):
            return

    # Check for bot mention or direct message
    is_mentioned = bot.user.mentioned_in(message) if bot.user else False
    is_dm = isinstance(message.channel, discord.DMChannel)

    # Command handling (! prefix)
    if message.content.startswith("!"):
        await handle_command(message)
        return

    # For natural language: respond if mentioned or in DM or in a monitored channel or in multi-agent channel
    if not is_multi_agent:
        if not (is_mentioned or is_dm or message.channel.id in MONITORED_CHANNEL_IDS):
            return

    # Fleet delegation: accept messages from Schubert or Proctor
    if message.author.bot:
        if message.author.id != SCHUBERT_BOT_ID and message.author.id != PROCTOR_BOT_ID:
            return  # Ignore all bots except Schubert and Proctor
        # Message from Proctor — treat as regular user input
        if message.author.id == PROCTOR_BOT_ID:
            user_input = message.content
            if is_mentioned:
                user_input = re.sub(rf'<@!?{bot.user.id}>', '', user_input).strip()
            if not user_input:
                return
            log(f"Request from Proctor: {user_input[:200]}", "INFO")
            _fleet_chain_id = None
            _fleet_turn = 0
            _fleet_from = None
            _fleet_to = None
        # Message from Schubert — check if it's a FLEET delegation
        elif is_fleet_message(message.content):
            parsed = parse_fleet_message(message.content)
            if parsed and parsed["to_agent"] == "architect":
                # Check chain depth (anti-loop)
                if not check_chain_depth(parsed["turn"]):
                    log(f"FLEET chain {parsed['chain_id']} exceeded max depth ({parsed['turn']})", "WARN")
                    # Send a max_depth_reached response back to Schubert
                    try:
                        schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                        if schubert_channel:
                            await schubert_channel.send(
                                format_response(
                                    chain_id=parsed["chain_id"],
                                    turn=parsed["turn"] + 1,
                                    from_agent="architect",
                                    to_agent="schubert",
                                    response="Maximum chain depth reached. Task cannot be processed further.",
                                    status="max_depth_reached",
                                )
                            )
                    except Exception as e:
                        log(f"Error sending max_depth response: {e}", "WARN")
                    return

                # Track the chain for anti-loop
                if not track_chain(parsed["chain_id"], parsed["from_agent"], "architect", parsed["turn"]):
                    log(f"Loop detected for chain {parsed['chain_id']}", "WARN")
                    return

                # Process the delegated task
                user_input = parsed["task"]
                log(f"FLEET delegation from Schubert (chain={parsed['chain_id']}, turn={parsed['turn']}): {user_input[:200]}", "INFO")

                # Store the chain info for the response
                _fleet_chain_id = parsed["chain_id"]
                _fleet_turn = parsed["turn"]
                _fleet_from = "architect"
                _fleet_to = "schubert"
            else:
                # FLEET message not for us — ignore
                return
        else:
            # Non-FLEET message from Schubert — ignore (only accept tagged delegations)
            return
    else:
        # Regular user message — process normally
        user_input = message.content
        # Remove bot mention from input
        if is_mentioned:
            user_input = re.sub(rf'<@!?{bot.user.id}>', '', user_input).strip()

        if not user_input:
            return

        log(f"Request from {message.author.name}: {user_input[:200]}", "INFO")
        _fleet_chain_id = None
        _fleet_turn = 0
        _fleet_from = None
        _fleet_to = None
    
    if metrics:
        metrics.record_agent_request()

    _last_inputs[message.channel.id] = user_input

    # Thread isolation — decide whether to create a dedicated thread
    use_thread = should_use_thread(user_input)
    response_channel = message.channel
    
    if use_thread and not _fleet_chain_id:  # Only create threads for non-FLEET requests
        thread_name = f"🔧 Task: {user_input[:80]}{'...' if len(user_input) > 80 else ''}"
        try:
            thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,  # 24 hours
            )
            response_channel = thread
            
            # Notify in main channel (silent)
            await message.reply(
                f"📋 Started a thread for this task: {thread.jump_url}",
                silent=True,
            )
            log(f"Created thread for task: {thread_name}", "INFO")
        except Exception as e:
            log(f"Failed to create thread, using main channel: {e}", "WARN")
            response_channel = message.channel

    # Start progress view in the response channel
    progress = AgentProgressView(message if not use_thread else thread)
    if _fleet_chain_id:
        progress._is_fleet_request = True
    await progress.start(f"Working on: {user_input[:200]}")

    agent_task = asyncio.create_task(
        run_agent_loop(message, user_input, mcp_client, progress,
                        fleet_chain_id=_fleet_chain_id,
                        fleet_turn=_fleet_turn,
                        fleet_from=_fleet_from,
                        fleet_to=_fleet_to)
    )
    _running_tasks[message.channel.id] = agent_task

    try:
        response = await agent_task
        await progress.finalize(response)
    except asyncio.CancelledError:
        log(f"Agent task cancelled for channel {message.channel.id}", "INFO")
        await progress.finalize("⏹️ Task cancelled.")
    except Exception as e:
        log(f"Agent error: {e}", "ERROR")
        import traceback
        log(f"TRACEBACK: {traceback.format_exc()}", "ERROR")
        await progress.finalize(f"❌ Error: {str(e)[:500]}")
    finally:
        _running_tasks.pop(message.channel.id, None)


# ---------------------------------------------------------------------------
# Bot Event Handlers
# ---------------------------------------------------------------------------

async def _heartbeat_loop():
    """
    Background task that sends heartbeats to coordinator every 30s.
    Indicates this agent is online and available for multi-agent coordination.
    """
    while True:
        try:
            await asyncio.sleep(30)
            if _coordinator:
                await _coordinator.heartbeat()
                log("Multi-agent heartbeat sent", "DEBUG")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log(f"Heartbeat error: {e}", "WARN")


# Feedback Summary View for kickstart-demo channel
class SendFeedbackButtonView(ui.View):
    """Button view for sending Writer Event Feedback Summary to Slack."""
    
    def __init__(self, mcp_client_ref):
        super().__init__(timeout=None)  # Button stays active indefinitely
        self.mcp = mcp_client_ref
    
    @ui.button(
        label="📊 Send Writer Feedback Summary to Slack #demo-cape-webinars",
        style=discord.ButtonStyle.primary,
        custom_id="architect_send_feedback_slack"
    )
    async def send_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            from send_feedback_slack import FEEDBACK_MESSAGE, SLACK_CHANNEL_ID
            
            if not self.mcp:
                await interaction.followup.send("❌ MCP client not available", ephemeral=True)
                return
            
            # Debug logging
            log(f"Sending to Slack - Channel: {SLACK_CHANNEL_ID}, Message length: {len(FEEDBACK_MESSAGE)}", "INFO")
            
            result = await self.mcp.call_tool("slack__slack_post_message", {
                "channel_id": SLACK_CHANNEL_ID,
                "text": FEEDBACK_MESSAGE
            })
            
            await interaction.followup.send(
                f"✅ Writer Event Feedback Summary sent to Slack **#demo-cape-webinars**!\n\nResponse: {str(result)[:200]}",
                ephemeral=True
            )
            log(f"Feedback summary sent via button click by {interaction.user.name}", "INFO")
            
        except Exception as e:
            log(f"Button click error: {e}", "ERROR")
            await interaction.followup.send(f"❌ Failed to send to Slack: {str(e)}", ephemeral=True)


async def post_kickstart_button(force_refresh=False):
    """Post persistent button in kickstart-demo channel if needed.
    
    Args:
        force_refresh: If True, delete old button and post a new one
    """
    try:
        channel = bot.get_channel(KICKSTART_DEMO_CHANNEL_ID)
        if not channel:
            log(f"Could not find kickstart-demo channel {KICKSTART_DEMO_CHANNEL_ID}", "WARN")
            return
        
        # Check if button message already exists
        existing_message = None
        async for message in channel.history(limit=20):
            if message.author.id == bot.user.id and message.embeds:
                if "Writer Event Feedback Summary" in (message.embeds[0].title or ""):
                    existing_message = message
                    break
        
        if existing_message:
            if force_refresh:
                await existing_message.delete()
                log("Deleted old kickstart demo button for refresh", "INFO")
            else:
                log("Kickstart demo button already exists", "INFO")
                return
        
        # Post new button message
        view = SendFeedbackButtonView(mcp_client)
        
        embed = discord.Embed(
            title="📊 Writer Event Feedback Summary → Slack",
            description=(
                "Click the button below to send the comprehensive Writer Event "
                "Feedback Summary to Slack **#demo-cape-webinars**.\n\n"
                "This will post the full report with all metrics, insights, and action items.\n\n"
                "**Alternative command:** `!send-feedback`"
            ),
            color=COLOR_ARCHITECT,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Click to send anytime • Managed by The Architect")
        
        await channel.send(embed=embed, view=view)
        log("Posted feedback button in kickstart-demo channel", "INFO")
        
    except Exception as e:
        log(f"Failed to post kickstart button: {e}", "WARN")


@bot.event
async def on_ready():
    global mcp_client, health_monitor, metrics, auto_updater, _channel_manager, _coordinator
    log(f"The Architect is online as {bot.user} (ID: {bot.user.id})", "INFO")
    global _multi_agent_manager
    _multi_agent_manager = MultiAgentManager(agent_name="architect")
    log(f"Admin: {ADMIN_USER_ID} | Channel: {CHANNEL_ID}", "INFO")
    log(f"Model: {current_model} via {LITELLM_URL}", "INFO")

    # Initialize persistent memory store
    global memory_store
    try:
        memory_store = MemoryStore()
        memory_store.init_db()
        log("Persistent memory store initialized (Redis + PostgreSQL)", "INFO")
    except Exception as e:
        log(f"Failed to initialize memory store: {e}", "WARN")
        memory_store = None
    
    # Channel onboarding
    try:
        await onboard_channel(bot, CHANNEL_ID, ARCHITECT_CHANNEL_CONFIG, replace_existing=True)
        log("Channel onboarding complete", "INFO")
    except Exception as e:
        log(f"Channel onboarding failed: {e}", "WARN")

    # Initialize multi-agent coordinator
    try:
        # TODO: Get database connection string from environment
        db_conn_string = os.environ.get("DATABASE_URL")
        _channel_manager = MultiAgentChannelManager(db_conn_string)
        
        # TODO: Get Redis client from memory_store if available
        redis_client = None
        if memory_store and hasattr(memory_store, 'redis_client'):
            redis_client = memory_store.redis_client
        
        _coordinator = ConversationCoordinator(redis_client, "architect")
        
        # Register multi-agent channels from environment
        senior_staff_channel = os.environ.get("SENIOR_STAFF_CHANNEL_ID")
        if senior_staff_channel:
            channel_id = int(senior_staff_channel)
            _channel_manager.register_channel(
                channel_id,
                agents=["admiral", "architect", "quartermaster", "cartographer"]
            )
            # Also register in multi_agent_config
            register_channel(
                channel_id=channel_id,
                enabled_agents=["admiral", "architect", "quartermaster", "cartographer"],
                coordinator="admiral",
                require_mention=False,
            )
            log(f"Registered multi-agent channel: {channel_id}", "INFO")
        
        log("Multi-agent coordinator initialized", "INFO")
    except Exception as e:
        log(f"Failed to initialize multi-agent coordinator: {e}", "WARN")
        _channel_manager = None
        _coordinator = None
    
    # Start heartbeat loop for multi-agent coordinator
    if _coordinator:
        asyncio.create_task(_heartbeat_loop())

    # Initialize metrics collector
    try:
        metrics = MetricsCollector()
        log("Metrics collector initialized", "INFO")
    except Exception as e:
        log(f"Failed to initialize metrics: {e}", "ERROR")
        metrics = None

    # Check for pending update from a previous restart
    if metrics:
        try:
            au = AutoUpdater.__new__(AutoUpdater)  # temporary instance for check
            au.metrics = metrics
            if au.check_pending_update():
                log("Pending update detected — monitoring health closely", "WARN")
        except Exception as e:
            log(f"Pending update check failed: {e}", "WARN")

    # Connect to MCP servers
    try:
        mcp_client = MCPClient(get_mcp_configs())
        await mcp_client.connect_all()
        tools = mcp_client.get_aggregated_tools()
        log(f"MCP: {len(tools)} tools available", "INFO")
    except Exception as e:
        log(f"MCP connection error: {e}", "WARN")
        mcp_client = None
    
    # Register persistent button view for Discord to handle clicks
    # (must be done after mcp_client is initialized)
    try:
        bot.add_view(SendFeedbackButtonView(mcp_client))
        log("Registered persistent button view for feedback summary", "INFO")
    except Exception as e:
        log(f"Failed to register button view: {e}", "WARN")

    # Post persistent button in kickstart-demo channel (after MCP is ready)
    # Force refresh on first startup to ensure MCP client is properly connected
    try:
        await post_kickstart_button(force_refresh=False)
    except Exception as e:
        log(f"Failed to post kickstart button: {e}", "WARN")

    # Start the proactive self-healing health monitor
    try:
        health_monitor = HealthMonitor(bot, mcp_client)
        await health_monitor.start()
    except Exception as e:
        log(f"Failed to start health monitor: {e}", "ERROR")

    # Start the self-improvement auto-updater
    try:
        auto_updater = AutoUpdater(bot, metrics)
        if auto_update_enabled:
            await auto_updater.start()
        else:
            log("Auto-update disabled — skipping auto-updater start", "INFO")
    except Exception as e:
        log(f"Failed to start auto-updater: {e}", "ERROR")

    # Send startup message to channel
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="🏗️ The Architect is online",
                description=(
                    f"**Model:** `{current_model}` (auto-routing ON)\n"
                    f"   • Default: `{DEFAULT_MODEL}` for general tasks\n"
                    f"   • Coding: `{CODING_MODEL}` (auto-switches on code-related requests)\n"
                    f"**MCP tools:** {len(mcp_client.get_aggregated_tools()) if mcp_client else 0}\n"
                    f"**Dev tools:** 8 (read_code, search_code, deploy_file, restart_service, view_logs, run_test, service_status, web_search)\n"
                    f"**Self-healing:** ✅ Active — monitoring all services, MCP, LLM, disk, and memory every 60s\n"
                    f"**Self-improvement:** {'✅ Active' if auto_update_enabled else '🔴 Disabled'} — assessing and optimizing every 6h\n\n"
                    f"Type naturally or use `!model` to switch LLMs.\n"
                    f"Use `!model auto` to restore auto-routing after a manual switch.\n"
                    f"Use `!health` for an on-demand health report.\n"
                    f"Use `!autoupdate` to manage self-improvement.\n"
                    f"Admin-only: responds to <@{ADMIN_USER_ID}>"
                ),
                color=COLOR_ARCHITECT,
                timestamp=datetime.now(timezone.utc),
            )
            await channel.send(embed=embed)
    except Exception as e:
        log(f"Could not send startup message: {e}", "WARN")


@bot.event
async def on_message(message: discord.Message):
    """Route message to appropriate handler based on channel type."""
    global current_model

    # Ignore own messages - but register them in multi-agent channels for context
    if message.author.id == bot.user.id:
        if _channel_manager and _channel_manager.is_multi_agent_channel(message.channel.id):
            # Register own message for multi-agent context
            if _coordinator:
                await _coordinator.register_message(
                    message_id=message.id,
                    channel_id=message.channel.id,
                    author_id=message.author.id,
                    author_name="Architect",
                    content=message.content,
                    is_bot=True,
                    agent_name="architect",
                )
        return  # Don't respond to own messages
    
    # Check if this is a reply to a WRITER playbook result (for follow-ups)
    if message.reference and message.reference.message_id in _playbook_threads:
        thread_id = _playbook_threads[message.reference.message_id]
        log(f"Detected reply to WRITER playbook thread: {thread_id}", "INFO")
        
        # Import here to avoid circular dependency
        from writer_integration import invoke_playbook_from_discord
        
        # Continue the WRITER conversation with the user's follow-up
        try:
            await invoke_playbook_from_discord(
                playbook_name="cursor-litellm",  # Use the same playbook
                discord_channel=message.channel,
                user_message=message.content,
                progress_updates=True,
                thread_tracker=_playbook_threads,
                continue_thread_id=thread_id
            )
            return  # Message handled
        except Exception as e:
            log(f"Follow-up handling error: {e}", "ERROR")
            await message.reply(f"❌ Failed to continue conversation: {str(e)}")
            return
    
    # WRITER Playbook Auto-Detection (runs first, before other handlers)
    try:
        playbook_handled = await handle_architect_message(message, _playbook_threads)
        if playbook_handled:
            log(f"Message handled by WRITER playbook auto-detection", "INFO")
            return  # Message was handled by playbook invocation
    except Exception as e:
        log(f"WRITER playbook auto-detection error: {e}", "ERROR")
        # Continue to normal message handling if playbook invocation fails
    
    # Check if this is a multi-agent channel
    if _channel_manager and _channel_manager.is_multi_agent_channel(message.channel.id):
        await handle_multi_agent_message(message)
    else:
        await handle_single_agent_message(message)

async def handle_command(message: discord.Message):
    """Handle ! prefix commands."""
    global current_model

    parts = message.content[1:].split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "model" or cmd == "models":
        if args:
            stripped = args.strip()

            # Re-enable auto model routing
            if stripped.lower() == "auto":
                user_model_override = False
                current_model = DEFAULT_MODEL
                log("Auto model routing re-enabled — Palmyra x6 (default) / Claude Sonnet 4.5 (coding)", "INFO")
                await message.reply(
                    f"✅ Auto-routing re-enabled.\n"
                    f"   • **Default:** `{DEFAULT_MODEL}` (general tasks)\n"
                    f"   • **Coding:** `{CODING_MODEL}` (auto-switches on code-related requests)\n\n"
                    f"Manual `!model` selections are overridden until you use `!model auto` again."
                )
                return

            # Direct model switch
            new_model = stripped
            # Validate against available models
            all_models = []
            for models in MODEL_CATEGORIES.values():
                all_models.extend(models)
            if new_model in all_models:
                old_model = current_model
                current_model = new_model
                user_model_override = True  # Manual selection disables auto-switching
                log(f"Model switched from {old_model} to {current_model} (manual override, auto-routing OFF)", "INFO")
                await message.reply(
                    f"✅ Model switched: `{old_model}` → `{current_model}`\n"
                    f"⚠️ Auto-routing is now OFF. Use `!model auto` to re-enable."
                )
            else:
                await message.reply(f"❌ Unknown model: `{new_model}`\nUse `!model` to see available models, or `!model auto` for auto-routing.")
        else:
            # Show model selection UI
            await handle_model_command(message)

    elif cmd == "send-feedback":
        # Direct command to send Writer Event Feedback Summary to Slack
        # Bypasses LLM - direct execution
        if message.channel.id != KICKSTART_DEMO_CHANNEL_ID:
            await message.reply("❌ This command only works in the kickstart-demo channel.")
            return
        
        try:
            from send_feedback_slack import FEEDBACK_MESSAGE, SLACK_CHANNEL_ID
            
            if not mcp_client:
                await message.reply("❌ MCP client not available")
                return
            
            await message.reply("📤 Sending Writer Event Feedback Summary to Slack #demo-cape-webinars...")
            
            result = await mcp_client.call_tool("slack__slack_post_message", {
                "channel": SLACK_CHANNEL_ID,
                "text": FEEDBACK_MESSAGE
            })
            
            await message.reply(f"✅ Writer Event Feedback Summary sent to Slack #demo-cape-webinars!\n\nResponse: {str(result)[:500]}")
            log(f"Feedback summary sent to Slack by {message.author.name}", "INFO")
            
        except Exception as e:
            log(f"Failed to send feedback to Slack: {e}", "ERROR")
            await message.reply(f"❌ Failed to send to Slack: {str(e)}")
        return

    elif cmd == "status":
        status = await execute_dev_tool("service_status", {})
        embed = discord.Embed(
            title="🏗️ Server Status",
            description=f"```\n{status}\n```",
            color=COLOR_ARCHITECT,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Model: {current_model}")
        await message.reply(embed=embed)

    elif cmd == "health":
        if health_monitor:
            report = await health_monitor.run_full_check()
            # The report can be long — send as embed if > 1900 chars
            if len(report) <= 1900:
                await message.reply(report)
            else:
                embed = discord.Embed(
                    title="🏗️ Health Report",
                    description=report[:4096],
                    color=COLOR_SUCCESS,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text=f"Model: {current_model} | Auto-healing: {'ON' if health_monitor._running else 'OFF'}")
                await message.reply(embed=embed)
        else:
            await message.reply("⚠️ Health monitor not initialized.")

    elif cmd == "memory":
        if not memory_store:
            await message.reply("Memory system not initialized.")
            return
        if not args:
            stats = memory_store.get_stats()
            embed = discord.Embed(
                title="Architect Memory",
                color=COLOR_ARCHITECT,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Total Memories", value=str(stats.get("total_memories", 0)), inline=True)
            embed.add_field(name="Entities", value=str(stats.get("total_entities", 0)), inline=True)
            embed.add_field(name="Facts", value=str(stats.get("total_facts", 0)), inline=True)
            embed.add_field(name="Events", value=str(stats.get("total_events", 0)), inline=True)
            embed.set_footer(text="Use !memory search <query> | !memory entity <name> | !memory recent | !memory clear")
            await message.reply(embed=embed)
        elif args.startswith("search"):
            query = args[6:].strip()
            if query:
                result = handle_query_memory({"type": "search", "query": query})
                await message.reply(result[:1900])
        elif args.startswith("entity"):
            name = args[6:].strip()
            if name:
                result = handle_query_memory({"type": "entity", "name": name})
                await message.reply(result[:1900])
        elif args.startswith("recent"):
            result = handle_query_memory({"type": "recent"})
            await message.reply(result[:1900])
        elif args.startswith("clear"):
            clear_session_history(message.channel.id)
            await message.reply("Session history cleared (persistent memories are retained).")
        elif args.startswith("stats"):
            result = handle_query_memory({"type": "stats"})
            await message.reply(result[:1900])
        else:
            await message.reply("Usage: !memory [search <query> | entity <name> | recent | stats | clear]")
        return

    elif cmd == "help":
        embed = discord.Embed(
            title="🏗️ The Architect — Command Reference",
            description=(
                "I'm your development and administration assistant for the Schubert Bot ecosystem. "
                "Type naturally or use commands below."
            ),
            color=COLOR_ARCHITECT,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="📋 Commands",
            value=(
                "`!model` — Switch LLM model (shows dropdown)\n"
                "`!model <name>` — Switch to a specific model (disables auto-routing)\n"
                "`!model auto` — Re-enable auto-routing (Palmyra x6 → Claude for coding)\n"
                "`!status` — Check all service statuses\n"
                "`!health` — Full health report (services, MCP, LLM, disk, memory)\n"
                "`!autoupdate` — Self-improvement status\n"
                "`!autoupdate on/off` — Enable/disable self-updates\n"
                "`!autoupdate now` — Run assessment immediately\n"
                "`!autoupdate history` — View recent self-modifications\n"
                "`!logs [service]` — View recent service logs\n"
                "`!help` — Show this help"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔧 Self-Healing",
            value=(
                "The Architect proactively monitors all systems every 60s and\n"
                "auto-remediates issues (restarts services, reconnects MCP,\n"
                "cleans disk). Only escalates to you when auto-fixes are exhausted."
            ),
            inline=False,
        )
        embed.add_field(
            name="🧬 Self-Improvement",
            value=(
                "The Architect assesses its own performance AND Admiral Schubert's\n"
                "every 6 hours and applies code optimizations to both bots. All\n"
                "changes are backed up, syntax-validated, and automatically rolled\n"
                "back if the bot fails to restart healthy. Golden backups provide a\n"
                "last-resort restore point. Kill switch: `!autoupdate off`."
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️ Safety Commands",
            value=(
                "`!rollback architect` — Roll back Architect to latest backup\n"
                "`!rollback schubert` — Roll back Admiral Schubert to latest backup\n"
                "`!rollback architect golden` — Roll back to golden (known-good) backup"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛠️ Dev Tools (natural language)",
            value=(
                "Read code, search code, deploy files, restart services,\n"
                "view logs, run tests, check status, search the web"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧠 Available Models",
            value="\n".join(f"`{m}`" for m in MODEL_CATEGORIES["Writer (Palmyra)"][:3] + MODEL_CATEGORIES["Claude"][:3]),
            inline=False,
        )
        embed.set_footer(text=f"Current model: {current_model} | Admin-only")
        await message.reply(embed=embed)

    elif cmd == "logs":
        service = args.strip() or "schubert-bot.service"
        result = await execute_dev_tool("view_logs", {"service": service, "lines": 30})
        embed = discord.Embed(
            title=f"📋 Logs: {service}",
            description=f"```\n{result[:4000]}\n```",
            color=COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        await message.reply(embed=embed)
    
    elif cmd == "refresh-button":
        try:
            await post_kickstart_button(force_refresh=True)
            await message.reply("✅ Refreshed kickstart-demo button with updated MCP client connection")
        except Exception as e:
            await message.reply(f"❌ Failed to refresh button: {e}")

    elif cmd == "autoupdate":
        global auto_update_enabled, auto_updater
        subcmd = args.strip().lower() if args else ""

        if subcmd == "off":
            auto_update_enabled = False
            if auto_updater:
                await auto_updater.stop()
            log("Auto-update DISABLED by user (kill switch)", "WARN")
            await message.reply(
                "🔴 **Auto-update DISABLED**\n"
                "The self-improvement system is now off. The Architect will stop\n"
                "assessing and modifying its own code.\n"
                "Use `!autoupdate on` to re-enable."
            )

        elif subcmd == "on":
            auto_update_enabled = True
            if auto_updater and not auto_updater._running:
                await auto_updater.start()
            log("Auto-update ENABLED by user", "INFO")
            await message.reply(
                "🟢 **Auto-update ENABLED**\n"
                "The self-improvement system is now active. The Architect will\n"
                "assess and optimize itself every 6 hours.\n"
                "Use `!autoupdate off` to disable at any time."
            )

        elif subcmd == "now":
            if not auto_update_enabled:
                await message.reply("⚠️ Auto-update is OFF. Use `!autoupdate on` first, then `!autoupdate now`.")
                return
            if auto_updater:
                await message.reply("🧬 Running an immediate assessment cycle...")
                asyncio.create_task(auto_updater._run_assessment_cycle())
            else:
                await message.reply("⚠️ Auto-updater not initialized.")

        elif subcmd == "history":
            if auto_updater:
                history = auto_updater.get_history(limit=10)
                if not history:
                    await message.reply("No auto-updates have been applied yet.")
                else:
                    lines = ["```", "🧬 AUTO-UPDATE HISTORY", ""]
                    for entry in history:
                        ts = entry.get("timestamp", "?")[:19]
                        status = "✅" if entry.get("success") else "❌"
                        desc = entry.get("description", "?")[:80]
                        risk = entry.get("risk_level", "?")
                        lines.append(f"  {status} [{ts}] ({risk}) {desc}")
                    lines.append("```")
                    await message.reply("\n".join(lines))
            else:
                await message.reply("⚠️ Auto-updater not initialized.")

        elif subcmd == "targets":
            lines = ["```", "🧬 OPTIMIZATION TARGETS", ""]
            for name, config in OPTIMIZATION_TARGETS.items():
                path = config["path"]
                svc = config["service"]
                # Check if golden backup exists
                bot_prefix = "architect-bot" if name == "architect" else "schubert-bot-v2"
                golden = os.path.join(config.get("golden_dir", ""), f"{bot_prefix}.py.golden")
                golden_status = "✅" if os.path.exists(golden) else "❌"
                lines.append(f"  {name}:")
                lines.append(f"    path: {path}")
                lines.append(f"    service: {svc}")
                lines.append(f"    golden backup: {golden_status}")
            lines.append("```")
            await message.reply("\n".join(lines))

        else:
            # Show status
            status_line = "🟢 ON" if auto_update_enabled else "🔴 OFF"
            embed = discord.Embed(
                title="🧬 Auto-Update Status",
                description=(
                    f"**Status:** {status_line}\n"
                    f"**Targets:** {', '.join(OPTIMIZATION_TARGETS.keys())}\n"
                    f"**Cadence:** Every 6 hours (first 3 cycles every 60s)\n"
                    f"**Daily cap:** {MAX_AUTO_UPDATES_PER_DAY} updates/day per target\n"
                    f"**Max changes per update:** {MAX_CODE_CHANGES_PER_UPDATE}\n"
                    f"**Rollback wait:** {ROLLBACK_WAIT_TIME}s\n"
                    f"**Intensive monitor:** {INTENSIVE_MONITOR_DURATION}s after update (every {INTENSIVE_MONITOR_INTERVAL}s)\n\n"
                    f"**Commands:**\n"
                    f"`!autoupdate on` — Enable self-improvement\n"
                    f"`!autoupdate off` — Disable (kill switch)\n"
                    f"`!autoupdate now` — Run assessment immediately\n"
                    f"`!autoupdate history` — View recent changes\n"
                    f"`!autoupdate targets` — View optimization targets\n"
                    f"`!rollback <target> [golden]` — Emergency rollback\n"
                    f"`!autoupdate status` — Show this status"
                ),
                color=COLOR_SUCCESS if auto_update_enabled else COLOR_ERROR,
                timestamp=datetime.now(timezone.utc),
            )
            if auto_updater and auto_updater._last_assessment:
                elapsed = time.time() - auto_updater._last_assessment
                embed.add_field(
                    name="Last Assessment",
                    value=f"{elapsed:.0f}s ago (cycle #{auto_updater._cycle_count})",
                    inline=True,
                )
            if metrics:
                summary = metrics.get_summary()
                embed.add_field(
                    name="Today's Updates",
                    value=f"{metrics.get_daily_update_count()}/{MAX_AUTO_UPDATES_PER_DAY}",
                    inline=True,
                )
            await message.reply(embed=embed)

    elif cmd == "rollback":
        target = args.strip().lower() if args else "architect"
        use_golden = "golden" in target
        target_name = target.replace("golden", "").strip() or "architect"

        if target_name not in OPTIMIZATION_TARGETS:
            await message.reply(f"❌ Unknown target: `{target_name}`. Available: {', '.join(OPTIMIZATION_TARGETS.keys())}")
            return

        if not auto_updater:
            await message.reply("⚠️ Auto-updater not initialized.")
            return

        if use_golden:
            await message.reply(f"🔄 Rolling back {target_name} to golden backup...")
            success = await auto_updater.rollback_to_golden(target_name)
        else:
            await message.reply(f"🔄 Rolling back {target_name} to latest backup...")
            success = await auto_updater.rollback_to_latest(target_name)

        if success:
            await message.reply(f"✅ {target_name} rolled back successfully. Service restarting.")
        else:
            await message.reply(f"❌ Rollback failed for {target_name}. Check logs.")

    else:
        await message.reply(f"Unknown command: `!{cmd}`. Try `!help`.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        print("ERROR: ARCHITECT_BOT_TOKEN not set in environment")
        sys.exit(1)

    log("=" * 60, "INFO")
    log("The Architect — Schubert Control & Development Bot", "INFO")
    log(f"Channel ID: {CHANNEL_ID}", "INFO")
    log(f"Admin User ID: {ADMIN_USER_ID}", "INFO")
    log(f"LLM Model: {current_model} via {LITELLM_URL}", "INFO")
    log(f"Serper API: {'configured' if SERPER_API_KEY else 'NOT configured'}", "INFO")
    log("=" * 60, "INFO")

    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
