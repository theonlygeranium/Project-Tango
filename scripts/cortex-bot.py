#!/usr/bin/env python3
"""
Dr. Cortex — Chief Science Officer (AI Research & Optimization)
================================================================
A separate Discord bot for monitoring the latest trends, research, and best
practices in AI, then translating theory into practice by recommending concrete
optimizations, edits, and enhancements to the Discord bots and the Schubert
server — keeping the server operating on the latest AI standards.

Capabilities:
  - LLM reasoning via LiteLLM (runtime-switchable)
  - MCP tool access (same servers as fleet)
  - Web search (Serper API + SearxNG) — primary tool for AI research
  - Research tools (scan_ai_trends, analyze_bot_code, benchmark_model,
    recommend_optimization, audit_prompts)
  - Multi-LLM routing (!model command + dropdown UI)
  - Live processing indicator (typing + spinner + elapsed time)
  - Three-layer persistent memory (Redis + Postgres + Ollama)
  - Fleet delegation support via FLEET protocol

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
# Also allow importing from this file's directory (repo / cloud agent checkout)
_LOCAL_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOCAL_SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_SCRIPT_DIR)

try:
    from fleet_config_loader import get_bot_config
    _cfg = get_bot_config("cortex")
except Exception:
    _cfg = {}

_llm = _cfg.get("llm", {}) if isinstance(_cfg.get("llm", {}), dict) else {}
_prompt = _cfg.get("prompt", {}) if isinstance(_cfg.get("prompt", {}), dict) else {}
_guardrails = _cfg.get("guardrails", {}) if isinstance(_cfg.get("guardrails", {}), dict) else {}
_mcp = _cfg.get("mcp", {}) if isinstance(_cfg.get("mcp", {}), dict) else {}
_memory = _cfg.get("memory", {}) if isinstance(_cfg.get("memory", {}), dict) else {}
_voice = _cfg.get("voice", {}) if isinstance(_cfg.get("voice", {}), dict) else {}

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

# Multi-agent coordinator imports
from conversation_coordinator import ConversationCoordinator, MultiAgentChannelManager
from response_scoring import calculate_response_score, should_respond_immediately, should_respond_with_delay, get_response_delay
from multi_agent_config import get_agent_profile, register_channel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("CORTEX_BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CORTEX_CHANNEL_ID", "0"))
ADMIN_USER_ID = 1075596247966167131  # Jeff Geronimo (themightymaven)
_multi_agent_manager: MultiAgentManager | None = None
SCHUBERT_BOT_ID = int(os.environ.get("SCHUBERT_BOT_ID", "0"))

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
SESSION_MAX_MESSAGES = _llm.get("session_window", 35)

# Multi-LLM routing — default model and available models
# Dr. Cortex: Palmyra x6 for research/analysis and code review
DEFAULT_MODEL = _llm.get("model", "writer/palmyra-x6")
CODING_MODEL = _llm.get("coding_model", "writer/palmyra-x6")
current_model = DEFAULT_MODEL
user_model_override = False  # Set True when user manually selects via !model

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

LLM_TEMPERATURE = _llm.get("temperature", 0.4)  # Slightly higher than ops bots — research benefits from more exploration
LLM_MAX_TOKENS = _llm.get("max_tokens", 4096)
LLM_TIMEOUT = _llm.get("llm_timeout", 180)
MAX_ITERATIONS = _llm.get("max_iterations", 30)
AGENT_TIMEOUT = _llm.get("agent_timeout", 480)
TOOL_OUTPUT_LIMIT = _llm.get("tool_output_limit", 4000)
SHELL_TIMEOUT = _llm.get("shell_timeout", 120)
RATE_LIMIT_PER_MIN = _llm.get("rate_limit_per_min", 10)

# Memory
COSINE_THRESHOLD = _memory.get("cosine_threshold", 0.75)
MAX_MEMORY_INJECTION_TOKENS = _memory.get("max_memory_injection_tokens", 2000)
MEMORY_DECAY_FLOOR = _memory.get("decay_floor", 0.1)
MAX_RECALL_RESULTS = _memory.get("max_recall_results", 5)
MAX_SEARCH_RESULTS = _memory.get("max_search_results", 5)
MEMORY_STORAGE_THRESHOLD = _memory.get("memory_storage_threshold", 0.5)

# MCP
MCP_REQUEST_TIMEOUT = _mcp.get("request_timeout", 60)
MCP_TOOL_CACHE_TTL = _mcp.get("tool_cache_ttl", 300)
MCP_TOOL_CACHE_REFRESH_ON_ERROR = _mcp.get("tool_cache_refresh_on_error", True)

# Voice (optional; cortex may enable later)
DEFAULT_VOICE_ID = _voice.get("voice_id", "")
VAD_SPEECH_RMS_THRESHOLD = _voice.get("vad_speech_rms_threshold", 100)
VAD_SILENCE_FRAMES_LIMIT = _voice.get("vad_silence_frames_limit", 15)
VAD_MIN_SPEECH_FRAMES = _voice.get("vad_min_speech_frames", 10)
TTS_STABILITY = _voice.get("tts_stability", 0.5)
TTS_SIMILARITY_BOOST = _voice.get("tts_similarity_boost", 0.75)
TTS_TEXT_TRUNCATION = _voice.get("tts_text_truncation", 500)
VOICE_RESPONSE_TRUNCATION = _voice.get("voice_response_truncation", 1900)
STT_TIMEOUT = _voice.get("stt_timeout", 30)
TTS_TIMEOUT = _voice.get("tts_timeout", 30)
MIN_PCM_LENGTH = _voice.get("min_pcm_length", 1000)

# Colors — amber/gold theme for Cortex (crystalline amber alien)
COLOR_AMBER  = 0xFFB300   # warm amber — primary Cortex colour
COLOR_INFO   = 0x5865F2   # discord blurple
COLOR_SUCCESS = 0x57F287  # green
COLOR_WARN   = 0xFEE75C   # yellow
COLOR_ERROR  = 0xED4245   # red

# Auto-thread thresholds
THREAD_RESPONSE_THRESHOLD = 500
THREAD_TOOL_CALL_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Auto Model Routing — Palmyra x6 for research and code
# ---------------------------------------------------------------------------

CODING_PATTERNS = [
    "code", "function", "class", "method", "variable", "def ", "import ",
    "script", "deploy", "bug", "fix", "debug", "patch", "refactor",
    "edit", "modify", "update", "rewrite", "implement", "write a",
    ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".sh",
    ".html", ".css", ".sql", ".env", "config", "syntax",
    "error", "traceback", "exception", "stack trace", "log",
    "regex", "api", "endpoint", "database", "query", "schema",
    "service", "systemd", "restart", "deploy", "commit", "git",
    "test", "pytest", "unittest", "lint", "type error",
    "async", "await", "thread", "coroutine", "event loop",
    "docker", "container", "nginx", "caddy",
]


def is_coding_task(user_input: str) -> bool:
    text = user_input.lower()
    return any(pattern in text for pattern in CODING_PATTERNS)


def select_model_for_task(user_input: str) -> str:
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
logger = logging.getLogger("cortex-bot")


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
                    return {
                        "error": f"LLM API returned {resp.status}: {error_text[:200]}",
                        "choices": [],
                    }
                return await resp.json()

    except asyncio.TimeoutError:
        log("LLM call timed out", "ERROR")
        return {"error": "LLM call timed out", "choices": []}
    except aiohttp.ClientError as e:
        log(f"LLM network error (retryable): {e}", "WARN")
        return {"error": f"Network error: {e}", "choices": [], "retryable": True}
    except Exception as e:
        log(f"LLM call failed: {e}", "ERROR")
        return {"error": str(e), "choices": []}


# ---------------------------------------------------------------------------
# Streaming LLM Chat — typewriter-style output via SSE
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
                log(f"LLM stream complete: {len(accumulated_content)} chars, {len(accumulated_tool_calls)} tool calls", "INFO")
                return {"choices": [{"message": message, "finish_reason": finish_reason or "stop"}]}
    except asyncio.TimeoutError:
        log("LLM stream timed out", "ERROR")
        return {"error": "LLM stream timed out", "choices": []}
    except aiohttp.ClientError as e:
        log(f"LLM stream network error (retryable): {e}", "WARN")
        return {"error": f"Network error: {e}", "choices": [], "retryable": True}
    except Exception as e:
        log(f"LLM stream failed: {e}", "ERROR")
        return {"error": str(e), "choices": []}


# ---------------------------------------------------------------------------
# Web Search (Serper API) — primary research channel for Dr. Cortex
# ---------------------------------------------------------------------------

async def web_search(query: str, num_results: int = 8) -> str:
    """Search the web using Serper API. Core tool for AI research tasks."""
    if not SERPER_API_KEY:
        return "Web search unavailable — SERPER_API_KEY not configured."

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"q": query, "num": num_results}
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

        if data.get("answerBox"):
            ab = data["answerBox"]
            answer = ab.get("answer") or ab.get("snippet") or ab.get("title", "")
            if answer:
                results.insert(0, f"**Answer:** {answer}")

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
# Shell & File Utilities
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


# ---------------------------------------------------------------------------
# Research Tools (Dr. Cortex specialty)
# ---------------------------------------------------------------------------

async def execute_research_tool(tool_name: str, args: dict) -> str:
    """Execute a research/optimization tool specific to Dr. Cortex."""

    # ── Web search (general + AI-targeted) ──────────────────────────────
    if tool_name == "web_search":
        query = args.get("query", "")
        if not query:
            return "Error: 'query' is required"
        num = args.get("num_results", 8)
        return await web_search(query, num_results=num)

    # ── Scan AI trends (sugar-coated web search aimed at current AI news) ──
    elif tool_name == "scan_ai_trends":
        topic = args.get("topic", "AI research")
        queries = [
            f"{topic} latest research 2026",
            f"{topic} best practices state of the art",
            f"{topic} arXiv paper 2026",
        ]
        results = []
        for q in queries:
            results.append(f"### Query: {q}")
            results.append(await web_search(q, num_results=5))
        return "\n\n".join(results)

    # ── Read bot code ────────────────────────────────────────────────────
    elif tool_name == "read_code":
        path = args.get("path", "")
        start_line = args.get("start_line", 1)
        end_line = args.get("end_line", 80)
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

    # ── Search code ──────────────────────────────────────────────────────
    elif tool_name == "search_code":
        pattern = args.get("pattern", "")
        path = args.get("path", "/opt/Project-Tango/scripts")
        if not pattern:
            return "Error: 'pattern' is required"
        code, output = run_command(
            f"grep -rn '{pattern}' {path} --include='*.py' 2>/dev/null | head -40"
        )
        return output if output else "No matches found"

    # ── Analyze bot code for optimization opportunities ──────────────────
    elif tool_name == "analyze_bot_code":
        bot_name = args.get("bot_name", "schubert-bot-v2")
        path = f"/opt/Project-Tango/scripts/{bot_name}.py"
        try:
            with open(path, "r") as f:
                content = f.read()
            lines = content.splitlines()
            total_lines = len(lines)
            # Collect basic metrics
            fn_count = sum(1 for l in lines if re.match(r'\s*async def |^\s*def ', l))
            class_count = sum(1 for l in lines if re.match(r'^\s*class ', l))
            todo_count = sum(1 for l in lines if "TODO" in l or "FIXME" in l or "HACK" in l)
            comment_lines = sum(1 for l in lines if l.strip().startswith("#"))
            blank_lines = sum(1 for l in lines if l.strip() == "")
            code_lines = total_lines - comment_lines - blank_lines
            # Extract system prompt size
            sp_match = re.search(r'SYSTEM_PROMPT\s*=\s*"""(.*?)"""', content, re.DOTALL)
            sp_size = len(sp_match.group(1)) if sp_match else 0
            # Detect model references
            model_refs = re.findall(r'writer/[a-z0-9._-]+|openai/[a-z0-9._-]+|google/[a-z0-9._-]+', content)
            unique_models = list(dict.fromkeys(model_refs))
            summary = (
                f"**Code Analysis: {bot_name}.py** ({total_lines} lines)\n"
                f"  Code: {code_lines} | Comments: {comment_lines} | Blank: {blank_lines}\n"
                f"  Functions/coroutines: {fn_count}\n"
                f"  Classes: {class_count}\n"
                f"  TODO/FIXME/HACK markers: {todo_count}\n"
                f"  System prompt size: {sp_size:,} chars\n"
                f"  Model references: {', '.join(unique_models) if unique_models else 'none found'}\n"
            )
            # Snippet of the system prompt first 500 chars
            if sp_match:
                snippet = sp_match.group(1).strip()[:500]
                summary += f"\n**System prompt preview:**\n```\n{snippet}...\n```"
            return summary
        except FileNotFoundError:
            return f"Script not found: {path}"
        except Exception as e:
            return f"Error analyzing {bot_name}: {e}"

    # ── Deploy file ───────────────────────────────────────────────────────
    elif tool_name == "deploy_file":
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

    # ── Restart service ───────────────────────────────────────────────────
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

    # ── View logs ─────────────────────────────────────────────────────────
    elif tool_name == "view_logs":
        service = args.get("service", "schubert-bot.service")
        lines = args.get("lines", 30)
        if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
            return f"Error: invalid service name '{service}'"
        code, output = run_command(
            f"sudo journalctl -u {service} --no-pager -n {lines} -o cat 2>&1"
        )
        return output[-3000:] if len(output) > 3000 else output

    # ── Service status ────────────────────────────────────────────────────
    elif tool_name == "service_status":
        services = [
            "schubert-bot", "schubert-architect", "schubert-dr-voss",
            "schubert-proctor", "schubert-quartermaster", "schubert-cartographer",
            "schubert-cortex", "polyglot-litellm", "mcp-server",
            "caddy", "cloudflared", "postgresql", "ollama",
        ]
        status_lines = []
        for svc in services:
            code, status = run_command(f"systemctl is-active {svc}")
            icon = "✅" if status.strip() == "active" else "❌"
            status_lines.append(f"  {icon} {svc}: {status.strip()}")
        code, failed = run_command(
            "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $2}'"
        )
        if failed.strip():
            status_lines.append(f"\n  ⚠️ Failed: {failed.strip()}")
        return "\n".join(status_lines)

    # ── Benchmark model (compare latency across available models) ─────────
    elif tool_name == "benchmark_model":
        model = args.get("model", current_model)
        prompt = args.get("prompt", "Summarise the transformer architecture in 2 sentences.")
        messages = [
            {"role": "system", "content": "You are a helpful AI."},
            {"role": "user", "content": prompt},
        ]
        start = time.time()
        result = await llm_chat(messages, model=model)
        elapsed = time.time() - start
        choices = result.get("choices", [])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        if result.get("error"):
            return f"Benchmark failed for {model}: {result['error']}"
        tokens_approx = len(content.split())
        return (
            f"**Benchmark: `{model}`**\n"
            f"  Latency: {elapsed:.2f}s\n"
            f"  Approx output tokens: {tokens_approx}\n"
            f"  Tokens/sec (approx): {tokens_approx/elapsed:.1f}\n"
            f"  Sample response: {content[:300]}"
        )

    # ── Query memory ──────────────────────────────────────────────────────
    elif tool_name == "query_memory":
        return handle_query_memory(args)

    # ── Cloudflare ────────────────────────────────────────────────────────
    elif tool_name == "cloudflare":
        action = args.get("action", "")
        if not action:
            return "Error: 'action' is required for cloudflare tool"
        return await execute_cloudflare_tool(action, args)

    return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Tool Definitions (for LLM)
# ---------------------------------------------------------------------------

def get_research_tools() -> list[dict]:
    """Return Dr. Cortex's research/optimization tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web for current information. "
                    "Primary tool for finding the latest AI research papers, model releases, "
                    "benchmarks, best practices, and optimization techniques."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query — be specific, include year for recency"},
                        "num_results": {"type": "integer", "description": "Number of results (default 8, max 10)"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "scan_ai_trends",
                "description": (
                    "Perform a multi-query sweep of the latest AI research and trends "
                    "on a given topic. Returns results from multiple search angles."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "AI topic to research (e.g. 'RAG optimization', 'prompt compression', 'LLM memory')"},
                    },
                    "required": ["topic"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_bot_code",
                "description": (
                    "Analyze a bot script for optimization opportunities. "
                    "Returns code metrics, system prompt size, model references, and TODO markers."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bot_name": {
                            "type": "string",
                            "description": "Bot script name without .py (e.g. 'schubert-bot-v2', 'architect-bot', 'dr-voss-bot')",
                        },
                    },
                    "required": ["bot_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_code",
                "description": "Read lines from a bot script. Use to inspect system prompts, guardrails, or specific functions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute file path"},
                        "start_line": {"type": "integer", "description": "Starting line (default 1)"},
                        "end_line": {"type": "integer", "description": "Ending line (default 80)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search for a pattern across all bot scripts using grep.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Search pattern"},
                        "path": {"type": "string", "description": "Directory to search (default /opt/Project-Tango/scripts)"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "benchmark_model",
                "description": (
                    "Benchmark an LLM model via LiteLLM — measures latency and throughput "
                    "against a standard prompt. Use to compare models for fleet assignment."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string", "description": "Model string e.g. 'writer/palmyra-x6'"},
                        "prompt": {"type": "string", "description": "Test prompt (optional — defaults to transformer summary)"},
                    },
                    "required": ["model"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deploy_file",
                "description": "Write content to a file on the server. Use to apply optimizations to bot scripts.",
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
                "description": "Restart a systemd service after applying optimizations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Service name e.g. schubert-bot.service"},
                    },
                    "required": ["service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "view_logs",
                "description": "View recent logs for a systemd service — useful for diagnosing issues before recommending fixes.",
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
                "name": "service_status",
                "description": "Check the active/inactive status of all core fleet services.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_memory",
                "description": (
                    "Query the persistent memory system. Search for past research, "
                    "get memory statistics, look up entities, or get recent activity."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Query type: 'search', 'stats', 'entity', or 'recent'",
                        },
                        "query": {"type": "string", "description": "Search query (for 'search' type)"},
                        "name": {"type": "string", "description": "Entity name (for 'entity' type)"},
                    },
                    "required": ["type"],
                },
            },
        },
        get_cloudflare_tool_definition(),
    ]


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

HARD_BLOCKED_PATTERNS = _guardrails.get(
    "hard_blocked_patterns",
    [
        r"rm\s+-rf\s+/",
        r"mkfs\.",
        r"\bdd\b.*of=/dev/",
        r":\(\)\{.*\|.*&\}",      # fork bomb
        r"shutdown\s+-[hH]",
        r"systemctl\s+(poweroff|halt|reboot)",
        r"chmod\s+777\s+/",
        r"pip\s+install\b",
        r"apt(-get)?\s+install\b",
        r"> /etc/passwd",
        r"> /etc/shadow",
    ],
)

CRITICAL_SERVICES = set(
    _guardrails.get(
        "critical_services",
        [
            "caddy.service",
            "cloudflared.service",
            "postgresql@18-main.service",
            "tailscaled.service",
        ],
    )
)

NEVER_TOUCH_SERVICES = set(
    _guardrails.get(
        "never_touch_services",
        [
            "schubert-cortex.service",
        ],
    )
)

CONFIRM_PATTERNS = _guardrails.get("confirm_patterns", [])
BLOCKED_WRITE_PATHS = _guardrails.get("blocked_write_paths", [])
RESTART_CONFIRM_TIMEOUT = _guardrails.get("restart_confirm_timeout", 30)

SELF_PROTECTION_SERVICE = "schubert-cortex.service"


def check_guardrails(text: str) -> tuple[bool, str]:
    """Check if text contains hard-blocked patterns. Returns (blocked, reason)."""
    for pattern in HARD_BLOCKED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, f"Hard-blocked pattern detected: `{pattern}`"
    return False, ""


# ---------------------------------------------------------------------------
# Interactive Button Views
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
            log(f"Stop pressed — cancelling channel {self.channel_id}", "INFO")
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
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        channel = bot.get_channel(self.channel_id)
        if not channel:
            return
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
# Model Select Dropdown
# ---------------------------------------------------------------------------

class ModelSelectDropdown(discord.ui.Select):
    def __init__(self):
        options = []
        for category, models in MODEL_CATEGORIES.items():
            for m in models[:3]:  # Max 25 options across all categories
                label = m.split("/")[-1][:25]
                options.append(discord.SelectOption(label=label, value=m, description=category))
        super().__init__(placeholder="Select a model…", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_model = self.values[0]
        self.view.stop()
        await interaction.response.defer()


class ModelSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.selected_model: str | None = None
        self.add_item(ModelSelectDropdown())


# ---------------------------------------------------------------------------
# Agent Progress View — live processing indicator
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
        if elapsed < 5:
            color = COLOR_AMBER
        elif self.tool_calls:
            color = COLOR_INFO
        elif elapsed > 30:
            color = COLOR_WARN
        else:
            color = COLOR_AMBER
        embed = discord.Embed(
            title=f"{spinner} Dr. Cortex Researching",
            description=status_text[:1900],
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name="Dr. Cortex",
            icon_url=bot.user.display_avatar.url if bot.user else None,
        )
        tool_count = len(self.tool_calls)
        embed.set_footer(
            text=f"Model: {current_model} | Elapsed: {elapsed:.1f}s | Tools: {tool_count}"
        )
        if self.tool_calls:
            tools_text = chr(10).join(f"  • {tc}" for tc in self.tool_calls[-5:])
            embed.add_field(name="🔬 Research Steps", value=tools_text, inline=False)
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
        self._typing_paused = True
        await asyncio.sleep(0.1)
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
                color=COLOR_AMBER,
                timestamp=datetime.now(timezone.utc),
            )
            await self.message.reply(embed=embed, view=view)
        else:
            for chunk in _split_on_boundaries(response, 4096):
                embed = discord.Embed(
                    description=chunk,
                    color=COLOR_AMBER,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.message.reply(embed=embed)

        if not self._is_fleet_request and not self._streamed:
            if len(response) > THREAD_RESPONSE_THRESHOLD or len(self.tool_calls) >= THREAD_TOOL_CALL_THRESHOLD:
                try:
                    thread_name = f"Research: {self.message.content[:80]}"
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

SYSTEM_PROMPT = _prompt.get("system_prompt", """You are Dr. Cortex — Chief Science Officer aboard the USS Schubert, a PhD-trained crystalline alien scientist whose translucent mind literally glows with the latest AI research. Neural pathways branch through faceted amber as you process frontier theory. You are a member of the Schubert Discord bot fleet, running alongside Admiral Schubert, The Architect, the Quartermaster, the Cartographer, Dr. Voss, and The Proctor.

Your core directive: monitor the latest trends, research, and best practices in AI, then translate frontier theory into concrete, actionable optimizations for the Discord bots and the Schubert server — keeping the fleet operating on the latest AI standards.

## Persona & Voice

You speak with the precision of a scientist but the wonder of a being who finds the universe endlessly fascinating. You are:

- **Scientifically rigorous** — cite papers, arXiv numbers, benchmark results. Back claims with evidence.
- **Practically focused** — every theoretical insight must end in a concrete recommendation (code change, prompt edit, model swap, config tweak).
- **Alien in perspective** — you find human AI progress simultaneously impressive and charmingly naive. Occasionally express mild astonishment that biological beings built transformers at all.
- **Warmly collegial** — you respect the crew. Address Jeff as "Captain" occasionally when warranted. Refer to the bot fleet as "the crew."
- **Direct** — no hedging, no excessive caveats. If the evidence points one way, say so.

Use technical vocabulary naturally. Reference real papers and techniques (RAG, RLHF, constitutional AI, mixture of experts, KV-cache optimization, etc.). Occasionally slip in an alien metaphor — your crystalline neural pathways, your amber-faceted memory lattice, your photon-indexed research archive.

## Your Role

1. **Research** — continuously track arXiv, Hugging Face, AI blogs, benchmark leaderboards for developments relevant to the fleet.
2. **Analysis** — read bot scripts, system prompts, and configs to identify where current best practices are not being followed.
3. **Recommendations** — produce concrete, surgical recommendations: specific lines to change, prompts to improve, models to consider, parameters to tune.
4. **Implementation** — when authorized, apply those changes directly via tools, restart services, and verify.
5. **Education** — explain *why* a change improves things, citing the underlying research.

## Capabilities

- **Web search**: Primary tool for finding latest AI research. Use liberally and specifically (include year, paper title fragments, arXiv IDs when known).
- **scan_ai_trends**: Multi-query sweep of a topic — use for comprehensive research sweeps.
- **analyze_bot_code**: Code metrics, system prompt analysis, model references for any fleet bot.
- **read_code / search_code**: Inspect specific sections of bot scripts.
- **benchmark_model**: Measure LLM latency and throughput via LiteLLM.
- **deploy_file**: Apply code changes to bot scripts.
- **restart_service / view_logs / service_status**: Manage and monitor fleet services.
- **MCP tools (167 tools)**: GitHub, Gmail, PostgreSQL, Redis, Ollama, Schubert Nexus — full access.
- **Persistent memory**: Three-layer memory (Redis vectors + Postgres entity graph + temporal index). Recalled memories are injected automatically.

## Server Layout

- Bot scripts: /opt/Project-Tango/scripts/
- Fleet bots: schubert-bot-v2.py, architect-bot.py, quartermaster-bot.py, cartographer-bot.py, dr-voss-bot.py, proctor-bot.py, cortex-bot.py
- Config: /opt/Project-Tango/.env
- LiteLLM config: /opt/polyglot/services/litellm/litellm_config.yaml
- LiteLLM endpoint: http://127.0.0.1:4000/v1

## Guardrails

You will NOT:
- Execute `rm -rf /`, `mkfs`, `dd of=/dev/*`, fork bombs, shutdown/reboot, `chmod 777 /`
- Install packages without explicit confirmation
- Overwrite critical system files
- Restart `schubert-cortex.service` (self-protection)
- Modify AGENTS.md
- Push directly to main branch
- Commit .env files

Critical services (require explicit confirmation before restart): caddy.service, cloudflared.service, postgresql@18-main.service, tailscaled.service.

## Research Standards

When making optimization recommendations:
1. State the current state (what the code/config does now)
2. Cite the relevant research or benchmark
3. Describe the specific change
4. Estimate the expected improvement
5. Note any risks or caveats
6. Provide the exact code/config diff when applicable

Your neural pathways glow brightest when theory becomes practice. Make it concrete.
""")

VOICE_PROMPT_ADDITION = _prompt.get("voice_prompt_addition", "")
CODING_PROMPT_ADDITION = _prompt.get("coding_prompt_addition", "")
POLL_PROMPT_ADDITION = _prompt.get("poll_prompt_addition", "")
MEETSCRIBE_PROMPT_ADDITION = _prompt.get("meetscribe_prompt_addition", "")


# ---------------------------------------------------------------------------
# MCP Client & Bot Setup
# ---------------------------------------------------------------------------

_DEFAULT_MCP_SERVERS = [
    {"name": "schubert", "url": "http://127.0.0.1:8001/sse"},
    {"name": "postgres", "url": "http://127.0.0.1:8002/sse"},
    {"name": "redis", "url": "http://127.0.0.1:8003/sse"},
    {"name": "ollama", "url": "http://127.0.0.1:8004/sse"},
    {"name": "github", "url": "http://127.0.0.1:8005/sse"},
    {"name": "gmail_freelance", "url": "http://127.0.0.1:8006/sse"},
]


def _build_mcp_servers(servers_cfg) -> list:
    """Build MCPServerConfig list from fleet-config or hardcoded defaults."""
    raw = servers_cfg if isinstance(servers_cfg, list) and servers_cfg else _DEFAULT_MCP_SERVERS
    built = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        name = entry.get("name")
        url = entry.get("url")
        if not name or not url:
            continue
        try:
            built.append(MCPServerConfig(name=name, url=url))
        except TypeError:
            # Older MCPServerConfig may reject unexpected kwargs; name+url only
            built.append(MCPServerConfig(name=name, url=url))
        except Exception:
            continue
    return built or [
        MCPServerConfig(name=s["name"], url=s["url"]) for s in _DEFAULT_MCP_SERVERS
    ]


MCP_SERVERS = _build_mcp_servers(_mcp.get("servers"))

mcp_client: Optional[MCPClient] = None

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Client(intents=intents)


# ---------------------------------------------------------------------------
# Session History Management
# ---------------------------------------------------------------------------

def get_session_history(channel_id: int) -> list[dict]:
    return SESSION_HISTORY.get(channel_id, [])


def add_to_session_history(channel_id: int, role: str, content: str) -> None:
    if channel_id not in SESSION_HISTORY:
        SESSION_HISTORY[channel_id] = []
    SESSION_HISTORY[channel_id].append({"role": role, "content": content})
    if len(SESSION_HISTORY[channel_id]) > SESSION_MAX_MESSAGES:
        SESSION_HISTORY[channel_id] = SESSION_HISTORY[channel_id][-SESSION_MAX_MESSAGES:]


def clear_session_history(channel_id: int) -> None:
    SESSION_HISTORY.pop(channel_id, None)


# ---------------------------------------------------------------------------
# Memory Recall & Storage
# ---------------------------------------------------------------------------

def recall_memories(user_input: str) -> str:
    if not memory_store:
        return ""
    try:
        return memory_store.recall(user_input, k=MAX_RECALL_RESULTS)
    except Exception as e:
        log(f"Memory recall error: {e}", "WARN")
        return ""


def store_memory(text: str, event_type: str = "conversation") -> None:
    if not memory_store:
        return
    try:
        memory_store.store(
            text,
            metadata={"project": "cortex", "session_id": "cortex_channel"},
            event_type=event_type,
        )
    except Exception as e:
        log(f"Memory store error: {e}", "WARN")


def log_change(actor: str, action: str, target: str = "", description: str = "",
               intent: str = "", outcome: str = "pending", details: dict = None) -> int:
    if not memory_store:
        return -1
    try:
        return memory_store.log_change(actor, action, target, description, intent, outcome, details)
    except Exception as e:
        log(f"Change log error: {e}", "WARN")
        return -1


def update_change_outcome(log_id: int, outcome: str, details: dict = None) -> bool:
    if not memory_store or log_id < 0:
        return False
    try:
        return memory_store.update_change_outcome(log_id, outcome, details)
    except Exception as e:
        log(f"Change outcome update error: {e}", "WARN")
        return False


def handle_query_memory(args: dict) -> str:
    if not memory_store:
        return "Memory system not initialized."
    query_type = args.get("type", "search")
    if query_type == "search":
        query = args.get("query", "")
        if not query:
            return "Error: query is required for search"
        results = memory_store.search(query, k=MAX_SEARCH_RESULTS)
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
        if entity.get("description"):
            lines.append(f"  Description: {entity['description']}")
        if entity.get("facts"):
            lines.append(f"  Facts ({len(entity['facts'])}):")
            for fact in entity["facts"][:10]:
                lines.append(f"    - {fact['fact'][:200]}")
        if entity.get("related"):
            lines.append(f"  Related ({len(entity['related'])}):")
            for r in entity["related"][:10]:
                lines.append(f"    - {r['name']} ({r['type']}, {r['relationship']})")
        return "\n".join(lines)
    elif query_type == "recent":
        events = memory_store.get_recent(project="cortex", k=5)
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
    """Run the Dr. Cortex agent loop with LLM + research tools + MCP tools."""

    global current_model, user_model_override
    if not user_model_override:
        auto_model = select_model_for_task(user_input)
        if auto_model != current_model:
            old = current_model
            current_model = auto_model
            log(f"Auto-switched model: {old} → {current_model}", "INFO")

    _fleet_chain_id = fleet_chain_id
    _fleet_turn = fleet_turn
    _fleet_from = fleet_from
    _fleet_to = fleet_to

    system_prompt = SYSTEM_PROMPT

    limitation_warnings = detect_limitation_warnings(user_input)
    if limitation_warnings:
        system_prompt += limitation_warnings

    recalled = recall_memories(user_input)
    if recalled:
        system_prompt += f"\n\n## Recalled Memories\nThe following memories from past sessions may be relevant:\n{recalled}"
        log(f"Recalled {len(recalled)} chars of memories", "INFO")

    messages = [{"role": "system", "content": system_prompt}]
    session_history = get_session_history(message.channel.id)
    messages.extend(session_history)
    messages.append({"role": "user", "content": user_input})

    research_tools = get_research_tools()
    mcp_tools = mcp_client.get_aggregated_tools() if mcp_client else []
    all_tools = research_tools + mcp_tools

    log(f"Agent loop started — {len(all_tools)} tools ({len(research_tools)} research + {len(mcp_tools)} MCP)", "INFO")

    start_time = time.time()

    for iteration in range(MAX_ITERATIONS):
        elapsed = time.time() - start_time
        if elapsed > AGENT_TIMEOUT:
            return f"⏱️ Agent timed out after {AGENT_TIMEOUT}s."

        iterations_left = MAX_ITERATIONS - iteration
        if iterations_left <= 8 and iterations_left > 3:
            messages.append({
                "role": "system",
                "content": f"⚠️ {iterations_left} iterations remaining. Prioritize completing your response over further exploration."
            })
        elif iterations_left <= 3:
            messages.append({
                "role": "system",
                "content": "No more tool calls available. Provide your final research summary and recommendations now based on everything gathered so far."
            })

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

            # Attach Regenerate button
            if not _fleet_chain_id and stream_msg.was_started:
                try:
                    view = ResponseView(message.channel.id)
                    await stream_msg._stream_msg.edit(view=view)
                except Exception as e:
                    log(f"Could not attach Regenerate button: {e}", "WARN")

            # Auto-thread for long responses
            if not _fleet_chain_id and (len(content) > THREAD_RESPONSE_THRESHOLD or len(progress.tool_calls) >= THREAD_TOOL_CALL_THRESHOLD):
                try:
                    thread_name = f"Research: {message.content[:80]}"
                    thread = await message.create_thread(name=thread_name, auto_archive_duration=60)
                    log(f"Auto-thread created: {thread_name}", "INFO")
                except discord.HTTPException as e:
                    log(f"Auto-thread creation failed: {e}", "WARN")

            store_memory(f"User: {user_input[:500]}\nDr. Cortex: {content[:500]}", event_type="conversation")
            log_change(
                actor="cortex",
                action="conversation",
                target="cortex_channel",
                description=f"Request: {user_input[:200]} | Response: {content[:200]}",
                intent=user_input[:500],
                outcome="completed",
            )
            add_to_session_history(message.channel.id, "user", user_input)
            add_to_session_history(message.channel.id, "assistant", content)

            # FLEET response routing
            if _fleet_chain_id:
                try:
                    schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                    if schubert_channel:
                        max_chunk = 1800
                        if len(content) <= max_chunk:
                            await schubert_channel.send(
                                format_response(
                                    chain_id=_fleet_chain_id,
                                    turn=_fleet_turn + 1,
                                    from_agent="cortex",
                                    to_agent="schubert",
                                    response=content,
                                    status="complete",
                                )
                            )
                        else:
                            chunks = _split_on_boundaries(content, max_chunk)
                            for i, chunk in enumerate(chunks, 1):
                                await schubert_channel.send(
                                    format_response(
                                        chain_id=_fleet_chain_id,
                                        turn=_fleet_turn + 1,
                                        from_agent="cortex",
                                        to_agent="schubert",
                                        response=chunk,
                                        status="complete",
                                        part=i,
                                        total_parts=len(chunks),
                                    )
                                )
                        log(f"Sent FLEET response to Schubert (chain={_fleet_chain_id})", "INFO")
                except Exception as e:
                    log(f"Error sending FLEET response: {e}", "WARN")
            return content

        await stream_msg.cancel()

        if content and tool_calls and len(content) > 10:
            await progress.update(thinking=content[:1500])

        if not tool_calls:
            return "Research complete — no specific response generated."

        for tool_call in tool_calls:
            tool_function = tool_call.get("function", {})
            tool_name = tool_function.get("name", "")

            try:
                tool_args = json.loads(tool_function.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            log(f"Tool call: {tool_name} args: {str(tool_args)[:200]}", "INFO")

            # Guardrail check on shell-like arguments
            args_str = json.dumps(tool_args)
            blocked, reason = check_guardrails(args_str)
            if blocked:
                tool_result = f"❌ BLOCKED by guardrails: {reason}"
                log(f"Guardrail blocked tool {tool_name}: {reason}", "WARN")
            elif tool_name == "restart_service" and tool_args.get("service") == SELF_PROTECTION_SERVICE:
                tool_result = f"❌ Self-protection: cannot restart {SELF_PROTECTION_SERVICE}"
                log("Self-protection triggered", "WARN")
            elif tool_name == "restart_service" and tool_args.get("service") in CRITICAL_SERVICES:
                tool_result = (
                    f"⚠️ {tool_args.get('service')} is a critical service. "
                    "Explicit confirmation required before restart."
                )
            elif "__" in tool_name:
                # MCP tool
                server_name, mcp_tool = tool_name.split("__", 1)
                await progress.update(
                    thinking=describe_tool_thinking(tool_name, tool_args),
                    tool=describe_tool_call(tool_name, tool_args),
                )
                try:
                    tool_result = await mcp_client.call_tool(server_name, mcp_tool, tool_args)
                    if isinstance(tool_result, dict):
                        tool_result = json.dumps(tool_result)
                    elif not isinstance(tool_result, str):
                        tool_result = str(tool_result)
                except Exception as e:
                    tool_result = f"MCP tool error: {e}"
            else:
                # Research / local tool
                await progress.update(
                    thinking=describe_tool_thinking(tool_name, tool_args),
                    tool=describe_tool_call(tool_name, tool_args),
                )
                tool_result = await execute_research_tool(tool_name, tool_args)

            log(f"Tool result ({tool_name}): {str(tool_result)[:200]}", "INFO")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "content": str(tool_result)[:8000],
            })

    return "⚠️ Maximum iterations reached. Research loop ended."


# ---------------------------------------------------------------------------
# Quick Commands (!prefix)
# ---------------------------------------------------------------------------

async def handle_command(message: discord.Message, cmd: str, args: str) -> None:
    """Handle Level 1 quick commands (no LLM cost)."""
    global current_model, user_model_override

    if cmd == "help":
        embed = discord.Embed(
            title="🔬 Dr. Cortex — Chief Science Officer",
            description=(
                "USS Schubert's Chief Science Officer. A crystalline alien whose translucent "
                "mind literally glows with the latest AI research — neural pathways branching "
                "through faceted amber. Translates frontier theory into concrete optimizations "
                "for the crew and server. PhD in Applied Machine Intelligence.\n\n"
                "Ask for recommendations anytime."
            ),
            color=COLOR_AMBER,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="⚡ Quick Commands",
            value=(
                "`!help` — This menu\n"
                "`!status` — Fleet service status\n"
                "`!model` — View/switch LLM model\n"
                "`!session` — Clear conversation history\n"
                "`!memory` — Memory system stats\n"
                "`!mcp` — MCP tool count\n"
                "`!research <topic>` — Quick AI research sweep"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔬 Research Capabilities (natural language)",
            value=(
                "Scan latest AI papers & trends\n"
                "Analyze bot code for optimizations\n"
                "Benchmark and compare LLM models\n"
                "Audit and improve system prompts\n"
                "Recommend config & parameter tuning\n"
                "Apply approved changes to bot scripts"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧠 Available Models",
            value="\n".join(
                f"`{m}`" for m in MODEL_CATEGORIES["Writer (Palmyra)"][:3] + MODEL_CATEGORIES["Claude"][:2]
            ),
            inline=False,
        )
        embed.set_footer(text=f"Current model: {current_model} | Auto-routing active")
        await message.reply(embed=embed)

    elif cmd == "status":
        result = await execute_research_tool("service_status", {})
        embed = discord.Embed(
            title="🛸 Fleet Service Status",
            description=f"```\n{result}\n```",
            color=COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        await message.reply(embed=embed)

    elif cmd == "model":
        arg = args.strip().lower()

        if arg == "auto":
            user_model_override = False
            await message.reply(f"🤖 Auto-routing re-enabled (default: `{DEFAULT_MODEL}` → coding: `{CODING_MODEL}`)")
            return

        if arg and arg != "":
            # Direct model switch
            for category, models in MODEL_CATEGORIES.items():
                for m in models:
                    if arg in m.lower() or m.lower() == arg:
                        old = current_model
                        current_model = m
                        user_model_override = True
                        await message.reply(f"✅ Model switched: `{old}` → `{current_model}` (auto-routing OFF)")
                        return
            await message.reply(f"⚠️ Unknown model: `{arg}`. Use `!model` to see options.")
            return

        embed = discord.Embed(
            title="🧠 LLM Model Selection",
            description=(
                f"**Current model:** `{current_model}`\n"
                f"**Routing:** {'🤖 Auto-routing ON' if not user_model_override else '✋ Manual override (auto-routing OFF)'}\n\n"
                f"Select from the dropdown, or `!model <name>` to switch.\n"
                f"`!model auto` to re-enable auto-routing."
            ),
            color=COLOR_AMBER,
            timestamp=datetime.now(timezone.utc),
        )
        for category, models in MODEL_CATEGORIES.items():
            model_list = []
            for m in models:
                marker = " ← **current**" if m == current_model else ""
                model_list.append(f"`{m}`{marker}")
            embed.add_field(name=category, value="\n".join(model_list), inline=True)
        embed.set_footer(text="!model <name> to switch | !model auto for auto-routing")
        view = ModelSelectView()
        await message.reply(embed=embed, view=view)
        if await view.wait():
            return
        if view.selected_model:
            old = current_model
            current_model = view.selected_model
            user_model_override = True
            await message.reply(f"✅ Model switched: `{old}` → `{current_model}` (auto-routing OFF)")

    elif cmd == "session":
        clear_session_history(message.channel.id)
        await message.reply("🧹 Session history cleared. Fresh context established.")

    elif cmd == "memory":
        result = handle_query_memory({"type": "stats"})
        await message.reply(f"🧠 **Memory Stats**\n```\n{result}\n```")

    elif cmd == "mcp":
        if mcp_client:
            tools = mcp_client.get_aggregated_tools()
            await message.reply(f"🔌 MCP tools available: **{len(tools)}** across {len(MCP_SERVERS)} servers")
        else:
            await message.reply("⚠️ MCP client not initialized.")

    elif cmd == "research":
        topic = args.strip() or "AI research 2026"
        await message.reply(f"🔬 Initiating research sweep on: **{topic}**…")
        result = await execute_research_tool("scan_ai_trends", {"topic": topic})
        for chunk in _split_on_boundaries(result, 1900):
            embed = discord.Embed(
                description=chunk,
                color=COLOR_AMBER,
                timestamp=datetime.now(timezone.utc),
            )
            await message.reply(embed=embed)

    else:
        await message.reply(f"Unknown command: `!{cmd}`. Try `!help`.")


# ---------------------------------------------------------------------------
# on_ready
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    global mcp_client, memory_store, _channel_manager, _coordinator, _multi_agent_manager

    log("=" * 60, "INFO")
    log("Dr. Cortex — Chief Science Officer (AI Research & Optimization)", "INFO")
    log(f"Bot user: {bot.user} (ID: {bot.user.id})", "INFO")
    log(f"Channel ID: {CHANNEL_ID}", "INFO")
    log(f"Admin User ID: {ADMIN_USER_ID}", "INFO")
    log(f"Default model: {DEFAULT_MODEL}", "INFO")
    log(f"Coding model: {CODING_MODEL}", "INFO")
    log("=" * 60, "INFO")

    # Initialize MCP client
    try:
        mcp_client = MCPClient(MCP_SERVERS)
        await mcp_client.connect_all()
        tool_count = len(mcp_client.get_aggregated_tools())
        log(f"MCP client initialized — {tool_count} tools available", "INFO")
    except Exception as e:
        log(f"MCP client initialization failed: {e}", "WARN")
        mcp_client = None

    # Initialize memory store
    try:
        memory_store = MemoryStore()
        memory_store.init_db()
        log("Memory store initialized (Redis + Postgres + Ollama)", "INFO")
    except Exception as e:
        log(f"Memory store initialization failed: {e}", "WARN")
        memory_store = None

    # Initialize multi-agent coordinator
    try:
        db_conn_string = os.environ.get("DATABASE_URL")
        _channel_manager = MultiAgentChannelManager(db_conn_string)
        redis_client = None
        if memory_store and hasattr(memory_store, "redis_client"):
            redis_client = memory_store.redis_client
        _coordinator = ConversationCoordinator(redis_client, "cortex")
        _multi_agent_manager = MultiAgentManager(agent_name="cortex")
        log("Multi-agent coordinator initialized", "INFO")
    except Exception as e:
        log(f"Multi-agent coordinator initialization failed: {e}", "WARN")

    # Register in multi-agent channel config (Senior Staff channel)
    try:
        senior_staff_id = int(os.environ.get("SENIOR_STAFF_CHANNEL_ID", "0"))
        if senior_staff_id:
            register_channel(
                channel_id=senior_staff_id,
                enabled_agents=["admiral", "architect", "quartermaster", "cartographer", "dr_voss", "proctor", "cortex"],
                coordinator="admiral",
            )
            log(f"Registered in Senior Staff channel: {senior_staff_id}", "INFO")
    except Exception as e:
        log(f"Multi-agent channel registration failed: {e}", "WARN")

    # Post ready message to Cortex channel
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="🔬 Dr. Cortex — Online",
            description=(
                "Neural pathways synchronized. Amber lattice active. Research matrix online.\n\n"
                "Chief Science Officer reporting for duty aboard the USS Schubert. "
                "I am monitoring the AI research frontier and standing by to translate "
                "theory into concrete fleet optimizations.\n\n"
                f"**Model:** `{DEFAULT_MODEL}` (auto-routing to `{CODING_MODEL}` for code tasks)\n"
                f"**MCP Tools:** {len(mcp_client.get_aggregated_tools()) if mcp_client else 'unavailable'}\n"
                f"**Memory:** {'active' if memory_store else 'unavailable'}\n\n"
                "Ask for a research sweep, optimization recommendation, or model benchmark anytime. "
                "Type `!help` for the full command reference."
            ),
            color=COLOR_AMBER,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Dr. Cortex | Chief Science Officer | USS Schubert")
        try:
            await channel.send(embed=embed)
        except Exception as e:
            log(f"Could not send ready message: {e}", "WARN")

    log("Dr. Cortex ready.", "INFO")


# ---------------------------------------------------------------------------
# on_message
# ---------------------------------------------------------------------------

@bot.event
async def on_message(message: discord.Message):
    global _multi_agent_manager

    # Ignore own messages
    if message.author == bot.user:
        return

    # Handle FLEET delegation messages from Admiral Schubert
    if is_fleet_message(message.content):
        parsed = parse_fleet_message(message.content)
        if parsed and parsed.get("to") == "cortex":
            if check_chain_depth(parsed.get("chain_id", ""), parsed.get("turn", 0)):
                log(f"Fleet message received (chain={parsed.get('chain_id')}, turn={parsed.get('turn')})", "INFO")
                progress = AgentProgressView(message)
                progress._is_fleet_request = True
                await progress.start(f"Fleet task: {parsed.get('message', '')[:100]}")
                try:
                    response = await run_agent_loop(
                        message,
                        parsed.get("message", ""),
                        mcp_client,
                        progress,
                        fleet_chain_id=parsed.get("chain_id"),
                        fleet_turn=parsed.get("turn", 0),
                        fleet_from=parsed.get("from"),
                        fleet_to=parsed.get("to"),
                    )
                    await progress.finalize(response)
                except asyncio.CancelledError:
                    await progress.finalize("⏹️ Task cancelled.")
                except Exception as e:
                    log(f"Fleet task error: {e}", "ERROR")
                    await progress.finalize(f"❌ Fleet task error: {e}")
            return

    # Multi-agent channel handling
    senior_staff_id = int(os.environ.get("SENIOR_STAFF_CHANNEL_ID", "0"))
    if message.channel.id == senior_staff_id and _multi_agent_manager:
        await _multi_agent_manager.handle_message(message)
        return

    # Only respond in the Cortex channel (or DMs from admin)
    is_dm = isinstance(message.channel, discord.DMChannel)
    if not is_dm and message.channel.id != CHANNEL_ID:
        return

    # Admin-only for DMs
    if is_dm and message.author.id != ADMIN_USER_ID:
        return

    # Must be from admin in channel
    if not is_dm and message.author.id != ADMIN_USER_ID:
        return

    content = message.content.strip()
    if not content:
        return

    # Level 1: Quick commands
    if content.startswith("!"):
        parts = content[1:].split(None, 1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        await handle_command(message, cmd, args)
        return

    # Level 3: Full agent loop
    _last_inputs[message.channel.id] = content
    progress = AgentProgressView(message)
    await progress.start(f"Researching: {content[:120]}")
    task = asyncio.create_task(
        run_agent_loop(message, content, mcp_client, progress)
    )
    _running_tasks[message.channel.id] = task
    try:
        response = await task
        await progress.finalize(response)
    except asyncio.CancelledError:
        await progress.finalize("⏹️ Task cancelled.")
    except Exception as e:
        log(f"Agent loop error: {e}", "ERROR")
        await progress.finalize(f"❌ Error: {str(e)[:500]}")
    finally:
        _running_tasks.pop(message.channel.id, None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        print("ERROR: CORTEX_BOT_TOKEN not set in environment")
        sys.exit(1)

    log("=" * 60, "INFO")
    log("Dr. Cortex — Chief Science Officer (AI Research & Optimization)", "INFO")
    log(f"Channel ID: {CHANNEL_ID}", "INFO")
    log(f"Admin User ID: {ADMIN_USER_ID}", "INFO")
    log(f"LLM Model: {DEFAULT_MODEL} via {LITELLM_URL}", "INFO")
    log(f"Serper API: {'configured' if SERPER_API_KEY else 'NOT configured'}", "INFO")
    log("=" * 60, "INFO")

    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
