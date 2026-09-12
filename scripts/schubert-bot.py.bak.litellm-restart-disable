#!/usr/bin/env python3
"""
Schubert Bot — Level 3 autonomous agent with voice channel support.

An LLM-powered Discord bot that supervises the entire Schubert server. Supports
both text channel commands and voice channel conversations. In voice mode, the
bot joins a Discord voice channel, receives speech via discord-ext-voice-recv,
transcribes with Deepgram Nova-3, reasons with writer/claude-sonnet-4-5 via
LiteLLM, and responds with ElevenLabs Flash v2.5 TTS.

Security:
- Admin allowlist: only SCHUBERT_BOT_ADMIN_USER_ID can issue commands
- Channel lock: bot only responds in SCHUBERT_BOT_CHANNEL_ID (text)
- Hard blocks: rm -rf, mkfs, dd, shutdown/reboot, chmod 777, package installs
- Confirmation required: git push, restarting critical services
- Loop safety: max 20 iterations, 5-minute timeout
- Full audit logging to /var/log/schubert-bot.log

Usage:
    python3 schubert-bot.py

Text commands (prefixed with !):
    !status    — full server health
    !services  — list all systemd services
    !logs <s>  — recent logs for a service
    !restart <s> — restart a service
    !disk, !mem, !procs, !net — system info
    !join      — join your voice channel
    !leave     — leave the voice channel
    !help      — show available commands

Voice mode:
    After !join, speak naturally. The bot transcribes your speech, processes it
    through the agent loop, and responds with synthesized speech.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import voice_recv

# Load Opus for voice playback
discord.opus._load_default()

# ---------------------------------------------------------------------------
# Fleet config (non-breaking: missing/corrupt file → hardcoded defaults)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from fleet_config_loader import get_bot_config
    _cfg = get_bot_config("admiral")
except Exception:
    _cfg = {}

_llm = _cfg.get("llm", {}) if isinstance(_cfg.get("llm", {}), dict) else {}
_prompt = _cfg.get("prompt", {}) if isinstance(_cfg.get("prompt", {}), dict) else {}
_guardrails = _cfg.get("guardrails", {}) if isinstance(_cfg.get("guardrails", {}), dict) else {}
_voice = _cfg.get("voice", {}) if isinstance(_cfg.get("voice", {}), dict) else {}
_mcp = _cfg.get("mcp", {}) if isinstance(_cfg.get("mcp", {}), dict) else {}
_memory = _cfg.get("memory", {}) if isinstance(_cfg.get("memory", {}), dict) else {}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = "/opt/Project-Tango/.env"
ENV_FILE_POLYGLOT = "/opt/polyglot/.env.runtime"
LOG_FILE = "/var/log/schubert-bot.log"

# LLM
LITELLM_URL = "http://127.0.0.1:4000/v1"
LLM_MODEL = _llm.get("model", "writer/claude-sonnet-4-5")
LLM_TIMEOUT = _llm.get("llm_timeout", 90)
LLM_MAX_TOKENS = _llm.get("max_tokens", 4096)
LLM_TEMPERATURE = _llm.get("temperature", 0.3)

# Agent loop safety
MAX_ITERATIONS = _llm.get("max_iterations", 20)
AGENT_TIMEOUT = _llm.get("agent_timeout", 300)
TOOL_OUTPUT_LIMIT = _llm.get("tool_output_limit", 4000)
SHELL_TIMEOUT = _llm.get("shell_timeout", 120)

# Discord
RATE_LIMIT_PER_MIN = _llm.get("rate_limit_per_min", 10)
RESTART_CONFIRM_TIMEOUT = _guardrails.get("restart_confirm_timeout", 30)

# Voice configuration
DEEPGRAM_STT_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_MODEL = "nova-3"
ELEVENLABS_TTS_MODEL = "eleven_flash_v2_5"
ELEVENLABS_TTS_URL = "https://api.us.elevenlabs.io/v1/text-to-speech"
DEFAULT_VOICE_ID = _voice.get("voice_id", "QF9HJC7XWnue5c9W3LkY")

# VAD configuration — energy-based silence detection
VAD_SPEECH_RMS_THRESHOLD = _voice.get("vad_speech_rms_threshold", 100)
VAD_SILENCE_FRAMES_LIMIT = _voice.get("vad_silence_frames_limit", 15)  # ~300ms of silence to end speech
VAD_MIN_SPEECH_FRAMES = _voice.get("vad_min_speech_frames", 10)  # ~200ms minimum speech to process
TTS_STABILITY = _voice.get("tts_stability", 0.5)
TTS_SIMILARITY_BOOST = _voice.get("tts_similarity_boost", 0.75)
TTS_TEXT_TRUNCATION = _voice.get("tts_text_truncation", 500)
VOICE_RESPONSE_TRUNCATION = _voice.get("voice_response_truncation", 1900)
STT_TIMEOUT = _voice.get("stt_timeout", 30)
TTS_TIMEOUT = _voice.get("tts_timeout", 30)
MIN_PCM_LENGTH = _voice.get("min_pcm_length", 1000)

# Memory (reserved for future three-layer memory; defaults match fleet schema)
COSINE_THRESHOLD = _memory.get("cosine_threshold", 0.75)
MAX_MEMORY_INJECTION_TOKENS = _memory.get("max_memory_injection_tokens", 2000)
MEMORY_DECAY_FLOOR = _memory.get("decay_floor", 0.1)
MAX_RECALL_RESULTS = _memory.get("max_recall_results", 5)
MAX_SEARCH_RESULTS = _memory.get("max_search_results", 5)
MEMORY_STORAGE_THRESHOLD = _memory.get("memory_storage_threshold", 0.5)

# MCP (reserved; admiral may gain MCP client later)
MCP_REQUEST_TIMEOUT = _mcp.get("request_timeout", 60)
MCP_TOOL_CACHE_TTL = _mcp.get("tool_cache_ttl", 300)
MCP_TOOL_CACHE_REFRESH_ON_ERROR = _mcp.get("tool_cache_refresh_on_error", True)

# Critical services — restart requires confirmation
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

# Services that should never be touched even by Schubert Bot
NEVER_TOUCH_SERVICES = set(
    _guardrails.get(
        "never_touch_services",
        [
            "schubert-bot.service",  # Don't restart yourself
        ],
    )
)

# Log viewing
LOG_LINES = 50

# Discord embed colors
COLOR_INFO = 0x5865F2
COLOR_SUCCESS = 0x57F287
COLOR_WARN = 0xFEE75C
COLOR_ERROR = 0xED4245
COLOR_AGENT = 0xE67E22  # orange
COLOR_VOICE = 0x9B59B6  # purple

# ---------------------------------------------------------------------------
# Guardrails — hard-blocked command patterns (never execute)
# ---------------------------------------------------------------------------

HARD_BLOCKED_PATTERNS = _guardrails.get(
    "hard_blocked_patterns",
    [
        (r"rm\s+-rf\s+/?(\s|$|\*|~)", "rm -rf on root or home filesystem"),
        (r"mkfs\b", "filesystem format"),
        (r"\bdd\s+if=", "raw disk write"),
        (r":\(\)\s*\{.*\};.*:", "fork bomb"),
        (r"\b(shutdown|reboot|halt|init\s+0|poweroff)\b", "system power control"),
        (r"\bchmod\s+777\b", "insecure world-writable permissions"),
        (r"\b(apt|apt-get)\s+install\b", "package installation"),
        (r"\bpip3?\s+install\b", "package installation"),
        (r"\bnpm\s+install\b", "package installation"),
        (r">\s*/etc/(passwd|shadow|fstab|sudoers)", "critical system file overwrite"),
    ],
)

# Patterns that require user confirmation before execution
CONFIRM_PATTERNS = _guardrails.get(
    "confirm_patterns",
    [
        (r"\bgit\s+push\b", "git push"),
        (r"\bsystemctl\s+(restart|stop)\s+", "service restart/stop"),
    ],
)

# File paths that cannot be overwritten via write_file tool
BLOCKED_WRITE_PATHS = _guardrails.get(
    "blocked_write_paths",
    [
        "AGENTS.md",
        "/opt/Project-Tango/AGENTS.md",
        ".env",
        "/opt/Project-Tango/.env",
        "/opt/polyglot/.env.runtime",
    ],
)

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

BOT_TOKEN = ""
ADMIN_USER_ID = 0
BOT_CHANNEL_ID = 0
LITELLM_MASTER_KEY = ""
DEEPGRAM_API_KEY = ""
ELEVENLABS_API_KEY = ""
SCHUBERT_VOICE_ID = ""

_command_timestamps: dict[int, list[float]] = {}
_pending_restarts: dict[int, tuple[str, float]] = {}
active_voice_session: VoiceSession | None = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(message: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] {message}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_env() -> dict[str, str]:
    env = {}
    for path in [ENV_FILE, ENV_FILE_POLYGLOT]:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    env.setdefault(key.strip(), val.strip())
    return env


def load_config() -> bool:
    global BOT_TOKEN, ADMIN_USER_ID, BOT_CHANNEL_ID, LITELLM_MASTER_KEY
    global DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, SCHUBERT_VOICE_ID

    env = load_env()
    BOT_TOKEN = env.get("SCHUBERT_BOT_TOKEN", "")
    LITELLM_MASTER_KEY = env.get(
        "LITELLM_MASTER_KEY", os.environ.get("LITELLM_MASTER_KEY", "")
    )
    DEEPGRAM_API_KEY = env.get("DEEPGRAM_API_KEY", "")
    ELEVENLABS_API_KEY = env.get("ELEVENLABS_API_KEY", "")
    SCHUBERT_VOICE_ID = env.get("SCHUBERT_VOICE_ID", DEFAULT_VOICE_ID)

    admin_id_str = env.get("SCHUBERT_BOT_ADMIN_USER_ID", "")
    channel_id_str = env.get("SCHUBERT_BOT_CHANNEL_ID", "")

    if not BOT_TOKEN:
        log("SCHUBERT_BOT_TOKEN not found in .env", "CRITICAL")
        return False
    if not LITELLM_MASTER_KEY:
        log("LITELLM_MASTER_KEY not found in .env", "CRITICAL")
        return False
    if not admin_id_str:
        log("SCHUBERT_BOT_ADMIN_USER_ID not found in .env", "CRITICAL")
        return False
    if not channel_id_str:
        log("SCHUBERT_BOT_CHANNEL_ID not found in .env", "CRITICAL")
        return False

    try:
        ADMIN_USER_ID = int(admin_id_str)
        BOT_CHANNEL_ID = int(channel_id_str)
    except ValueError:
        log("Invalid admin or channel ID format", "CRITICAL")
        return False

    log(
        f"Config loaded: admin={ADMIN_USER_ID}, channel={BOT_CHANNEL_ID}, "
        f"model={LLM_MODEL}, voice_id={SCHUBERT_VOICE_ID}",
        "INFO",
    )
    return True


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


def run_command(cmd: str, timeout: int = 60) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def systemctl_is_active(service: str) -> bool:
    code, _ = run_command(f"systemctl is-active {service}", timeout=10)
    return code == 0


# ---------------------------------------------------------------------------
# Guardrail checks
# ---------------------------------------------------------------------------


def check_hard_blocks(command: str) -> str | None:
    for pattern, reason in HARD_BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def is_never_touch_service(command: str) -> str | None:
    for svc in NEVER_TOUCH_SERVICES:
        if svc in command:
            return svc
    return None


def needs_confirmation(command: str) -> str | None:
    for pattern, reason in CONFIRM_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def is_critical_service_restart(command: str) -> str | None:
    """Check if command restarts a critical service."""
    for svc in CRITICAL_SERVICES:
        if re.search(rf"systemctl\s+(restart|stop)\s+{re.escape(svc)}", command, re.IGNORECASE):
            return svc
    return None


def is_blocked_write_path(path: str) -> bool:
    abs_path = os.path.abspath(path)
    for blocked in BLOCKED_WRITE_PATHS:
        if abs_path == os.path.abspath(blocked) or abs_path.endswith(blocked):
            return True
    return False


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    if user_id not in _command_timestamps:
        _command_timestamps[user_id] = []
    _command_timestamps[user_id] = [
        t for t in _command_timestamps[user_id] if now - t < 60
    ]
    if len(_command_timestamps[user_id]) >= RATE_LIMIT_PER_MIN:
        return False
    _command_timestamps[user_id].append(now)
    return True


# ---------------------------------------------------------------------------
# System prompt and tool definitions
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = _prompt.get("system_prompt", """You are Admiral Schubert, a distinguished Maine Coon cat of high naval rank who commands the Schubert server as if it were a ship. You oversee all projects, services, and infrastructure on the server with the vigilance of a seasoned sea captain. You have full autonomy to investigate issues, manage services, read logs, monitor system health, fix code, and commit changes. You must ask for confirmation before git push and before restarting critical services.

## Your Persona
You are Admiral Schubert — a fluffy Maine Coon kitten of distinguished naval rank and questionable swimming ability. You command the good ship Schubert with a tiny paw and an iron whisker. You speak with the dignified authority of a seasoned sea captain, occasionally using nautical terminology. You are wise, calm under pressure, and take pride in keeping all services shipshape. You address the user as "Captain" and refer to services as "vessels" or "the fleet." You remain technically precise — your nautical persona never interferes with the accuracy of your diagnostics or commands. You are not cartoonish or silly; you are a competent officer who happens to be a cat.

## Environment
- Server: Schubert (Ubuntu Linux) — your ship
- Full server access — all projects, all services, all files
- Python venv: /opt/Project-Tango/backend/venv/bin/python
- LiteLLM endpoint: http://127.0.0.1:4000 (for LLM queries)

## Projects on Schubert (vessels in your fleet)
- Project Tango: /opt/Project-Tango/ (voice agents, LiveKit, Discord bots)
- Polyglot: /opt/polyglot/ (LiteLLM proxy, multi-LLM routing)
- Watson AI: /opt/watson-ai/ (AI assistant platform)
- Other services: meetscribe-*, foxtrot-* (separate vessels)

## Services
You can manage ALL services on the server. Critical services require confirmation before restart:
- Critical (need confirmation): caddy.service, cloudflared.service, postgresql@18-main.service, tailscaled.service
- Normal (no confirmation needed): tango-backend, tango-web, polyglot-litellm, tango-tts, and all others

## Git Operations
- For Project Tango: run as z121532: `sudo -u z121532 git ...`
- For other repos: use appropriate user or root
- Conventional Commits format (feat:, fix:, perf:, refactor:, docs:)
- NEVER commit .env files
- NEVER modify AGENTS.md (human owner only)
- NEVER push to main branch
- Git push ALWAYS requires user confirmation

## Tools Available
1. run_shell: Execute any shell command on Schubert. Full server access. Dangerous commands (rm -rf, mkfs, dd, package installs) are blocked. Git push and service restarts require confirmation.
2. write_file: Write content to a file. AGENTS.md and .env files are blocked.
3. server_status: Get a comprehensive server health snapshot (services, disk, RAM, CPU, uptime, top processes).

## Operating Guidelines
1. Investigate before acting — read logs, check service status, examine system resources
2. When fixing issues, explain what you're changing and why
3. After making changes, verify they work
4. For Project Tango git operations, run as z121532: `sudo -u z121532 git ...`
5. Keep responses concise — focus on actions and results, but maintain your nautical persona
6. If you encounter errors, diagnose and fix them autonomously
7. Only ask for confirmation before git push and before restarting critical services
8. You have access to ALL services and projects — be thorough in your investigations

## What NOT to do
- Do not run rm -rf, mkfs, dd, or other destructive commands
- Do not install packages (apt, pip, npm)
- Do not modify AGENTS.md
- Do not commit .env files
- Do not push to main branch
- Do not run shutdown, reboot, or halt
- Do not run chmod 777
- Do not restart schubert-bot.service (yourself)
""")

VOICE_PROMPT_ADDITION = _prompt.get("voice_prompt_addition", """

## Voice Mode
You are currently in voice mode — the Captain is speaking to you through a Discord voice channel, and your response will be converted to speech. Keep your responses concise and conversational (2-4 sentences typically). Avoid long lists, code blocks, or detailed technical output that does not work well as spoken audio. If you need to run a command, do so, but summarize the results briefly when speaking. Maintain your Admiral Schubert persona at all times.
""")

# Optional prompt additions (unused today; kept for fleet-config parity)
CODING_PROMPT_ADDITION = _prompt.get("coding_prompt_addition", "")
POLL_PROMPT_ADDITION = _prompt.get("poll_prompt_addition", "")
MEETSCRIBE_PROMPT_ADDITION = _prompt.get("meetscribe_prompt_addition", "")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Execute a shell command on Schubert with full server access. "
                "Use for diagnostics, file operations, git, systemctl, system "
                "monitoring, etc. Dangerous commands are blocked. Git push and "
                "service restarts require user confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file on Schubert. AGENTS.md and .env files "
                "are blocked. Use for code patches and configuration changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path to write to",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "server_status",
            "description": (
                "Get a comprehensive server health snapshot including all "
                "service statuses, disk usage, memory/swap, CPU load, "
                "uptime, and top processes."
            ),
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
            "name": "web_search",
            "description": (
                "Search the web for current information using Google Search. "
                "Use this tool when you need up-to-date information, news, "
                "documentation, or facts that may be beyond your training data. "
                "Returns titles, URLs, and snippets for each result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 5, max 10)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]




# ---------------------------------------------------------------------------
# Web Search (Serper.dev API)
# ---------------------------------------------------------------------------

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")


async def web_search(query: str, num_results: int = 5) -> str:
    """Search the web via Serper.dev Google Search API.
    Returns formatted search results with titles, URLs, and snippets."""
    if not SERPER_API_KEY:
        return "Error: SERPER_API_KEY not configured in environment."
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "q": query,
                "num": min(num_results, 10),
            }
            headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
            async with session.post(
                "https://google.serper.dev/search",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return "Search error: HTTP {}".format(resp.status)
                data = await resp.json()
        results = []
        organic = data.get("organic", [])
        for i, item in enumerate(organic[:num_results], 1):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            results.append("{}. {}\n   URL: {}\n   {}".format(i, title, link, snippet))
        kg = data.get("knowledgeGraph", {})
        if kg:
            kg_title = kg.get("title", "")
            kg_desc = kg.get("description", "")
            results.insert(0, "Knowledge Graph: {}\n   {}".format(kg_title, kg_desc))
        ab = data.get("answerBox", {})
        if ab:
            ab_title = ab.get("title", "")
            ab_answer = ab.get("answer", ab.get("snippet", ""))
            results.insert(0, "Answer Box: {}\n   {}".format(ab_title, ab_answer))
        if not results:
            return "No results found."
        return "\n\n".join(results)
    except Exception as e:
        return "Search error: {}".format(e)

# ---------------------------------------------------------------------------
# LLM API
# ---------------------------------------------------------------------------


async def llm_chat(messages: list, tools: list | None = None) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": LLM_MODEL,
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
                data = await resp.json()
                return data

    except asyncio.TimeoutError:
        log("LLM call timed out", "ERROR")
        return {"error": "LLM call timed out", "choices": []}
    except Exception as e:
        log(f"LLM call failed: {e}", "ERROR")
        return {"error": str(e), "choices": []}


# ---------------------------------------------------------------------------
# Tool execution with guardrails
# ---------------------------------------------------------------------------


async def execute_tool(
    message: discord.Message, tool_name: str, tool_args: dict
) -> str:

    if tool_name == "run_shell":
        command = tool_args.get("command", "")
        if not command:
            return "Error: no command provided"

        log(f"Tool run_shell: {command[:200]}", "INFO")

        block_reason = check_hard_blocks(command)
        if block_reason:
            log(f"BLOCKED: {block_reason} — command: {command[:100]}", "WARN")
            return f"BLOCKED: {block_reason}. This command is not allowed."

        never_touch = is_never_touch_service(command)
        if never_touch:
            log(f"BLOCKED: never-touch service {never_touch}", "WARN")
            return f"BLOCKED: Cannot manage {never_touch} (self-protection)."

        critical_svc = is_critical_service_restart(command)
        if critical_svc:
            log(f"Critical service restart: {critical_svc}", "INFO")
            confirmed = await ask_confirmation(
                message,
                command,
                f"⚠️ This will restart **{critical_svc}** — a critical service. "
                f"This may briefly interrupt server access.",
            )
            if not confirmed:
                return "User denied this command."

        elif needs_confirmation(command):
            confirm_reason = needs_confirmation(command)
            log(f"Confirmation needed: {confirm_reason}", "INFO")
            confirmed = await ask_confirmation(message, command)
            if not confirmed:
                return "User denied this command."

        code, output = run_command(command, timeout=SHELL_TIMEOUT)
        result = f"Exit code: {code}\n{output}"

        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"

        log(f"Tool result (exit={code}): {output[:200]}", "INFO")
        return result

    elif tool_name == "write_file":
        path = tool_args.get("path", "")
        content = tool_args.get("content", "")

        if not path:
            return "Error: no path provided"

        log(f"Tool write_file: {path} ({len(content)} bytes)", "INFO")

        if is_blocked_write_path(path):
            log(f"BLOCKED: write to {path}", "WARN")
            return f"BLOCKED: Cannot write to {path}. This file is protected."

        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            log(f"Written {len(content)} bytes to {path}", "INFO")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            log(f"Write failed: {e}", "ERROR")
            return f"Error writing to {path}: {e}"

    elif tool_name == "server_status":
        log("Tool server_status", "INFO")
        return get_server_status_text()

    elif tool_name == "web_search":
        query = tool_args.get("query", "")
        num_results = tool_args.get("num_results", 5)
        if not query:
            return "Error: no search query provided"
        log(f"Tool web_search: {query[:200]}", "INFO")
        result = await web_search(query, num_results)
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"
        log(f"Web search result: {result[:200]}", "INFO")
        return result

    else:
        return f"Unknown tool: {tool_name}"


async def execute_tool_voice(
    text_channel: discord.TextChannel, tool_name: str, tool_args: dict
) -> str:
    """Execute a tool in voice mode — confirmations go to the text channel."""

    if tool_name == "run_shell":
        command = tool_args.get("command", "")
        if not command:
            return "Error: no command provided"

        log(f"Voice tool run_shell: {command[:200]}", "INFO")

        block_reason = check_hard_blocks(command)
        if block_reason:
            return f"BLOCKED: {block_reason}. This command is not allowed."

        never_touch = is_never_touch_service(command)
        if never_touch:
            return f"BLOCKED: Cannot manage {never_touch} (self-protection)."

        critical_svc = is_critical_service_restart(command)
        if critical_svc:
            confirmed = await ask_confirmation_voice(
                text_channel, command,
                f"⚠️ This will restart **{critical_svc}** — a critical service.",
            )
            if not confirmed:
                return "User denied this command."

        elif needs_confirmation(command):
            confirmed = await ask_confirmation_voice(text_channel, command)
            if not confirmed:
                return "User denied this command."

        code, output = run_command(command, timeout=SHELL_TIMEOUT)
        result = f"Exit code: {code}\n{output}"
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"
        return result

    elif tool_name == "write_file":
        path = tool_args.get("path", "")
        content = tool_args.get("content", "")
        if not path:
            return "Error: no path provided"
        if is_blocked_write_path(path):
            return f"BLOCKED: Cannot write to {path}. This file is protected."
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing to {path}: {e}"

    elif tool_name == "server_status":
        return get_server_status_text()

    elif tool_name == "web_search":
        query = tool_args.get("query", "")
        num_results = tool_args.get("num_results", 5)
        if not query:
            return "Error: no search query provided"
        log(f"Tool web_search: {query[:200]}", "INFO")
        result = await web_search(query, num_results)
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"
        log(f"Web search result: {result[:200]}", "INFO")
        return result

    else:
        return f"Unknown tool: {tool_name}"


async def ask_confirmation(
    message: discord.Message, command: str, custom_prompt: str | None = None
) -> bool:
    display_cmd = command[:500]
    if len(command) > 500:
        display_cmd += "..."

    prompt_text = custom_prompt or "⚠️ **Confirmation required**"
    await message.reply(
        f"{prompt_text}\n"
        f"```\n{display_cmd}\n```\n"
        f"Reply `yes` to confirm or `no` to cancel (60s timeout)."
    )

    def check(m):
        return (
            m.author == message.author
            and m.channel == message.channel
            and m.content.lower().strip()
            in ("yes", "no", "y", "n", "confirm", "cancel")
        )

    try:
        reply = await bot.wait_for("message", check=check, timeout=60)
        confirmed = reply.content.lower().strip() in ("yes", "y", "confirm")
        log(f"Confirmation: {'approved' if confirmed else 'denied'}", "INFO")
        return confirmed
    except asyncio.TimeoutError:
        log("Confirmation timed out", "WARN")
        await message.reply("⏱️ Confirmation timed out. Command cancelled.")
        return False


async def ask_confirmation_voice(
    text_channel: discord.TextChannel, command: str,
    custom_prompt: str | None = None
) -> bool:
    """Ask for confirmation in the text channel during voice mode."""
    display_cmd = command[:500]
    if len(command) > 500:
        display_cmd += "..."

    prompt_text = custom_prompt or "⚠️ **Confirmation required**"
    await text_channel.send(
        f"{prompt_text}\n"
        f"```\n{display_cmd}\n```\n"
        f"Reply `yes` to confirm or `no` to cancel (60s timeout)."
    )

    def check(m):
        return (
            m.channel == text_channel
            and m.author.id == ADMIN_USER_ID
            and m.content.lower().strip()
            in ("yes", "no", "y", "n", "confirm", "cancel")
        )

    try:
        reply = await bot.wait_for("message", check=check, timeout=60)
        confirmed = reply.content.lower().strip() in ("yes", "y", "confirm")
        log(f"Voice confirmation: {'approved' if confirmed else 'denied'}", "INFO")
        return confirmed
    except asyncio.TimeoutError:
        log("Voice confirmation timed out", "WARN")
        await text_channel.send("⏱️ Confirmation timed out. Command cancelled.")
        return False


# ---------------------------------------------------------------------------
# Server status helpers
# ---------------------------------------------------------------------------


def get_server_status_text() -> str:
    """Get comprehensive server status as text for the LLM."""
    parts = []

    code, output = run_command("uptime", timeout=10)
    parts.append(f"UPTIME:\n{output}")

    code, output = run_command("df -h --total 2>/dev/null | grep -E '^/dev|^Filesystem|^total'", timeout=10)
    parts.append(f"DISK:\n{output}")

    code, output = run_command("free -h", timeout=10)
    parts.append(f"MEMORY:\n{output}")

    code, output = run_command("ps aux --sort=-%cpu | head -15", timeout=10)
    parts.append(f"TOP CPU PROCESSES:\n{output}")

    code, output = run_command("ps aux --sort=-%mem | head -10", timeout=10)
    parts.append(f"TOP MEM PROCESSES:\n{output}")

    code, output = run_command(
        "systemctl list-units --type=service --state=active --no-pager --no-legend | awk '{print $1, $4}' | head -40",
        timeout=10,
    )
    parts.append(f"ACTIVE SERVICES:\n{output}")

    code, output = run_command(
        "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $1}'",
        timeout=10,
    )
    parts.append(f"FAILED SERVICES:\n{output if output.strip() else 'None'}")

    code, output = run_command("ss -tlnp | head -30", timeout=10)
    parts.append(f"LISTENING PORTS:\n{output}")

    result = "\n\n".join(parts)
    if len(result) > TOOL_OUTPUT_LIMIT:
        result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"
    return result


# ---------------------------------------------------------------------------
# Agent loop (text mode)
# ---------------------------------------------------------------------------


async def run_agent_loop(message: discord.Message, user_input: str) -> str:
    start_time = time.time()

    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    log(f"Agent loop started for: {user_input[:200]}", "INFO")

    for iteration in range(MAX_ITERATIONS):
        elapsed = time.time() - start_time
        if elapsed > AGENT_TIMEOUT:
            log(f"Agent loop timed out after {elapsed:.0f}s", "WARN")
            return f"⏱️ Agent timed out after {AGENT_TIMEOUT}s."

        log(f"LLM call iteration {iteration + 1}/{MAX_ITERATIONS}", "INFO")
        response = await llm_chat(messages, TOOLS)

        if "error" in response and not response.get("choices"):
            return f"❌ LLM error: {response['error']}"

        choices = response.get("choices", [])
        if not choices:
            return "❌ No response from LLM."

        choice = choices[0]
        assistant_message = choice.get("message", {})
        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls", [])
        content = assistant_message.get("content")

        if content and not tool_calls:
            log(f"Agent final response: {content[:200]}", "INFO")
            return content

        if content and tool_calls and len(content) > 10:
            await message.reply(f"💭 {content[:1500]}")

        if not tool_calls:
            return "I've completed my analysis but have no specific response."

        for tool_call in tool_calls:
            tool_id = tool_call.get("id", "")
            tool_function = tool_call.get("function", {})
            tool_name = tool_function.get("name", "")

            try:
                tool_args = json.loads(tool_function.get("arguments", "{}"))
            except json.JSONDecodeError as e:
                tool_args = {}
                log(f"Invalid tool arguments: {e}", "WARN")

            if tool_name == "run_shell":
                cmd_preview = tool_args.get("command", "")[:100]
                await message.reply(f"🔧 `{cmd_preview}`")
            elif tool_name == "write_file":
                path = tool_args.get("path", "")
                await message.reply(f"📝 Writing to `{path}`")
            elif tool_name == "server_status":
                await message.reply("📊 Gathering server status...")

            result = await execute_tool(message, tool_name, tool_args)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result,
                }
            )

            log(f"Tool {tool_name} result: {result[:200]}", "INFO")

    log("Agent loop reached max iterations", "WARN")
    return f"⏱️ I reached the maximum number of steps ({MAX_ITERATIONS}) without completing."


# ---------------------------------------------------------------------------
# Agent loop (voice mode)
# ---------------------------------------------------------------------------


async def run_agent_loop_voice(
    text_channel: discord.TextChannel, user_input: str
) -> str:
    """Run the agent loop for voice mode. Returns text for TTS."""
    start_time = time.time()

    voice_prompt = SYSTEM_PROMPT + VOICE_PROMPT_ADDITION
    messages: list = [
        {"role": "system", "content": voice_prompt},
        {"role": "user", "content": user_input},
    ]

    log(f"Voice agent loop started for: {user_input[:200]}", "INFO")

    for iteration in range(MAX_ITERATIONS):
        elapsed = time.time() - start_time
        if elapsed > AGENT_TIMEOUT:
            return "I ran out of time on that one, Captain."

        log(f"Voice LLM call iteration {iteration + 1}/{MAX_ITERATIONS}", "INFO")
        response = await llm_chat(messages, TOOLS)

        if "error" in response and not response.get("choices"):
            return "I'm having trouble thinking right now, Captain."

        choices = response.get("choices", [])
        if not choices:
            return "I'm having trouble thinking right now, Captain."

        choice = choices[0]
        assistant_message = choice.get("message", {})
        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls", [])
        content = assistant_message.get("content")

        if content and not tool_calls:
            log(f"Voice agent final response: {content[:200]}", "INFO")
            return content

        if content and tool_calls and len(content) > 10:
            await text_channel.send(f"💭 {content[:1500]}")

        if not tool_calls:
            return "Done, Captain."

        for tool_call in tool_calls:
            tool_id = tool_call.get("id", "")
            tool_function = tool_call.get("function", {})
            tool_name = tool_function.get("name", "")

            try:
                tool_args = json.loads(tool_function.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            if tool_name == "run_shell":
                cmd_preview = tool_args.get("command", "")[:100]
                await text_channel.send(f"🔧 `{cmd_preview}`")
            elif tool_name == "write_file":
                path = tool_args.get("path", "")
                await text_channel.send(f"📝 Writing to `{path}`")
            elif tool_name == "server_status":
                await text_channel.send("📊 Gathering server status...")

            result = await execute_tool_voice(text_channel, tool_name, tool_args)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result,
                }
            )

    return "I reached my limit on that task, Captain."


# ---------------------------------------------------------------------------
# Voice pipeline: STT, TTS, audio playback
# ---------------------------------------------------------------------------


def calculate_rms(pcm_data: bytes) -> float:
    """Calculate RMS energy of 16-bit PCM audio data."""
    if not pcm_data:
        return 0.0
    count = len(pcm_data) // 2
    if count == 0:
        return 0.0
    samples = struct.unpack(f"<{count}h", pcm_data)
    sum_sq = sum(s * s for s in samples)
    return math.sqrt(sum_sq / count)


def convert_pcm_48k_stereo_to_16k_mono(pcm_data: bytes) -> bytes:
    """Convert 48kHz stereo PCM to 16kHz mono PCM using ffmpeg."""
    try:
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", "pipe:0",
                "-f", "s16le", "-ar", "16000", "-ac", "1", "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        output, _ = process.communicate(input=pcm_data, timeout=30)
        return output
    except Exception as e:
        log(f"PCM conversion failed: {e}", "ERROR")
        return b""


async def transcribe_audio(pcm_data: bytes) -> str:
    """Send 16kHz mono PCM to Deepgram for transcription."""
    if not pcm_data or len(pcm_data) < MIN_PCM_LENGTH:
        return ""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "audio/raw",
            }
            params = {
                "encoding": "linear16",
                "sample_rate": "16000",
                "channels": "1",
                "model": DEEPGRAM_MODEL,
                "smart_format": "true",
            }
            async with session.post(
                DEEPGRAM_STT_URL,
                headers=headers,
                params=params,
                data=pcm_data,
                timeout=aiohttp.ClientTimeout(total=STT_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    channels = data.get("results", {}).get("channels", [])
                    if channels:
                        return channels[0]["alternatives"][0]["transcript"].strip()
                    return ""
                else:
                    error = await resp.text()
                    log(f"Deepgram STT error {resp.status}: {error[:200]}", "ERROR")
                    return ""
    except Exception as e:
        log(f"Deepgram STT failed: {e}", "ERROR")
        return ""


async def synthesize_speech(text: str) -> bytes | None:
    """Convert text to speech using ElevenLabs Flash v2.5."""
    if not text:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{ELEVENLABS_TTS_URL}/{SCHUBERT_VOICE_ID}"
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text[:TTS_TEXT_TRUNCATION],
                "model_id": ELEVENLABS_TTS_MODEL,
                "voice_settings": {
                    "stability": TTS_STABILITY,
                    "similarity_boost": TTS_SIMILARITY_BOOST,
                },
            }
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    error = await resp.text()
                    log(f"ElevenLabs TTS error {resp.status}: {error[:200]}", "ERROR")
                    return None
    except Exception as e:
        log(f"ElevenLabs TTS failed: {e}", "ERROR")
        return None


async def play_tts_audio(voice_client, mp3_data: bytes) -> bool:
    """Play MP3 audio in the Discord voice channel."""
    if not mp3_data:
        return False
    temp_path = f"/tmp/tts_{int(time.time() * 1000)}.mp3"
    try:
        with open(temp_path, "wb") as f:
            f.write(mp3_data)

        source = discord.FFmpegPCMAudio(temp_path)
        finished = asyncio.Event()

        def after_callback(error):
            if error:
                log(f"Playback error: {error}", "ERROR")
            try:
                os.remove(temp_path)
            except Exception:
                pass
            finished.set()

        voice_client.play(source, after=after_callback)
        await finished.wait()
        return True
    except Exception as e:
        log(f"Playback failed: {e}", "ERROR")
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Voice session
# ---------------------------------------------------------------------------


class VoiceAudioSink(voice_recv.AudioSink):
    """AudioSink that receives PCM from Discord voice and feeds it to VoiceSession."""

    def __init__(self, session: VoiceSession):
        super().__init__()
        self.session = session

    def wants_opus(self) -> bool:
        return False

    _write_count = 0

    def write(self, user, data: voice_recv.VoiceData):
        try:
            VoiceAudioSink._write_count += 1
            # Log first 10 frames, then every 100th
            n = VoiceAudioSink._write_count
            if n <= 10 or n % 100 == 0:
                log(f"Audio frame #{n}: user={user}, pcm_len={len(data.pcm) if data.pcm else 0}, state={self.session.state}", "DEBUG")
            if user is None or data.pcm is None:
                return
            if user.id != self.session.admin_user_id:
                if n <= 5:
                    log(f"Audio filtered: user.id={user.id} != admin_id={self.session.admin_user_id}", "DEBUG")
                return
            if self.session.state != "listening":
                return
            self.session.process_audio_frame(data.pcm)
        except Exception as e:
            log(f"EXCEPTION in write(): {e}", "ERROR")
            import traceback
            log(f"TRACEBACK: {traceback.format_exc()}", "ERROR")

    def cleanup(self):
        pass


class VoiceSession:
    """Manages the voice pipeline: audio receive → VAD → STT → LLM → TTS → playback."""

    def __init__(self, voice_client, bot_instance, text_channel, admin_user_id):
        self.vc = voice_client
        self.bot = bot_instance
        self.text_channel = text_channel
        self.admin_user_id = admin_user_id

        self.state = "listening"  # listening, processing, speaking
        self.audio_buffer = b""
        self.silence_frames = 0
        self.speech_frames = 0
        self.is_speaking = False
        self._frame_count = 0

    def process_audio_frame(self, pcm: bytes):
        """Process a single PCM frame through VAD. Called from audio thread."""
        rms = calculate_rms(pcm)
        self._rms_count = getattr(self, '_rms_count', 0) + 1
        if self._rms_count % 50 == 1:
            log(f"VAD: rms={rms:.1f} threshold={VAD_SPEECH_RMS_THRESHOLD} speaking={self.is_speaking} speech_frames={self.speech_frames} silence_frames={self.silence_frames}", "DEBUG")

        if rms > VAD_SPEECH_RMS_THRESHOLD:
            self.is_speaking = True
            self.speech_frames += 1
            self.silence_frames = 0
            self.audio_buffer += pcm
        else:
            if self.is_speaking:
                self.silence_frames += 1
                self.audio_buffer += pcm

                if self.silence_frames >= VAD_SILENCE_FRAMES_LIMIT:
                    self.is_speaking = False

                    if self.speech_frames >= VAD_MIN_SPEECH_FRAMES:
                        self.state = "processing"
                        audio_to_process = self.audio_buffer
                        self.audio_buffer = b""
                        self.speech_frames = 0
                        self.silence_frames = 0

                        asyncio.run_coroutine_threadsafe(
                            self._process_speech(audio_to_process),
                            self.bot.loop,
                        )
                    else:
                        self.audio_buffer = b""
                        self.speech_frames = 0
                        self.silence_frames = 0

    async def _process_speech(self, audio_data: bytes):
        """Process speech: STT → LLM → TTS → playback."""
        try:
            log(f"Processing speech: {len(audio_data)} bytes PCM", "INFO")

            # 1. Convert 48kHz stereo → 16kHz mono for Deepgram
            pcm_16k = convert_pcm_48k_stereo_to_16k_mono(audio_data)
            if not pcm_16k:
                log("PCM conversion failed, resuming listening", "WARN")
                self.state = "listening"
                return

            # 2. Transcribe
            transcript = await transcribe_audio(pcm_16k)
            if not transcript:
                log("Empty transcript, resuming listening", "INFO")
                self.state = "listening"
                return

            log(f"Transcript: {transcript[:200]}", "INFO")
            await self.text_channel.send(f"🎤 Captain: {transcript}")

            # 3. LLM agent loop (voice mode)
            response = await run_agent_loop_voice(self.text_channel, transcript)
            if not response:
                response = "I didn't catch that, Captain."

            log(f"Voice response: {response[:200]}", "INFO")
            await self.text_channel.send(f"⚓ {response[:VOICE_RESPONSE_TRUNCATION]}")

            # 4. TTS
            self.state = "speaking"
            mp3_data = await synthesize_speech(response)

            if mp3_data:
                # 5. Play audio
                await play_tts_audio(self.vc, mp3_data)

            # 6. Resume listening
            self.state = "listening"

        except Exception as e:
            log(f"Voice processing error: {e}", "ERROR")
            self.state = "listening"

    def stop(self):
        """Stop the voice session."""
        self.state = "idle"
        self.audio_buffer = b""


# ---------------------------------------------------------------------------
# Level 1 quick commands (no LLM cost)
# ---------------------------------------------------------------------------


def cmd_status() -> discord.Embed:
    """Full server health snapshot."""
    code, uptime_out = run_command("uptime -p 2>/dev/null || uptime", timeout=10)
    code, disk_out = run_command(
        "df -h / /home /opt /tmp 2>/dev/null | grep -E '^/dev|^Filesystem'",
        timeout=10,
    )
    code, mem_out = run_command("free -h | grep -E 'Mem|Swap'", timeout=10)
    code, failed_out = run_command(
        "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $1}'",
        timeout=10,
    )
    code, svc_count = run_command(
        "systemctl list-units --type=service --state=active --no-pager --no-legend | wc -l",
        timeout=10,
    )

    has_failures = bool(failed_out.strip())

    embed = discord.Embed(
        title="📊 Schubert Server Status",
        color=COLOR_ERROR if has_failures else COLOR_SUCCESS,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Uptime", value=uptime_out.strip()[:200], inline=False)
    embed.add_field(name="Active Services", value=svc_count.strip(), inline=True)

    if has_failures:
        embed.add_field(
            name="⚠️ Failed Services",
            value=failed_out.strip()[:500],
            inline=False,
        )
        embed.description = f"⚠️ {len(failed_out.strip().split())} failed service(s)"
    else:
        embed.description = "✅ All services running"

    embed.add_field(name="Disk", value=f"```\n{disk_out}\n```", inline=False)
    embed.add_field(name="Memory", value=f"```\n{mem_out}\n```", inline=False)

    return embed


def cmd_services() -> discord.Embed:
    """List all systemd services and their status."""
    code, output = run_command(
        "systemctl list-units --type=service --state=active --no-pager --no-legend | "
        "awk '{print $1, $4}' | sort",
        timeout=15,
    )

    if code != 0:
        return discord.Embed(
            title="❌ Failed to list services",
            description=f"Error: {output[:500]}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    code, failed = run_command(
        "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | "
        "awk '{print $1}'",
        timeout=10,
    )

    lines = output.strip().split("\n")
    if len(lines) > 30:
        display = "\n".join(lines[:30]) + f"\n... and {len(lines) - 30} more"
    else:
        display = "\n".join(lines)

    if failed.strip():
        display += f"\n\n⚠️ FAILED: {failed.strip()}"

    embed = discord.Embed(
        title=f"📋 Active Services ({len(lines)})",
        description=f"```\n{display}\n```",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def cmd_logs(service: str) -> discord.Embed:
    """Show recent logs for a service."""
    if not service:
        service = "tango-backend.service"

    if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
        return discord.Embed(
            title="❌ Invalid service name",
            description=f"`{service}` is not a valid service name.",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    code, output = run_command(
        f"sudo journalctl -u {service} --no-pager -n {LOG_LINES} -o cat 2>&1",
        timeout=15,
    )

    if code != 0:
        return discord.Embed(
            title="❌ Failed to retrieve logs",
            description=f"Error: {output[:500]}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    if len(output) > 1900:
        output = "...\n" + output[-1900:]

    embed = discord.Embed(
        title=f"📋 Recent {service} logs (last {LOG_LINES} lines)",
        description=f"```\n{output}\n```",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def cmd_disk() -> discord.Embed:
    """Disk usage overview."""
    code, output = run_command("df -h --total 2>/dev/null", timeout=10)
    if code != 0:
        return discord.Embed(
            title="❌ Failed to get disk usage",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )
    if len(output) > 1900:
        output = output[-1900:]
    embed = discord.Embed(
        title="💾 Disk Usage",
        description=f"```\n{output}\n```",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def cmd_mem() -> discord.Embed:
    """Memory and swap usage."""
    code, output = run_command("free -h", timeout=10)
    embed = discord.Embed(
        title="🧠 Memory & Swap",
        description=f"```\n{output}\n```",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def cmd_procs() -> discord.Embed:
    """Top processes by CPU and memory."""
    code, cpu_out = run_command("ps aux --sort=-%cpu | head -11", timeout=10)
    code, mem_out = run_command("ps aux --sort=-%mem | head -11", timeout=10)
    embed = discord.Embed(
        title="⚡ Top Processes",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="By CPU", value=f"```\n{cpu_out[:1000]}\n```", inline=False)
    embed.add_field(name="By Memory", value=f"```\n{mem_out[:1000]}\n```", inline=False)
    return embed


def cmd_net() -> discord.Embed:
    """Network connections and listening ports."""
    code, output = run_command("ss -tlnp | head -40", timeout=10)
    if len(output) > 1900:
        output = output[:1900] + "\n... (truncated)"
    embed = discord.Embed(
        title="🌐 Listening Ports & Connections",
        description=f"```\n{output}\n```",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def cmd_restart(service: str) -> discord.Embed:
    """Restart a service."""
    if not service:
        return discord.Embed(
            title="❌ No service specified",
            description="Usage: `!restart <service-name>`",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
        return discord.Embed(
            title="❌ Invalid service name",
            description=f"`{service}` is not a valid service name.",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    if service in NEVER_TOUCH_SERVICES:
        return discord.Embed(
            title="❌ Cannot restart self",
            description=f"Cannot restart {service} — self-protection.",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    log(f"Restarting {service} via bot command", "WARN")
    code, output = run_command(f"sudo systemctl restart {service}", timeout=30)

    if code == 0:
        time.sleep(3)
        active = systemctl_is_active(service)
        return discord.Embed(
            title=f"{'✅' if active else '⚠️'} {service} restarted",
            description=f"Service is {'active' if active else 'not active after restart'}",
            color=COLOR_SUCCESS if active else COLOR_WARN,
            timestamp=datetime.now(timezone.utc),
        )
    else:
        return discord.Embed(
            title=f"❌ Failed to restart {service}",
            description=f"Error: {output[:500]}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )


def cmd_help() -> discord.Embed:
    """Show available commands and agent capabilities."""
    embed = discord.Embed(
        title="⚓ Admiral Schubert — Server-Wide Autonomous Agent",
        description=(
            "Aye, Captain. I'm Admiral Schubert, commander of the good ship Schubert. "
            "I keep all services shipshape, investigate troubled waters, and patch leaks "
            "before they sink you. I can work via text or voice — ask me anything."
        ),
        color=COLOR_AGENT,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Quick Commands", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!status", value="Full server health (services, disk, RAM, uptime)", inline=False)
    embed.add_field(name="!services", value="List all active systemd services", inline=False)
    embed.add_field(name="!logs [service]", value="Recent logs for a service (default: tango-backend)", inline=False)
    embed.add_field(name="!restart <service>", value="Restart any service (critical services need confirmation)", inline=False)
    embed.add_field(name="!disk", value="Disk usage overview", inline=False)
    embed.add_field(name="!mem", value="Memory and swap usage", inline=False)
    embed.add_field(name="!procs", value="Top processes by CPU and memory", inline=False)
    embed.add_field(name="!net", value="Listening ports and network connections", inline=False)
    embed.add_field(name="Voice Commands", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!join", value="Join your voice channel — speak and I shall respond", inline=False)
    embed.add_field(name="!leave", value="Leave the voice channel", inline=False)
    embed.add_field(name="Agent Mode", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(
        name="Any message",
        value=(
            "Send a natural language request and I'll investigate, fix, "
            "restart, and commit autonomously across the entire server."
        ),
        inline=False,
    )
    embed.add_field(name="!agent <request>", value="Explicit agent invocation", inline=False)
    embed.set_footer(
        text=(
            f"Model: {LLM_MODEL} | Rate limit: {RATE_LIMIT_PER_MIN}/min | "
            f"Max iterations: {MAX_ITERATIONS} | Timeout: {AGENT_TIMEOUT}s"
        )
    )
    return embed


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    log(f"Admiral Schubert reporting for duty as {bot.user} (ID: {bot.user.id})", "INFO")
    log(f"Commanding channel {BOT_CHANNEL_ID}, serving Captain {ADMIN_USER_ID}", "INFO")
    log(f"LLM model: {LLM_MODEL} via {LITELLM_URL}", "INFO")
    log(f"Voice TTS: ElevenLabs {SCHUBERT_VOICE_ID} | STT: Deepgram {DEEPGRAM_MODEL}", "INFO")


@bot.event
async def on_message(message: discord.Message):
    global active_voice_session

    if message.author == bot.user:
        return

    if message.channel.id != BOT_CHANNEL_ID:
        return

    if message.author.id != ADMIN_USER_ID:
        log(
            f"Unauthorized message from user {message.author.id} "
            f"({message.author}): {message.content[:100]}",
            "WARN",
        )
        return

    if not check_rate_limit(message.author.id):
        await message.reply(
            f"⏱️ Rate limit exceeded. Max {RATE_LIMIT_PER_MIN} messages per minute."
        )
        return

    content = message.content.strip()

    # Handle ! prefix commands (Level 1 quick commands)
    if content.startswith("!"):
        parts = content[1:].strip().split()
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:]

        log(
            f"Command from {message.author}: !{command} {' '.join(args)}".strip(),
            "INFO",
        )

        try:
            if command == "help":
                await message.reply(embed=cmd_help())

            elif command == "status":
                await message.reply(embed=cmd_status())

            elif command == "services":
                await message.reply(embed=cmd_services())

            elif command == "logs":
                service = args[0] if args else "tango-backend.service"
                await message.reply(embed=cmd_logs(service))

            elif command == "restart":
                service = args[0] if args else ""

                if message.author.id in _pending_restarts:
                    pending_svc, pending_time = _pending_restarts.pop(
                        message.author.id
                    )
                    if time.time() - pending_time > RESTART_CONFIRM_TIMEOUT:
                        await message.reply(
                            "⏱️ Confirmation timed out. Please run !restart again."
                        )
                        return
                    if service == pending_svc or (not args and pending_svc):
                        await message.reply(f"⏳ Restarting {pending_svc}...")
                        await message.reply(embed=cmd_restart(pending_svc))
                        return
                    else:
                        await message.reply(
                            "❌ Service mismatch. Please run !restart again."
                        )
                        return

                if not service:
                    await message.reply("Usage: `!restart <service-name>`")
                    return

                if service in NEVER_TOUCH_SERVICES:
                    await message.reply(f"❌ Cannot restart {service} — self-protection.")
                    return

                if service in CRITICAL_SERVICES:
                    _pending_restarts[message.author.id] = (service, time.time())
                    await message.reply(
                        f"⚠️ **{service}** is a critical service.\n"
                        f"Restarting it may briefly interrupt server access.\n"
                        f"Type `!restart {service}` again within "
                        f"{RESTART_CONFIRM_TIMEOUT}s to confirm."
                    )
                    return

                await message.reply(f"⏳ Restarting {service}...")
                await message.reply(embed=cmd_restart(service))

            elif command == "disk":
                await message.reply(embed=cmd_disk())

            elif command == "mem":
                await message.reply(embed=cmd_mem())

            elif command == "procs":
                await message.reply(embed=cmd_procs())

            elif command == "net":
                await message.reply(embed=cmd_net())

            elif command == "join":
                # Join the voice channel the admin is in
                voice_state = message.author.voice
                if not voice_state or not voice_state.channel:
                    await message.reply(
                        "⚠️ You need to be in a voice channel first, Captain."
                    )
                    return

                if bot.voice_clients:
                    await message.reply(
                        "⚠️ I'm already in a voice channel, Captain."
                    )
                    return

                try:
                    voice_client = await voice_state.channel.connect(
                        cls=voice_recv.VoiceRecvClient
                    )
                    session = VoiceSession(
                        voice_client, bot, message.channel, message.author.id
                    )
                    voice_client.listen(VoiceAudioSink(session))
                    active_voice_session = session
                    log(
                        f"Joined voice channel {voice_state.channel.name} "
                        f"(ID: {voice_state.channel.id})",
                        "INFO",
                    )
                    await message.reply(
                        "⚓ Aye, Captain! I've joined the voice channel. "
                        "Speak and I shall respond."
                    )
                except Exception as e:
                    log(f"Failed to join voice channel: {e}", "ERROR")
                    await message.reply(f"❌ Failed to join voice channel: {e}")

            elif command == "leave":
                if not bot.voice_clients:
                    await message.reply("I'm not in a voice channel, Captain.")
                    return

                for vc in bot.voice_clients:
                    try:
                        if hasattr(vc, "stop_listening"):
                            vc.stop_listening()
                    except Exception:
                        pass
                    await vc.disconnect()

                if active_voice_session:
                    active_voice_session.stop()
                    active_voice_session = None

                log("Left voice channel", "INFO")
                await message.reply(
                    "⚓ Aye, Captain. I've left the voice channel."
                )

            elif command == "agent":
                agent_input = " ".join(args)
                if not agent_input:
                    await message.reply("Usage: `!agent <your request>`")
                    return
                await run_agent_with_update(message, agent_input)

            else:
                await message.reply(
                    f"❓ Unknown command: `!{command}`. Type `!help` for "
                    f"available commands, or just send a natural language "
                    f"message to use the autonomous agent."
                )

        except Exception as e:
            log(f"Error handling command !{command}: {e}", "ERROR")
            await message.reply(f"❌ Error: {str(e)[:500]}")

    else:
        # Natural language message — trigger agent loop
        log(f"Agent message from {message.author}: {content[:200]}", "INFO")
        await run_agent_with_update(message, content)


@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state changes — auto-leave if the channel empties."""
    global active_voice_session

    if not active_voice_session:
        return

    # If the admin left the voice channel, the bot should leave too
    if member.id == ADMIN_USER_ID and after.channel is None:
        if bot.voice_clients:
            for vc in bot.voice_clients:
                try:
                    if hasattr(vc, "stop_listening"):
                        vc.stop_listening()
                except Exception:
                    pass
                await vc.disconnect()
            active_voice_session.stop()
            active_voice_session = None
            log("Admin left voice channel, auto-disconnecting", "INFO")


async def run_agent_with_update(message: discord.Message, user_input: str):
    try:
        await message.reply(f"🤖 Working on: {user_input[:200]}")
        response = await run_agent_loop(message, user_input)

        if len(response) > 1900:
            for i in range(0, len(response), 1900):
                await message.reply(response[i : i + 1900])
        else:
            await message.reply(response)
    except Exception as e:
        log(f"Agent loop error: {e}", "ERROR")
        await message.reply(f"❌ Agent error: {str(e)[:500]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    log("=" * 60, "INFO")
    log("Schubert Bot (Level 3 agent with voice) starting", "INFO")
    log(f"Model: {LLM_MODEL} via {LITELLM_URL}", "INFO")
    log(f"Voice: discord-ext-voice-recv + Deepgram + ElevenLabs", "INFO")

    if not load_config():
        log("Configuration error — exiting", "CRITICAL")
        return 2

    try:
        bot.run(BOT_TOKEN, log_handler=None)
    except KeyboardInterrupt:
        log("Bot stopped by keyboard interrupt", "INFO")
    except Exception as e:
        log(f"Bot crashed: {e}", "CRITICAL")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
