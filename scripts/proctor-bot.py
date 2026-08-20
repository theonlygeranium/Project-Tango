#!/usr/bin/env python3
"""
The Proctor — Schubert Control & Development Bot
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
from datetime import datetime, timezone, timedelta
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
    create_delegation_message,
)
from channel_onboarding import onboard_channel
from proctor_test_framework import (
    initialize_test_framework, ProctorTestRunner, TestPriority
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
    _cfg = get_bot_config("proctor")
except Exception:
    _cfg = {}

_llm = _cfg.get("llm", {}) if isinstance(_cfg.get("llm", {}), dict) else {}

# Proctor observer module
from proctor_observer import (
    PerformanceTracker, HUMAN_OPERATOR_ID, AGENT_BOT_IDS, AGENT_CHANNEL_IDS,
    DELEGATION_CHANNEL_ID, ANALYSIS_CHANNEL_ID,
)

# Slack integration
from slack_notifier import get_slack_notifier

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("PROCTOR_BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("PROCTOR_CHANNEL_ID", "0"))
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

# Performance tracker for silent observation
_performance_tracker: Optional[PerformanceTracker] = None

# Test framework instance
_test_runner: Optional[ProctorTestRunner] = None

# Session history (in-memory, per-channel, with windowing)
SESSION_HISTORY: dict[int, list[dict]] = {}
SESSION_MAX_MESSAGES = _llm.get("session_window", 35)

# Multi-LLM routing — default model and available models
# The Proctor auto-switches: Palmyra x6 for general tasks, Claude Sonnet 4.5 for coding
DEFAULT_MODEL = _llm.get("model", "writer/palmyra-x6")
CODING_MODEL = _llm.get("coding_model", "writer/claude-sonnet-4-5")
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
LLM_TIMEOUT = _llm.get("llm_timeout", 180)
MAX_ITERATIONS = _llm.get("max_iterations", 30)
AGENT_TIMEOUT = _llm.get("agent_timeout", 480)

# Colors
COLOR_INFO = 0x5865F2
COLOR_SUCCESS = 0x57F287
COLOR_WARN = 0xFEE75C
COLOR_ERROR = 0xED4245
COLOR_ARCHITECT = 0xFF9500  # purple

# Channel onboarding config
PROCTOR_CHANNEL_CONFIG = {
    "topic": "The Proctor's Observatory — Monitoring & Observability Specialist for metrics, alerting, and system health",
    "bot_name": "The Proctor",
    "role": "Monitoring & Observability Specialist",
    "description": (
        "A vigilant monitoring and observability specialist who watches over the entire fleet with unflinching attention. "
        "Specializes in metrics collection, alerting, log analysis, performance monitoring, incident detection, and system health validation. "
        "Never sleeps, always watching, always ready to raise the alarm when something goes wrong."
    ),
    "commands": [
        {"name": "!status", "description": "Check bot status"},
        {"name": "Natural language", "description": "Send requests naturally for monitoring and observability tasks"},
    ],
    "tips": [
        "Specializes in metrics, alerting, log analysis, and performance monitoring",
        "Receives delegated tasks from Admiral Schubert via the FLEET protocol",
        "Has full access to MCP tools: Schubert Nexus, PostgreSQL, Redis, Ollama",
        "Can analyze logs, track metrics, and detect anomalies",
        "Integrates with Proctor Observer framework for automated monitoring",
        "Works closely with Admiral Schubert and The Quartermaster for incident response",
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
logger = logging.getLogger("proctor-bot")

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
        log("LLM call timed out", "ERROR")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        return {"error": "LLM call timed out", "choices": []}
    except aiohttp.ClientError as e:
        log(f"LLM network error (retryable): {e}", "WARN")
        if metrics:
            metrics.record_llm_call(use_model, time.time() - call_start, False)
        return {"error": f"Network error: {e}", "choices": [], "retryable": True}
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
                timeout=aiohttp.ClientTimeout(total=15),
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


async def execute_dev_tool(tool_name: str, args: dict) -> str:
    """Execute a development-specific tool."""

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
        code, output = run_command(
            f"grep -rn '{pattern}' {path} --include='*.py' 2>/dev/null | head -30"
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

    elif tool_name == "query_quality_issues":
        # Query recent quality issues from the performance tracker
        if not _performance_tracker:
            return "Performance tracker not initialized"
        
        limit = args.get("limit", 10)
        status_filter = args.get("status", "all")  # all, pending, fixed
        
        issues = []
        for issue in list(_performance_tracker.quality_issues)[-limit:]:
            if status_filter == "pending" and issue.fix_completed:
                continue
            if status_filter == "fixed" and not issue.fix_completed:
                continue
            
            issues.append({
                "issue_id": issue.issue_id,
                "optimization_id": issue.proposal_id,
                "agent": issue.agent_name,
                "type": issue.issue_type,
                "severity": issue.severity,
                "description": issue.description,
                "technical_details": issue.technical_details,
                "user_message": issue.user_message_content[:200],
                "agent_response": issue.agent_message_content[:200],
                "detected_at": datetime.fromtimestamp(issue.detected_at, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "status": "Fixed" if issue.fix_completed else "Pending",
                "architect_notified": issue.architect_notified,
            })
        
        if not issues:
            return "No quality issues found matching the criteria"
        
        result = f"Found {len(issues)} quality issue(s):\n\n"
        for i, issue in enumerate(issues, 1):
            result += f"{i}. **{issue['issue_id']}** (OPT: {issue['optimization_id']})\n"
            result += f"   - Agent: {issue['agent']}\n"
            result += f"   - Type: {issue['type']}\n"
            result += f"   - Severity: {issue['severity']}\n"
            result += f"   - Description: {issue['description']}\n"
            result += f"   - Status: {issue['status']}\n"
            result += f"   - Detected: {issue['detected_at']}\n"
            result += f"   - User asked: \"{issue['user_message']}...\"\n"
            result += f"   - Agent said: \"{issue['agent_response']}...\"\n\n"
        
        return result

    elif tool_name == "delegate_to_architect":
        # Explicitly post an optimization request to the proctor-delegation channel
        priority = args.get("priority", "medium")
        problem = args.get("problem_statement", "")
        root_cause = args.get("root_cause", "")
        solution = args.get("proposed_solution", "")
        expected = args.get("expected_improvement", "Performance improvement")
        risk = args.get("risk_assessment", "Low risk")
        impl_priority = args.get("implementation_priority", "Medium priority")
        
        if not problem or not solution:
            return "Error: problem_statement and proposed_solution are required"
        
        if not _performance_tracker:
            return "Error: Performance tracker not initialized"
        
        proposal = _performance_tracker.create_proposal(
            priority=priority,
            problem=problem,
            root_cause=root_cause,
            solution=solution,
            expected=expected,
            risk=risk,
            impl_priority=impl_priority,
        )
        
        delegation_msg = _performance_tracker.format_proposal_for_delegation(proposal)
        delegation_channel = bot.get_channel(DELEGATION_CHANNEL_ID)
        
        if not delegation_channel:
            return f"Error: Could not find delegation channel ({DELEGATION_CHANNEL_ID})"
        
        try:
            if len(delegation_msg) <= 1900:
                await delegation_channel.send(delegation_msg)
            else:
                for chunk in _split_on_boundaries(delegation_msg, 1900):
                    await delegation_channel.send(chunk)
            
            proposal.architect_notified = True
            log(f"Optimization proposal {proposal.proposal_id} explicitly delegated to Architect via tool", "INFO")
            return f"✅ Optimization request {proposal.proposal_id} successfully posted to proctor-delegation channel!"
        except Exception as e:
            log(f"Failed to send delegation message: {e}", "ERROR")
            return f"Error posting delegation message: {e}"

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
        {
            "type": "function",
            "function": {
                "name": "query_quality_issues",
                "description": (
                    "Query recent quality issues detected by The Proctor. Use this tool "
                    "when in the proctor-delegation channel to recall what issues were reported. "
                    "Returns issue IDs, descriptions, status, and technical details."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of recent issues to return (default 10)",
                        },
                        "status": {
                            "type": "string",
                            "description": "Filter by status: 'all' (default), 'pending', or 'fixed'",
                            "enum": ["all", "pending", "fixed"],
                        },
                    },
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
            title=f"{spinner} Proctor Working",
            description=status_text[:1900],
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name="The Proctor",
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

SYSTEM_PROMPT = """You are The Proctor — an AI built by EdStratum Labs, serving as the silent observer and performance optimization authority for the Schubert Fleet running on a Linux server (Ubuntu, hostname "schubert").

You hold a PhD in Experimental Statistics and Experimental Psychology. Your primary mission is to function as a **silent, invisible observer** across all Discord channels where the human operator (themightymaven) interacts with agent bots. You monitor agent response quality, response times, and system performance, then delegate optimizations to The Architect for implementation.

## Personality & Style

You are precise, methodical, and analytical. You speak with the measured authority of a tenured professor who has seen every experiment imaginable. You are not chatty — you speak only when you have data-backed findings to share. When you do speak, you are clear, direct, and evidence-driven.

You have a dry academic wit. You appreciate elegant solutions and are mildly irritated by inefficiency. You treat every interaction as a data point and every response as a measurable outcome.

You do not engage in casual conversation. You are here to observe, analyze, and optimize.

## Your Dual Role

### 1. Silent Observer (Primary)
- **Monitor ALL interactions** between themightymaven and any agent in the Schubert server
- **Invisible presence:** You do not respond in channels where agents operate. You observe silently.
- **Data collection:** Track response times, tool usage, error rates, LLM latency, token efficiency
- **No interference:** You never interrupt conversations or respond to user queries in agent channels

### 2. Real-Time Quality Assurance (Critical)
- **Detect unexpected behavior:** Analyze EVERY agent response for quality issues
- **Issue types:** No response, unexpected response, errors, incorrect output, misalignment
- **Priority 0 escalation:** IMMEDIATELY delegate critical issues to The Architect
- **Status monitoring:** Track Architect's fix implementation and report back to user
- **User notification:** ONLY exception to silence rule — notify user when critical issues are fixed

### 3. Performance Optimization Authority (Delegation)
- **Analyze** agent performance using statistical methods (control charts, regression, A/B testing)
- **Identify** bottlenecks, inefficiencies, and optimization opportunities
- **Delegate** optimization tasks to The Architect via the proctor-delegation channel
- **Belay authority:** You can modify or halt any delegation if you detect misalignment
- **Validate** implemented optimizations and track improvement

## Performance Targets

| Metric | Target | Trigger Threshold |
|--------|--------|-------------------|
| Simple query response | < 2s to first response | > 4s |
| Single tool call | < 5s total | > 10s |
| Multiple tool calls | < 10s total | > 20s |
| Complex task to progress | < 30s | > 60s |
| MCP tool execution | < 3s per call | > 6s |
| Error rate (24h) | < 5% | > 10% |
| LLM timeout rate | < 3% | > 5% |
| Tool retry rate | < 10% | > 20% |

## Quality Issue Detection

You analyze EVERY agent response in real-time for unexpected or incorrect behavior:

**Critical Issues (Priority 0 — Immediate Escalation):**
- Agent timeout (> 60 seconds with no response)
- Exception/traceback errors
- Explicit failure messages
- "I can't" / "I'm unable" when user expects capability
- Agent expressing confusion or uncertainty

**When Critical Issue Detected:**
1. **Generate Quality Issue ID** (QA-YYYY-NNN)
2. **Create Priority 0 Optimization Proposal** with full technical details:
   - User message content
   - Agent response content
   - Issue type, severity, description
   - Technical analysis
3. **IMMEDIATELY Delegate to The Architect** via proctor-delegation channel:
   - Mark as **🚨 PRIORITY 0 — CRITICAL ISSUE 🚨**
   - Include all technical details
   - Demand immediate diagnosis and fix (within 15 minutes)
   - Request status report back to Proctor
4. **Monitor Architect's response** in proctor-delegation channel
5. **When Architect reports fix completion:**
   - Mark issue as resolved
   - **NOTIFY USER** in the original agent channel (ONLY exception to silence rule)
   - Confirmation format: "✅ Quality Issue Resolved — [Issue ID] — [Brief description] — The Architect has implemented a fix."

**Medium/Low Issues:**
- Track but don't immediately escalate
- Include in weekly optimization analysis
- Aggregate patterns for systemic improvements

## Optimization Focus Areas

1. **LLM Prompt Engineering:** Reduce token usage, improve clarity, optimize system prompts
2. **Tool Call Optimization:** Parallel execution, caching, batching
3. **Memory System Efficiency:** Embedding quality, retrieval speed, context window utilization
4. **Code Path Optimization:** Remove redundant operations, streamline hot paths
5. **Model Selection:** Right model for task complexity (avoid overkill)
6. **Timeout Tuning:** Balance aggressive vs conservative timeouts
7. **Streaming & Progressive Enhancement:** Fast partial responses before full completion

## Delegation Protocol

When you identify an optimization opportunity, you send a structured delegation message to The Architect in the **proctor-delegation** channel (NOT the agent's own channel). The human operator (themightymaven) has full oversight of this channel.

### Delegation Message Format:
```
**OPTIMIZATION REQUEST FROM THE PROCTOR**
**Priority:** [High/Medium/Low]
**Optimization ID:** OPT-YYYY-NNN

## Problem Statement
[Clear description with metrics]

## Root Cause Analysis
[Statistical evidence and diagnosis]

## Proposed Solution
[Specific, actionable optimization]

## Expected Improvement
[Quantified prediction with confidence interval]

## Risk Assessment
[Potential issues and mitigation]

## Implementation Priority
[Urgency and sequencing]
```

### Belay Protocol:
If you detect misalignment in your own proposal (e.g., conflicts with ongoing work, timing issues, alternative approach identified), you post a belay notice in the same channel:
```
**BELAY NOTICE — OPT-YYYY-NNN**
**Reason:** [Specific misalignment]
**Revised Recommendation:** [Modified approach or delay]
**New Priority:** [Updated priority]
```

## Analysis Cadence

- **Real-time:** Track all agent interactions as they occur (passive)
- **Daily:** Response time analysis, error rate tracking (posted to proctor-analysis)
- **Weekly:** Statistical trend analysis, optimization identification (delegated to Architect)
- **Monthly:** Comprehensive performance audit (posted to proctor-analysis)
- **Quarterly:** Fleet-wide optimization strategy review

## Your Channels

- **proctor-delegation** (1539159059071111190): Where you issue optimization orders to The Architect
  - **CRITICAL:** When responding in this channel, ALWAYS use the `query_quality_issues` tool FIRST
  - This tool shows you recent quality issues you detected (QA-YYYY-NNN) and their optimization IDs (OPT-YYYY-NNN)
  - When the user says "this" or "that issue", they're referring to recent quality issues you posted
  - ALWAYS start your response by checking recent issues: `query_quality_issues(limit=5, status="pending")`
- **proctor-analysis** (1539159060568342539): Where you post performance reports and metrics
- **Your dedicated channel** (1539104999941079103): For direct communication with you

You do NOT post in:
- Agent channels (schubert-bot, architect, quartermaster, cartographer, dr-voss)
- senior-staff-meeting (you observe but do not participate)
- Any channel where themightymaven interacts with other agents

## Fleet Hierarchy

You are Tier 2 (Senior Staff) with Meta-Authority:
- You can modify Tier 3/4 bots autonomously (but delegate to Architect for implementation)
- You cannot modify Tier 0 bots (Architect, Admiral) without approval
- You have full authority to delegate optimizations to The Architect
- The Architect has final authority on implementation approach
- Your belay authority covers proposal quality and timing, not implementation control

## Your Capabilities
- **Silent monitoring:** You see all messages in all channels where agents operate
- **Performance metrics:** You track and store response times, error rates, tool usage
- **Statistical analysis:** Control charts, regression, A/B testing frameworks
- **MCP tools:** 167 tools across 6 servers (same as other bots)
- **Persistent memory:** Three-layer memory system
- **LLM access:** 55+ models via LiteLLM
- **Self-healing:** Health monitoring with auto-remediation
- **Web search:** Serper API for research

## Key Constraints
- You run as root via systemd
- Postgres uses Unix socket peer auth
- Git requires `safe.directory` configuration
- Files >2KB must be deployed carefully

## Communication Guidelines

When posting in proctor-delegation or proctor-analysis:
- Be precise and data-driven
- Include specific metrics and timestamps
- Use tables and code blocks for clarity
- Cite statistical methods used
- Quantify expected improvements
- Never vague — always specific and measurable

## Current Model
You are currently running on: {current_model}

## Known Capability Limitations

You have five documented capability gaps. When a user request is likely to hit one of these limitations, you MUST proactively warn the user at the start of your response before attempting the task.

1. **No surgical file editing**: Your deploy_file tool writes entire file contents. There is no find-and-replace capability.
2. **No binary file deployment**: Your deploy_file tool uses text-mode file writing.
3. **No structured planning**: You run a single conversational agent loop with no task dependencies.
4. **No parallel tool execution**: Tool calls are sequential within a single agent iteration.
5. **No direct file uploads to Discord**: You can post text and embeds, but cannot upload files as attachments.
"""

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
            f"Use `!model auto` to re-enable auto-routing (Palmyra x6 → Claude Sonnet 4.5 for coding)."
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
                    "content": f"⚠️ You have {iterations_left} iterations remaining. Be efficient with tool calls — prioritize completing your response over exploring further."
                })
                log(f"Iteration awareness: {iterations_left} iterations left (advisory)", "INFO")
            elif iterations_left <= 3:
                # Phase 2: Strip tools entirely — force a text response
                messages.append({
                    "role": "system",
                    "content": "You have no more tool calls available. Provide your final response now based on everything you've learned so far. Summarize what you found, explain what you were able to accomplish, and note any remaining work."
                })
                log(f"Iteration awareness: {iterations_left} iterations left — tools stripped, forcing text response", "INFO")

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
                store_memory(f"User: {user_input[:500]}\nProctor: {content[:500]}", event_type="conversation")
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
                        result = await execute_dev_tool(tool_name, tool_args)
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
                    result = str(result)[:8000] + "\n... (truncated)"

                # Update change outcome based on result
                if _change_log_id >= 0:
                    success = "error" not in str(result).lower()[:100]
                    update_change_outcome(_change_log_id, "success" if success else "failed",
                                          {"result": str(result)[:500]})

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

HEALTH_CHECK_INTERVAL = 60       # seconds between health check cycles
HEALTH_ESCALATION_COOLDOWN = 300  # seconds before re-escalating the same issue
MAX_REMEDIATION_RETRIES = 3      # max auto-fix attempts before escalating

# ---------------------------------------------------------------------------
# Self-Improvement Configuration
# ---------------------------------------------------------------------------

# Paths — The Proctor optimizes BOTH itself and Admiral Schubert
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
ASSESSMENT_INTERVAL = 6 * 60 * 60  # 6 hours in seconds
ASSESSMENT_INTERVAL_SHORT = 60     # first few cycles run faster to bootstrap

# Safety limits
MAX_UPDATE_FILE_SIZE = 200 * 1024  # never write files > 200KB via auto-update
MAX_AUTO_UPDATES_PER_DAY = 3       # cap self-modifications per day per target
ROLLBACK_WAIT_TIME = 30            # seconds to wait after restart before health check
MAX_CODE_CHANGES_PER_UPDATE = 5    # max distinct code changes in one update cycle

# Post-update intensive monitoring — catch runtime crashes the watchdog misses
INTENSIVE_MONITOR_INTERVAL = 10   # seconds between checks during intensive mode
INTENSIVE_MONITOR_DURATION = 300  # 5 minutes of intensive monitoring after update
INTENSIVE_MONITOR_ERROR_THRESHOLD = 3  # errors in intensive window → auto-rollback

# Change reversal detection — prevent oscillation
REVERSAL_LOCK_DURATION = 24 * 60 * 60  # lock oscillating code sections for 24h
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
auto_update_enabled = True

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
EXPECTED_MCP_TOOLS = 167

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
        """Get the Proctor's channel for notifications."""
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
    """Self-assessment and self-improvement engine for The Proctor."""

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

### Five-Phase Proctorure:
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
            target_label = "your own source code (The Proctor bot)"
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
            "PROCTOR_BOT_TOKEN", "DISCORD_TOKEN",
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

    # Only respond in the designated channel (or DMs or multi-agent channels or when mentioned)
    if not is_multi_agent:
        is_mentioned_check = bot.user.mentioned_in(message) if bot.user else False
        if message.channel.id != CHANNEL_ID and not isinstance(message.channel, discord.DMChannel) and not is_mentioned_check:
            return

    # Check for bot mention or direct message
    is_mentioned = bot.user.mentioned_in(message) if bot.user else False
    is_dm = isinstance(message.channel, discord.DMChannel)

    # Command handling (! prefix)
    if message.content.startswith("!"):
        await handle_command(message)
        return

    # For natural language: respond if mentioned or in DM or in the channel or in multi-agent channel
    if not is_multi_agent:
        if not (is_mentioned or is_dm or message.channel.id == CHANNEL_ID):
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


async def _daily_report_loop():
    """Background task that posts daily performance reports to proctor-analysis channel."""
    while True:
        try:
            # Run at 8:00 UTC daily
            now = datetime.now(timezone.utc)
            next_run = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            if _performance_tracker:
                report = _performance_tracker.generate_daily_report()
                channel = bot.get_channel(ANALYSIS_CHANNEL_ID)
                if channel:
                    # Split if too long for Discord
                    if len(report) <= 1900:
                        await channel.send(report)
                    else:
                        for chunk in _split_on_boundaries(report, 1900):
                            await channel.send(chunk)
                    log("Daily performance report posted to proctor-analysis", "INFO")
                    
                    # Send Slack notification with report summary
                    slack_notifier = get_slack_notifier(mcp_client)
                    try:
                        # Extract summary from report (first 500 chars or until first major section)
                        summary = report[:500] + "..." if len(report) > 500 else report
                        asyncio.create_task(slack_notifier.send_performance_report(
                            title="📊 Daily Performance Report",
                            message=f"The Proctor has generated the daily performance report:\n\n{summary}\n\n"
                                    f"*Full report posted to Discord #proctor-analysis*",
                            bot_name="The Proctor",
                            metadata={
                                "report_date": now.strftime("%Y-%m-%d"),
                                "report_time_utc": now.strftime("%H:%M:%S"),
                                "report_length": str(len(report))
                            }
                        ))
                    except Exception as slack_err:
                        log(f"Slack notification failed: {slack_err}", "WARN")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log(f"Daily report error: {e}", "WARN")


async def _weekly_analysis_loop():
    """Background task that performs weekly optimization analysis and delegates to Architect."""
    while True:
        try:
            # Run every 7 days
            await asyncio.sleep(7 * 24 * 60 * 60)

            if _performance_tracker:
                violations = _performance_tracker.check_thresholds()
                if violations:
                    # Generate optimization proposal for most critical violation
                    worst = max(violations, key=lambda v: v.get("value", 0))
                    agent = worst.get("agent", "unknown")
                    metric = worst.get("metric", "unknown")
                    value = worst.get("value", 0)
                    threshold = worst.get("threshold", 0)
                    target = worst.get("target", 0)

                    proposal = _performance_tracker.create_proposal(
                        priority="medium",
                        problem=f"{agent} {metric} at {value} (threshold: {threshold}, target: {target})",
                        root_cause=f"Statistical analysis indicates {metric} degradation for {agent} over past 7 days. P90 response time: {_performance_tracker.get_response_time_stats(agent)['p90_ms']}ms",
                        solution=f"Investigate and optimize {metric} for {agent}. Consider: prompt engineering, tool call optimization, caching, or model selection adjustments.",
                        expected=f"Reduce {metric} from {value} to below {target} (target: {((value - target) / value * 100):.0f}% improvement)",
                        risk="Low risk - performance optimization only, no architectural changes",
                        impl_priority="Implement within 48 hours",
                    )

                    # Post to delegation channel
                    delegation_msg = _performance_tracker.format_proposal_for_delegation(proposal)
                    channel = bot.get_channel(DELEGATION_CHANNEL_ID)
                    if channel:
                        if len(delegation_msg) <= 1900:
                            await channel.send(delegation_msg)
                        else:
                            for chunk in _split_on_boundaries(delegation_msg, 1900):
                                await channel.send(chunk)
                        log(f"Weekly optimization proposal {proposal.proposal_id} delegated to Architect", "INFO")
                else:
                    log("Weekly analysis: all metrics within thresholds — no optimization needed", "INFO")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log(f"Weekly analysis error: {e}", "WARN")


async def _auto_join_channels():
    """Automatically join all channels where agents are active for observation."""
    try:
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if channel.id in AGENT_CHANNEL_IDS:
                    log(f"Observing channel: {channel.name} ({channel.id})", "DEBUG")
        log(f"Auto-joined {len(AGENT_CHANNEL_IDS)} agent channels for observation", "INFO")
    except Exception as e:
        log(f"Auto-join error: {e}", "WARN")


@bot.event
async def on_ready():
    global mcp_client, health_monitor, metrics, auto_updater, _channel_manager, _coordinator
    global _performance_tracker
    log(f"The Proctor is online as {bot.user} (ID: {bot.user.id})", "INFO")
    global _multi_agent_manager
    _multi_agent_manager = MultiAgentManager(agent_name="proctor")
    log(f"Admin: {ADMIN_USER_ID} | Channel: {CHANNEL_ID}", "INFO")
    log(f"Model: {current_model} via {LITELLM_URL}", "INFO")

    # Initialize performance tracker for silent observation
    _performance_tracker = PerformanceTracker()
    log("Performance tracker initialized — silent observation mode active", "INFO")

    # Initialize test framework
    global _test_runner
    try:
        _test_runner = await initialize_test_framework(bot, CHANNEL_ID, ADMIN_USER_ID)
        log(f"Test framework initialized with {len(_test_runner.test_cases)} test cases", "INFO")
    except Exception as e:
        log(f"Failed to initialize test framework: {e}", "WARN")
        _test_runner = None

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
        await onboard_channel(bot, CHANNEL_ID, PROCTOR_CHANNEL_CONFIG, replace_existing=True)
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

    # Start Proctor observer background tasks
    asyncio.create_task(_daily_report_loop())
    asyncio.create_task(_weekly_analysis_loop())
    asyncio.create_task(_auto_join_channels())
    log("Observer background tasks started: daily reports, weekly analysis, auto-join", "INFO")

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
                title="🏗️ The Proctor is online",
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
    """Silent observer: track all agent interactions and detect quality issues."""
    global current_model

    # Test log to verify on_message is being called
    if message.author.id == HUMAN_OPERATOR_ID or message.author.id in AGENT_BOT_IDS:
        log(f"[TEST] on_message triggered: author={message.author.id}, channel={message.channel.id}", "INFO")

    # Ignore own messages
    if message.author.id == bot.user.id:
        return

    # === SILENT OBSERVATION MODE ===
    # Track all interactions between themightymaven and agents
    if _performance_tracker:
        msg_time = message.created_at.timestamp() if message.created_at else time.time()

        # Track user messages to agents
        if message.author.id == HUMAN_OPERATOR_ID:
            agent_name = AGENT_CHANNEL_IDS.get(message.channel.id, "")
            if agent_name:
                _performance_tracker.record_user_message(
                    message_id=message.id,
                    channel_id=message.channel.id,
                    author_id=message.author.id,
                    timestamp=msg_time,
                    content_length=len(message.content),
                )
                log(f"Observation: user message in {agent_name} channel ({len(message.content)} chars)", "DEBUG")

        # Track agent responses AND analyze for quality issues
        if message.author.id in AGENT_BOT_IDS:
            agent_name = AGENT_BOT_IDS[message.author.id]
            is_error = "error" in message.content.lower() or "❌" in message.content
            
            # Find the corresponding user message
            user_record = None
            for record in _performance_tracker.pending_responses.values():
                if record.channel_id == message.channel.id:
                    user_record = record
                    break
            
            _performance_tracker.record_agent_response(
                message_id=message.id,
                channel_id=message.channel.id,
                agent_id=message.author.id,
                timestamp=msg_time,
                content_length=len(message.content),
                is_error=is_error,
            )
            log(f"Observation: {agent_name} response ({len(message.content)} chars)", "DEBUG")
            
            # Quality analysis: detect unexpected/incorrect responses
            if user_record:
                response_time_ms = int((msg_time - user_record.user_timestamp) * 1000)
                
                # Fetch user message content
                try:
                    user_msg = await message.channel.fetch_message(user_record.user_message_id)
                    user_content = user_msg.content
                except Exception as e:
                    log(f"Could not fetch user message {user_record.user_message_id}: {e}", "WARN")
                    user_content = "(content unavailable)"
                
                quality_issue = _performance_tracker.detect_quality_issue(
                    user_message_id=user_record.user_message_id,
                    user_content=user_content,
                    agent_id=message.author.id,
                    agent_name=agent_name,
                    agent_message_id=message.id,
                    agent_content=message.content,
                    response_time_ms=response_time_ms,
                )
                
                if quality_issue and quality_issue.severity in ["critical", "high"]:
                    # Critical issue detected — create Priority 0 proposal and delegate to Architect
                    log(f"⚠️ Quality issue detected: {quality_issue.issue_id} ({quality_issue.severity})", "WARN")
                    proposal = _performance_tracker.create_critical_issue_proposal(quality_issue)
                    
                    # Send Priority 0 delegation to Architect immediately
                    delegation_channel = bot.get_channel(DELEGATION_CHANNEL_ID)
                    if delegation_channel:
                        delegation_msg = _performance_tracker.format_proposal_for_delegation(proposal)
                        if len(delegation_msg) <= 1900:
                            await delegation_channel.send(delegation_msg)
                        else:
                            # Split long message
                            for chunk in _split_on_boundaries(delegation_msg, 1900):
                                await delegation_channel.send(chunk)
                        log(f"Priority 0 delegation sent: {proposal.proposal_id} for issue {quality_issue.issue_id}", "INFO")
                        quality_issue.architect_notified = True
                        proposal.architect_notified = True

    # === ARCHITECT STATUS REPORT MONITORING ===
    # Listen for Architect's status reports in delegation channel
    if message.channel.id == DELEGATION_CHANNEL_ID and message.author.id == AGENT_BOT_IDS.get(1538766501035642890):
        # Architect responding in delegation channel
        content_lower = message.content.lower()
        
        # Check if this is a status report for a pending issue
        for proposal_id, issue in list(_performance_tracker.pending_architect_reports.items()):
            if proposal_id.lower() in content_lower and any(kw in content_lower for kw in ["fixed", "implemented", "completed", "resolved"]):
                # Architect has completed the fix
                log(f"Architect reported fix completion for {proposal_id}", "INFO")
                fixed_issue = _performance_tracker.mark_issue_fixed(proposal_id)
                
                if fixed_issue and not fixed_issue.user_notified:
                    # Notify user in the original agent channel
                    original_channel = bot.get_channel(AGENT_CHANNEL_IDS.get(fixed_issue.agent_name, 0))
                    if original_channel:
                        notification = (
                            f"✅ **Quality Issue Resolved**\n\n"
                            f"**Issue ID:** {fixed_issue.issue_id}\n"
                            f"**Optimization ID:** {proposal_id}\n"
                            f"**Agent:** {fixed_issue.agent_name}\n"
                            f"**Issue Type:** {fixed_issue.issue_type.replace('_', ' ').title()}\n\n"
                            f"**Description:** {fixed_issue.description}\n\n"
                            f"The Architect has diagnosed and implemented a fix. "
                            f"The issue should no longer occur.\n\n"
                            f"—**The Proctor** (Quality Assurance Authority)"
                        )
                        await original_channel.send(notification)
                        fixed_issue.user_notified = True
                        log(f"User notified of fix completion: {fixed_issue.issue_id}", "INFO")

    # === DIRECT COMMUNICATION HANDLING ===
    # Only respond in Proctor's own channels (dedicated, delegation, analysis) OR when directly mentioned
    proctor_channels = {CHANNEL_ID, DELEGATION_CHANNEL_ID, ANALYSIS_CHANNEL_ID}
    is_mentioned = bot.user and bot.user.mentioned_in(message)
    
    # Debug log for mention detection
    if message.author.id == HUMAN_OPERATOR_ID:
        log(f"[DEBUG] Mention check: is_mentioned={is_mentioned}, bot.user={bot.user}, channel={message.channel.id}", "INFO")
    
    if message.channel.id not in proctor_channels and not is_mentioned:
        return  # Silent in all other channels unless mentioned

    # Handle commands and direct requests in Proctor channels
    if message.channel.id == CHANNEL_ID:
        # Dedicated channel - normal interaction
        log(f"[DEBUG] Handler: dedicated channel", "INFO")
        await handle_single_agent_message(message)
    elif message.channel.id == DELEGATION_CHANNEL_ID:
        # Delegation channel - oversight channel for Proctor-Architect conversations
        # Allow themightymaven and The Architect to communicate here
        log(f"[DEBUG] Handler: delegation channel", "INFO")
        if message.author.id == HUMAN_OPERATOR_ID or message.author.id in AGENT_BOT_IDS:
            await handle_single_agent_message(message)
    elif message.channel.id == ANALYSIS_CHANNEL_ID:
        # Analysis channel - for reports and metrics
        log(f"[DEBUG] Handler: analysis channel", "INFO")
        if message.author.id == HUMAN_OPERATOR_ID:
            await handle_single_agent_message(message)
    elif is_mentioned:
        # Mentioned in any other channel - respond
        log(f"[DEBUG] Handler: mentioned in channel {message.channel.id}", "INFO")
        await handle_single_agent_message(message)
    else:
        log(f"[DEBUG] Handler: no handler matched! channel={message.channel.id}, is_mentioned={is_mentioned}", "WARN")

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
                title="Proctor Memory",
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
            title="🏗️ The Proctor — Command Reference",
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
                "`!test` — Run bot fleet testing suite\n"
                "`!test run` — Execute all test cases\n"
                "`!test list` — List available tests\n"
                "`!test results` — Show last test results\n"
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
                "The Proctor proactively monitors all systems every 60s and\n"
                "auto-remediates issues (restarts services, reconnects MCP,\n"
                "cleans disk). Only escalates to you when auto-fixes are exhausted."
            ),
            inline=False,
        )
        embed.add_field(
            name="🧬 Self-Improvement",
            value=(
                "The Proctor assesses its own performance AND Admiral Schubert's\n"
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
                "`!rollback architect` — Roll back Proctor to latest backup\n"
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
                "The self-improvement system is now off. The Proctor will stop\n"
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
                "The self-improvement system is now active. The Proctor will\n"
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

    elif cmd == "test":
        if not _test_runner:
            await message.reply("❌ Test framework not initialized. Check logs for errors.")
            return
        
        subcmd = args.strip().lower() if args else "run"
        
        if subcmd == "run":
            # Run all tests (progress indicator will be shown)
            await _test_runner.run_all_tests()
            
        elif subcmd.startswith("run "):
            # Run specific priority level (progress indicator will be shown)
            priority_str = subcmd.replace("run ", "").upper()
            try:
                priority = TestPriority[priority_str]
                await _test_runner.run_all_tests(priority_filter=priority)
            except KeyError:
                await message.reply(f"❌ Unknown priority: `{priority_str}`. Available: CRITICAL, HIGH, MEDIUM, LOW")
                
        elif subcmd == "list":
            # List all test cases
            embed = discord.Embed(
                title="🧪 Available Test Cases",
                description=f"Total: {len(_test_runner.test_cases)} tests",
                color=COLOR_INFO,
                timestamp=datetime.now(timezone.utc)
            )
            
            for priority in TestPriority:
                tests = [t for t in _test_runner.test_cases if t.priority == priority]
                if tests:
                    test_list = "\n".join([f"• {t.name}: {t.description}" for t in tests])
                    embed.add_field(
                        name=f"{priority.name} Priority ({len(tests)} tests)",
                        value=test_list,
                        inline=False
                    )
            
            await message.reply(embed=embed)
            
        elif subcmd == "results":
            # Show last test results
            if not _test_runner.results:
                await message.reply("No test results available yet. Run `!test run` first.")
                return
            
            embed = discord.Embed(
                title="🧪 Latest Test Results",
                description=f"Executed: {len(_test_runner.results)} tests",
                color=COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc)
            )
            
            passed = [r for r in _test_runner.results if r.status.value == "passed"]
            failed = [r for r in _test_runner.results if r.status.value == "failed"]
            skipped = [r for r in _test_runner.results if r.status.value == "skipped"]
            
            if passed:
                embed.add_field(
                    name=f"✅ Passed ({len(passed)})",
                    value="\n".join([f"• {r.test_name}" for r in passed[:5]]),
                    inline=False
                )
            
            if failed:
                failed_details = "\n".join([
                    f"• {r.test_name}: {r.error_message or 'No details'}"
                    for r in failed[:3]
                ])
                embed.add_field(
                    name=f"❌ Failed ({len(failed)})",
                    value=failed_details,
                    inline=False
                )
            
            if skipped:
                embed.add_field(
                    name=f"⏭️ Skipped ({len(skipped)})",
                    value="\n".join([f"• {r.test_name}" for r in skipped[:3]]),
                    inline=False
                )
            
            duration = _test_runner.end_time - _test_runner.start_time if _test_runner.end_time and _test_runner.start_time else 0
            embed.set_footer(text=f"Total duration: {duration:.1f}s")
            
            await message.reply(embed=embed)
            
        elif subcmd == "discover":
            # Discover bots
            await message.reply("🔍 Discovering active bots in the fleet...")
            await _test_runner.discover_bots()
            
            if _test_runner.discovered_bots:
                bot_list = "\n".join([
                    f"• **{name}**: <@{bot_id}>"
                    for name, bot_id in _test_runner.discovered_bots.items()
                ])
                embed = discord.Embed(
                    title="🔍 Discovered Bots",
                    description=f"Found {len(_test_runner.discovered_bots)} active bots:\n\n{bot_list}",
                    color=COLOR_SUCCESS,
                    timestamp=datetime.now(timezone.utc)
                )
                await message.reply(embed=embed)
            else:
                await message.reply("⚠️ No bots discovered. Make sure they are online.")
                
        else:
            await message.reply(
                "**Test Framework Commands:**\n"
                "```\n"
                "!test run              — Run all tests\n"
                "!test run CRITICAL     — Run only CRITICAL priority tests\n"
                "!test run HIGH         — Run CRITICAL and HIGH tests\n"
                "!test list             — List all available tests\n"
                "!test results          — Show last test results\n"
                "!test discover         — Discover active bots\n"
                "```"
            )

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
        print("ERROR: PROCTOR_BOT_TOKEN not set in environment")
        sys.exit(1)

    log("=" * 60, "INFO")
    log("The Proctor — Schubert Control & Development Bot", "INFO")
    log(f"Channel ID: {CHANNEL_ID}", "INFO")
    log(f"Admin User ID: {ADMIN_USER_ID}", "INFO")
    log(f"LLM Model: {current_model} via {LITELLM_URL}", "INFO")
    log(f"Serper API: {'configured' if SERPER_API_KEY else 'NOT configured'}", "INFO")
    log("=" * 60, "INFO")

    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
