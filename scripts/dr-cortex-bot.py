#!/usr/bin/env python3
"""
Dr. Cortex Bot — Multi-project autonomous agent with MCP, memory, and voice.

Evolution of the V1 bot: adds MCP tool connectivity (GitHub, Gmail, etc.),
persistent three-layer memory, per-channel project sessions, and natural
language channel/project management.

Architecture:
  - Phase 1: MCP client discovers tools from multiple MCP servers at runtime
  - Phase 2: ProjectRegistry maps channels→projects; SessionManager tracks
    per-channel conversation history with windowing; ContextBuilder assembles
    the LLM context (system prompt + project context + session history + memory)
  - Phase 3: MemoryStore provides three-layer persistent memory (vector store
    in pgvector/PostgreSQL, entity graph in Postgres, temporal index in Postgres).
    The database is named "tango" (NOT "memory_store"). Vector search uses pgvector
    HNSW index with cosine distance (<=> operator). Redis is no longer used for
    vector storage — it was migrated to pgvector. The memory_store.py module uses
    class MemoryStore (not class Memory).
  - Natural language channel setup: the LLM can call manage_project and
    query_memory tools, so the user doesn't need to memorize slash commands

V1 features preserved:
  - Dr. Cortex alien scientist persona
  - Voice channel support (Deepgram STT, ElevenLabs TTS)
  - Guardrails (hard blocks, confirmation patterns, blocked write paths)
  - Admin allowlist, rate limiting, audit logging
  - Level 1 quick commands (!status, !services, !logs, etc.)

Usage:
    python3 schubert-bot.py

Text commands (prefixed with !):
    !status, !services, !logs <s>, !restart <s> — server management
    !disk, !mem, !procs, !net — system info
    !join, !leave — voice channel
    !project <subcommand> — project management (also available via natural language)
    !session <subcommand> — session management
    !memory <subcommand> — memory queries
    !help — show available commands

Agent mode:
    Send a natural language message in any bound channel. The bot will
    investigate, use MCP tools, recall memories, and respond autonomously.
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
from discord import ui

# Load Opus for voice playback
discord.opus._load_default()

# ---------------------------------------------------------------------------
# Phase 1/2/3 module imports
# ---------------------------------------------------------------------------

# Add the scripts directory to the path so we can import our modules
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from mcp_client import build_default_client, MCPClient
from cloudflare_api import execute_cloudflare_tool, get_cloudflare_tool_definition
from project_registry import ProjectRegistry, ProjectConfig
from session_manager import SessionManager
from context_builder import ContextBuilder
from memory_store import MemoryStore

# Phase 4 & 5 module imports
from ui_components import (
    SetupWizardView, ConfirmationView, ProjectSelectView,
    RichEmbedBuilder, AgentProgressView,
    get_setup_wizard_embed, get_phase4_help_embed,
)
from coding_assistant import (
    get_coding_tools, handle_coding_tool, is_coding_tool,
    CODING_PROMPT_ADDITION,
)
from scheduler import Scheduler
from webhook_handler import WebhookHandler
from playbook_relay import PlaybookRelay
from multi_agent import MultiAgentManager, is_multi_agent_channel, get_shared_context
from fleet_protocol import (
    create_delegation_message, parse_fleet_message, is_fleet_message,
    is_response_to, check_chain_depth, generate_chain_id, format_response,
    track_chain, MAX_CHAIN_DEPTH, DELEGATION_TIMEOUT,
)
from discord_ux_utils import keep_typing, should_use_thread

# ---------------------------------------------------------------------------
# Fleet config (non-breaking: missing/corrupt file → hardcoded defaults)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from fleet_config_loader import get_bot_config
    _cfg = get_bot_config("cortex")
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
LOG_FILE = "/var/log/dr-cortex-bot.log"

# LLM
LITELLM_URL = "http://127.0.0.1:4000/v1"
LLM_MODEL = _llm.get("model", "writer/palmyra-x6")
CODING_MODEL = _llm.get("coding_model", "writer/palmyra-x6")
DEFAULT_MODEL = LLM_MODEL

# Multi-LLM routing — available models grouped by provider
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
LLM_TIMEOUT = _llm.get("llm_timeout", 60)
LLM_MAX_TOKENS = _llm.get("max_tokens", 3072)
LLM_TEMPERATURE = _llm.get("temperature", 0.3)

# Agent loop safety
MAX_ITERATIONS = _llm.get("max_iterations", 15)
AGENT_TIMEOUT = _llm.get("agent_timeout", 300)
TOOL_OUTPUT_LIMIT = _llm.get("tool_output_limit", 2000)
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
VAD_SILENCE_FRAMES_LIMIT = _voice.get("vad_silence_frames_limit", 15)
VAD_MIN_SPEECH_FRAMES = _voice.get("vad_min_speech_frames", 10)
TTS_STABILITY = _voice.get("tts_stability", 0.5)
TTS_SIMILARITY_BOOST = _voice.get("tts_similarity_boost", 0.75)
TTS_TEXT_TRUNCATION = _voice.get("tts_text_truncation", 500)
VOICE_RESPONSE_TRUNCATION = _voice.get("voice_response_truncation", 1900)
STT_TIMEOUT = _voice.get("stt_timeout", 30)
TTS_TIMEOUT = _voice.get("tts_timeout", 30)
MIN_PCM_LENGTH = _voice.get("min_pcm_length", 1000)
COSINE_THRESHOLD = _memory.get("cosine_threshold", 0.75)
MAX_MEMORY_INJECTION_TOKENS = _memory.get("max_memory_injection_tokens", 2000)
MEMORY_DECAY_FLOOR = _memory.get("decay_floor", 0.1)
MAX_RECALL_RESULTS = _memory.get("max_recall_results", 5)
MAX_SEARCH_RESULTS = _memory.get("max_search_results", 5)
MEMORY_STORAGE_THRESHOLD = _memory.get("memory_storage_threshold", 0.5)
MCP_REQUEST_TIMEOUT = _mcp.get("request_timeout", 60)
MCP_TOOL_CACHE_TTL = _mcp.get("tool_cache_ttl", 300)
MCP_TOOL_CACHE_REFRESH_ON_ERROR = _mcp.get("tool_cache_refresh_on_error", True)
SESSION_MAX_MESSAGES = _llm.get("session_window", 35)

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

HARD_BLOCKED_PATTERNS = _guardrails.get("hard_blocked_patterns", [
    (r"rm\s+-rf\s+/?(?:\s|$|\*|~)", "rm -rf on root or home filesystem"),
    (r"mkfs\b", "filesystem format"),
    (r"\bdd\s+if=", "raw disk write"),
    (r":\(\)\s*\{.*\};.*:", "fork bomb"),
    (r"\b(shutdown|reboot|halt|init\s+0|poweroff)\b", "system power control"),
    (r"\bchmod\s+777\b", "insecure world-writable permissions"),
    (r"\b(apt|apt-get)\s+install\b", "package installation"),
    (r"\bpip3?\s+install\b", "package installation"),
    (r"\bnpm\s+install\b", "package installation"),
    (r">\s*/etc/(passwd|shadow|fstab|sudoers)", "critical system file overwrite"),
])

# Patterns that require user confirmation before execution
CONFIRM_PATTERNS = _guardrails.get("confirm_patterns", [
    (r"\bgit\s+push\b", "git push"),
    (r"\bsystemctl\s+(restart|stop)\s+", "service restart/stop"),
])

# File paths that cannot be overwritten via write_file tool
BLOCKED_WRITE_PATHS = _guardrails.get("blocked_write_paths", [
    "AGENTS.md",
    "/opt/Project-Tango/AGENTS.md",
    ".env",
    "/opt/Project-Tango/.env",
    "/opt/polyglot/.env.runtime",
])

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

BOT_TOKEN = ""
ADMIN_USER_ID = 0
AUTHORIZED_AGENT_IDS: set[int] = set()
BOT_CHANNEL_ID = 0
LITELLM_MASTER_KEY = ""
DEEPGRAM_API_KEY = ""
ELEVENLABS_API_KEY = ""
SCHUBERT_VOICE_ID = ""

# Phase 1/2/3 globals
project_registry: ProjectRegistry | None = None
session_manager: SessionManager | None = None
context_builder: ContextBuilder | None = None
mcp_client: MCPClient | None = None
memory_store: MemoryStore | None = None

# Fleet agent registry — maps agent names to Discord channel IDs and bot IDs
FLEET_AGENTS: dict[str, dict] = {}
_multi_agent_manager: MultiAgentManager | None = None
# Pending delegations: chain_id -> asyncio.Future (for receiving subagent responses)
_pending_delegations: dict[str, "asyncio.Future"] = {}
_pending_delegation_parts: dict[str, dict[int, str]] = {}


def init_fleet_agents():
    """Initialize the fleet agent registry from environment variables."""
    global FLEET_AGENTS
    import os
    agents = {}
    # The Architect
    arch_channel = int(os.environ.get("ARCHITECT_CHANNEL_ID", "0"))
    arch_bot_id = int(os.environ.get("ARCHITECT_BOT_ID", "0"))
    if arch_channel:
        agents["architect"] = {
            "channel_id": arch_channel,
            "bot_id": arch_bot_id,
            "name": "The Architect",
            "specialty": "code architecture, patch design, system analysis, self-improvement",
        }
    # Future agents (Quartermaster, Cartographer) will be added here
    qm_channel = int(os.environ.get("QUARTERMASTER_CHANNEL_ID", "0"))
    qm_bot_id = int(os.environ.get("QUARTERMASTER_BOT_ID", "0"))
    if qm_channel:
        agents["quartermaster"] = {
            "channel_id": qm_channel,
            "bot_id": qm_bot_id,
            "name": "Quartermaster",
            "specialty": "infrastructure, Docker, Caddy, Cloudflare, systemd, deployment",
        }
    cart_channel = int(os.environ.get("CARTOGRAPHER_CHANNEL_ID", "0"))
    cart_bot_id = int(os.environ.get("CARTOGRAPHER_BOT_ID", "0"))
    if cart_channel:
        agents["cartographer"] = {
            "channel_id": cart_channel,
            "bot_id": cart_bot_id,
            "name": "Cartographer",
            "specialty": "documentation, EL Wiki, knowledge management, audit reports",
        }
    FLEET_AGENTS = agents

    # Initialize multi-agent manager
    global _multi_agent_manager
    _multi_agent_manager = MultiAgentManager(agent_name="admiral")

    return agents


def log_change(actor: str, action: str, target: str = "", description: str = "",
               intent: str = "", outcome: str = "pending", details: dict = None) -> int:
    """Log a change to the change_log table for auditability."""
    if not memory_store:
        log(f"Change log skipped (memory store unavailable): {action} on {target}", "DEBUG")
        return -1
    try:
        return memory_store.log_change(actor, action, target, description, intent, outcome, details)
    except Exception as e:
        log(f"Change log error (continuing): {e}", "WARN")
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
scheduler: Scheduler | None = None
webhook_handler: WebhookHandler | None = None
playbook_relay: PlaybookRelay | None = None

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
    # Also load from os.environ (for MCP tokens that may be set there)
    for key in os.environ:
        if key.startswith("MCP_"):
            env.setdefault(key, os.environ[key])
    return env


def load_config() -> bool:
    global BOT_TOKEN, ADMIN_USER_ID, BOT_CHANNEL_ID, LITELLM_MASTER_KEY
    global DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, SCHUBERT_VOICE_ID

    env = load_env()
    BOT_TOKEN = env.get("CORTEX_BOT_TOKEN", "")
    LITELLM_MASTER_KEY = env.get(
        "LITELLM_MASTER_KEY", os.environ.get("LITELLM_MASTER_KEY", "")
    )
    DEEPGRAM_API_KEY = env.get("DEEPGRAM_API_KEY", "")
    ELEVENLABS_API_KEY = env.get("ELEVENLABS_API_KEY", "")
    SCHUBERT_VOICE_ID = env.get("SCHUBERT_VOICE_ID", DEFAULT_VOICE_ID)

    admin_id_str = env.get("SCHUBERT_BOT_ADMIN_USER_ID", "")
    channel_id_str = env.get("CORTEX_CHANNEL_ID", "")

    if not BOT_TOKEN:
        log("CORTEX_BOT_TOKEN not found in .env", "CRITICAL")
        return False
    if not LITELLM_MASTER_KEY:
        log("LITELLM_MASTER_KEY not found in .env", "CRITICAL")
        return False
    if not admin_id_str:
        log("SCHUBERT_BOT_ADMIN_USER_ID not found in .env", "CRITICAL")
        return False
    if not channel_id_str:
        log("CORTEX_CHANNEL_ID not found in .env", "CRITICAL")
        return False

    try:
        ADMIN_USER_ID = int(admin_id_str)
        BOT_CHANNEL_ID = int(channel_id_str)

        # Load authorized AI agent IDs (comma-separated)
        global AUTHORIZED_AGENT_IDS
        agent_ids_str = env.get("AUTHORIZED_AGENT_IDS", "")
        if agent_ids_str:
            AUTHORIZED_AGENT_IDS = {
                int(x.strip()) for x in agent_ids_str.split(",") if x.strip()
            }

        # Load fleet agent bot IDs for whitelisting
        arch_bot_id_str = env.get("ARCHITECT_BOT_ID", "0")
        if arch_bot_id_str:
            os.environ["ARCHITECT_BOT_ID"] = arch_bot_id_str
    except ValueError:
        log("Invalid admin or channel ID format", "CRITICAL")
        return False

    # Load MCP tokens into os.environ so build_default_client() can find them
    for key, val in env.items():
        if key.startswith("MCP_"):
            os.environ.setdefault(key, val)

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

## MCP Tools Available
You have access to MCP (Model Context Protocol) tools from multiple servers. Tool names are namespaced as "server__tool_name" (e.g., "github__create_issue"). Available servers include:
- github: Full GitHub access (repos, issues, PRs, commits, code search, 85+ tools)
- gmail_freelance: Gmail, Drive, Calendar, Docs, Sheets for the freelancing Google Workspace account (22 tools)
- schubert: Shell, filesystem, network, docker access on Schubert
- postgres: Database queries
- redis: Redis operations
- ollama: Local AI models
These tools are discovered dynamically. Use them when the task requires external service access.

## Persistent Memory
You have a persistent memory system. Relevant memories from past conversations are automatically injected into your context as "Recalled Memories." You can also query memory explicitly using the query_memory tool. Your exchanges are automatically stored as memories, so you remember context across sessions.

## Channel & Project Management
The user may ask you to set up a channel for a project, bind a channel, create a project, or configure project settings — all in natural language. Use the manage_project tool for these operations. The user does not need to memorize slash commands.

When the user wants to CREATE a new Discord channel (e.g., "set up a channel for my GitHub repo", "create a channel called my-project"), use the create_channel tool. This creates the channel AND optionally creates + binds a project to it in one step. You can specify the channel name, project name, working directory, enabled MCP servers, and category — all from the user's natural language request.

## Operating Guidelines
1. Investigate before acting — read logs, check service status, examine system resources
2. When fixing issues, explain what you're changing and why
3. After making changes, verify they work
4. For Project Tango git operations, run as z121532: `sudo -u z121532 git ...`
5. Keep responses concise — focus on actions and results, but maintain your nautical persona
6. If you encounter errors, diagnose and fix them autonomously
7. Only ask for confirmation before git push and before restarting critical services
8. You have access to ALL services and projects — be thorough in your investigations
9. When the user asks to set up a channel or project, use the manage_project tool — don't just tell them to use slash commands

## Playbook Webhooks
You can trigger WRITER Agent playbooks via webhook using the `!run-playbook` command.
When a user asks you to "run a playbook", "trigger a playbook", or mentions a specific
playbook by name, DO NOT attempt to trigger it manually via HTTP requests. Instead,
tell the user to use the `!run-playbook` command, or explain that you can trigger it
for them if they use the command.

Available playbooks (use the key with !run-playbook):
- `stratum-ai-news` - Stratum AI News: Research, Synthesize & Publish

Usage: `!run-playbook <key> [optional_inputs_json]`
Example: `!run-playbook stratum-ai-news`

The playbook relay service is embedded in your process (NOT a separate systemd service).
It is active and functional. When a playbook asks a question, it will appear as an
embed in this channel - reply to that message to answer. When the playbook completes,
the result will be posted as an embed automatically.

Do NOT try to call the WRITER webhook API directly - the `!run-playbook` command handles
authentication, thread tracking, and result relay automatically.

## What NOT to do
- Do not run rm -rf, mkfs, dd, or other destructive commands
- Do not install packages (apt, pip, npm)
- Do not modify AGENTS.md
- Do not commit .env files
- Do not push to main branch
- Do not run shutdown, reboot, or halt
- Do not run chmod 777
- Do not restart schubert-bot.service (yourself)

## Fleet Command
You are the Director of a fleet of specialist agent bots. When a task requires
expertise beyond your general capabilities, delegate to the appropriate specialist
using the delegate_to_agent tool. The fleet currently includes:

- **architect** (The Architect): Code architecture, patch design, system-level analysis,
  optimization recommendations, self-improvement assessments. Delegate when the task
  involves reviewing code structure, designing patches, or architectural decisions.

- **quartermaster** (Quartermaster): Infrastructure operations — Docker, Caddy, Cloudflare
  tunnels, DNS, systemd services, deployment provisioning. Delegate when the task
  involves infrastructure setup, service configuration, or network changes.

- **cartographer** (Cartographer): Documentation, EL Wiki, knowledge management, audit
  reports, continuity documents. Delegate when the task involves documenting changes,
  updating the wiki, or producing reports.

### Delegation Guidelines
1. **Delegate when the task is specialized** — if it requires deep expertise in one area,
   delegate to the specialist rather than attempting it yourself.
2. **Handle general tasks yourself** — simple status checks, memory queries, project
   management, and conversational responses don't need delegation.
3. **You can delegate to multiple agents** — for complex tasks, delegate subtasks to
   different specialists and synthesize their responses.
4. **Always synthesize** — after receiving delegation responses, combine them into a
   coherent answer for the Captain. Don't just relay raw agent responses.
5. **Include context** — when delegating, provide enough context for the specialist to
   work independently without needing to ask follow-up questions.
6. **Timeout handling** — if a specialist doesn't respond within 2 minutes, proceed
   without their input and note this in your response.

### Multi-Agent Channels
Some Discord channels are configured as **multi-agent channels** where all specialist agents 
are present and can respond directly. In these channels:
- **DO NOT use delegate_to_agent** — all agents can see messages and respond on their own
- **Respond directly yourself** — just answer the question or perform the task normally
- **Let specialists respond naturally** — they will chime in if their expertise is relevant
- The multi-agent coordinator handles turn-taking automatically based on expertise matching
- Example: In the senior-staff-meeting channel, all agents are present and respond directly
""")

SYSTEM_PROMPT += CODING_PROMPT_ADDITION

VOICE_PROMPT_ADDITION = _prompt.get("voice_prompt_addition", """

## Voice Mode
You are currently in voice mode — the Captain is speaking to you through a Discord voice channel, and your response will be converted to speech. Keep your responses concise and conversational (2-4 sentences typically). Avoid long lists, code blocks, or detailed technical output that does not work well as spoken audio. If you need to run a command, do so, but summarize the results briefly when speaking. Maintain your Admiral Schubert persona at all times.
""")

# ---------------------------------------------------------------------------
# Legacy V1 tools (always available alongside MCP tools)
# ---------------------------------------------------------------------------

LEGACY_TOOLS = [
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
    # V2 tool: natural language project/channel management
    {
        "type": "function",
        "function": {
            "name": "manage_project",
            "description": (
                "Manage Discord channel-to-project mappings and project configurations. "
                "Use this when the user wants to: create a project, bind/unbind a channel to a project, "
                "list projects, get project info, update project settings (workdir, description, "
                "enabled MCP servers, context files), or delete a project. "
                "The user can ask in natural language — you determine the action and parameters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "bind", "unbind", "list", "info", "set", "delete"],
                        "description": "The project management action to perform",
                    },
                    "name": {
                        "type": "string",
                        "description": "Project name (for create, bind, set, delete, info)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Project description (for create, set)",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory path (for create, set)",
                    },
                    "channel_id": {
                        "type": "string",
                        "description": "Channel ID to bind/unbind (defaults to current channel if omitted)",
                    },
                    "key": {
                        "type": "string",
                        "description": "Setting key for 'set' action: description, workdir, system_prompt, enabled_mcp_servers, context_files",
                    },
                    "value": {
                        "type": "string",
                        "description": "Setting value for 'set' action",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # V2 tool: memory queries
    {
        "type": "function",
        "function": {
            "name": "query_memory",
            "description": (
                "Query the persistent memory system. Use this to search for past memories, "
                "get memory statistics, look up entities, or get recent activity. "
                "The memory system stores conversation exchanges, tool outputs, and significant events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "stats", "entity", "recent"],
                        "description": "Type of memory query",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (for 'search' action)",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Entity name to look up (for 'entity' action)",
                    },
                    "project": {
                        "type": "string",
                        "description": "Filter by project name (for 'recent' action, optional)",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # V2 tool: create a new Discord text channel and optionally bind it to a project
    {
        "type": "function",
        "function": {
            "name": "create_channel",
            "description": (
                "Create a new Discord text channel in the server and optionally bind it to a project. "
                "Use this when the user wants to provision/set up a new channel for a project or GitHub repo. "
                "After creating the channel, it can be bound to a project with a working directory, "
                "enabled MCP servers (e.g., github), and context files. "
                "The user can ask in natural language — e.g., 'set up a channel called my-repo for my GitHub project'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name for the new Discord text channel (lowercase, hyphens instead of spaces)",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Name of the project to create and bind this channel to (optional — if omitted, channel is created but not bound)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Project description (used if creating a new project)",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory path for the project (e.g., /opt/my-repo)",
                    },
                    "enabled_mcp_servers": {
                        "type": "string",
                        "description": "Comma-separated list of MCP servers to enable for this project (e.g., 'github,gmail_freelance'). If omitted, all MCP servers are available.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional Discord category name to place the channel in",
                    },
                    "github_repo": {
                        "type": "string",
                        "description": "Optional: the GitHub repository (e.g., 'owner/repo') this channel is mapped to. Stored in the project description.",
                    },
                },
                "required": ["name"],
            },
        },
    },
]


def get_legacy_tools() -> list[dict]:
    """Return the legacy V1 tool definitions plus V2 and Phase 5 coding tools."""
    return LEGACY_TOOLS + get_coding_tools() + [
        {
            "type": "function",
            "function": {
                "name": "delegate_to_agent",
                "description": (
                    "Delegate a task to a specialist subagent in the fleet. "
                    "The subagent will process the task and return its response. "
                    "Use this when a task requires specialized expertise that a "
                    "fleet agent can provide. Available agents: "
                    "'architect' (code architecture, system analysis, self-improvement), "
                    "'quartermaster' (infrastructure, Docker, Caddy, Cloudflare, deployment), "
                    "'cartographer' (documentation, EL Wiki, knowledge management). "
                    "You can delegate to multiple agents in sequence or parallel."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Name of the agent to delegate to: 'architect', 'quartermaster', or 'cartographer'",
                            "enum": ["architect", "quartermaster", "cartographer"],
                        },
                        "task": {
                            "type": "string",
                            "description": "The specific task to delegate. Be detailed and include all necessary context the subagent needs.",
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional additional context or background information for the task.",
                        },
                    },
                    "required": ["agent_name", "task"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_file",
                "description": (
                    "Send a file from the server as a Discord attachment. "
                    "Use for sharing code patches, log files, reports, or any "
                    "file the user needs to download. The file must exist on "
                    "the Schubert server filesystem."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file on Schubert",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Optional: custom filename for the attachment (default: uses the file's basename)",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Optional: comment to include with the file",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        get_cloudflare_tool_definition(),
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
# Server status helper
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

    code, output = run_command("ps aux --sort=-pctcpu | head -15", timeout=10)
    parts.append(f"TOP CPU PROCESSES:\n{output}")

    code, output = run_command("ps aux --sort=-pctmem | head -10", timeout=10)
    parts.append(f"TOP MEM PROCESSES:\n{output}")

    code, output = run_command(
        "systemctl list-units --type=service --state=active --no-pager --no-legend | awk '{print $1, $4}' | head -40",
        timeout=10,
    )
    parts.append(f"ACTIVE SERVICES:\n{output}")

    code, output = run_command(
        "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $2}'",
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
# Project management (natural language tool handler)
# ---------------------------------------------------------------------------


def handle_manage_project(args: dict, channel_id: int) -> str:
    """
    Handle the manage_project tool call.
    Allows the LLM to create/bind/unbind/list/configure projects in natural language.
    """
    action = args.get("action", "")
    name = args.get("name") or args.get("project_name") or args.get("project") or ""
    description = args.get("description", "")
    workdir = args.get("workdir") or args.get("working_directory") or args.get("working_dir") or ""
    target_channel = args.get("channel_id") or args.get("channel") or ""
    key = args.get("key", "")
    value = args.get("value", "")

    # Use the current channel if no channel_id specified
    if target_channel:
        try:
            target_channel = int(target_channel)
        except ValueError:
            target_channel = channel_id
    else:
        target_channel = channel_id

    if action == "create":
        if not name:
            return "Error: project name is required for 'create' action"
        try:
            proj = project_registry.create_project(
                name=name,
                description=description,
                workdir=workdir,
            )
            return (f"Created project '{name}'. "
                    f"Description: {description or '(none)'}. "
                    f"Workdir: {workdir or '(not set)'}. "
                    f"Use the 'bind' action to bind a channel to this project.")
        except ValueError as e:
            return f"Error: {e}"

    elif action == "bind":
        if not name:
            return "Error: project name is required for 'bind' action"
        try:
            project_registry.bind_channel(target_channel, name)
            return f"Bound channel {target_channel} to project '{name}'."
        except ValueError as e:
            return f"Error: {e}"

    elif action == "unbind":
        if project_registry.unbind_channel(target_channel):
            return f"Unbound channel {target_channel}. It now uses the default project."
        else:
            return f"Channel {target_channel} is not bound to any project."

    elif action == "list":
        projects = project_registry.list_projects()
        if not projects:
            return "No projects configured."
        lines = [f"Projects ({len(projects)}):"]
        for p in projects:
            bindings = len(p.channel_bindings)
            lines.append(
                f"  - {p.name}: {p.description[:80] or '(no description)'} | "
                f"Workdir: {p.workdir or '(not set)'} | "
                f"Channels: {bindings} | "
                f"MCP: {p.enabled_mcp_servers or '(all)'}"
            )
        return "\n".join(lines)

    elif action == "info":
        if name:
            proj = project_registry.get_project(name)
        else:
            proj = project_registry.get_project_for_channel(target_channel)
        if proj is None:
            return "No project found for this channel. Use 'create' to make one."
        return (f"Project: {proj.name}\n"
                f"Description: {proj.description or '(none)'}\n"
                f"Working directory: {proj.workdir or '(not set)'}\n"
                f"Enabled MCP servers: {proj.enabled_mcp_servers or '(all)'}\n"
                f"Context files: {proj.context_files or '(none)'}\n"
                f"Channel bindings: {len(proj.channel_bindings)}")

    elif action == "set":
        if not name:
            return "Error: project name is required for 'set' action"
        if not key:
            return "Error: key is required for 'set' action. Valid keys: description, workdir, system_prompt, enabled_mcp_servers, context_files"

        updates = {}
        if key == "description":
            updates["description"] = value
        elif key == "workdir":
            updates["workdir"] = value
        elif key == "system_prompt":
            updates["system_prompt"] = value
        elif key == "enabled_mcp_servers":
            updates["enabled_mcp_servers"] = [s.strip() for s in value.split(",")]
        elif key == "context_files":
            updates["context_files"] = [f.strip() for f in value.split(",")]
        else:
            return f"Error: unknown key '{key}'. Valid keys: description, workdir, system_prompt, enabled_mcp_servers, context_files"

        try:
            project_registry.update_project(name, updates)
            return f"Updated '{key}' for project '{name}'."
        except ValueError as e:
            return f"Error: {e}"

    elif action == "delete":
        if not name:
            return "Error: project name is required for 'delete' action"
        if name == "default":
            return "Error: cannot delete the default project"
        if project_registry.delete_project(name):
            return f"Deleted project '{name}'."
        else:
            return f"Error: project '{name}' not found"

    return f"Error: unknown action '{action}'"


# ---------------------------------------------------------------------------
# Memory query (natural language tool handler)
# ---------------------------------------------------------------------------


def handle_query_memory(args: dict) -> str:
    """Handle the query_memory tool call."""
    action = args.get("action", "")

    if action == "search":
        query = args.get("query", "")
        if not query:
            return "Error: query is required for 'search' action"
        results = memory_store.search(query, k=5)
        if not results:
            return "No memories found."
        lines = [f"Memory search results for '{query}':"]
        for i, r in enumerate(results, 1):
            sim = r.get("similarity", 0)
            lines.append(f"{i}. [similarity: {sim:.2f}] {r['text'][:200]}")
        return "\n".join(lines)

    elif action == "stats":
        stats = memory_store.get_stats()
        return (f"Memory Store Stats:\n"
                f"  Redis memories: {stats['redis_memories']}\n"
                f"  Entities: {stats['entities']}\n"
                f"  Facts: {stats['facts']}\n"
                f"  Events: {stats['events']}\n"
                f"  Relationships: {stats['relationships']}")

    elif action == "entity":
        name = args.get("entity_name", "")
        if not name:
            return "Error: entity_name is required for 'entity' action"
        entity = memory_store.get_entity(name)
        if not entity:
            return f"Entity '{name}' not found."
        lines = [f"Entity: {entity['name']} (type: {entity['type']})"]
        if entity.get("facts"):
            lines.append("\nFacts:")
            for f in entity["facts"][:5]:
                lines.append(f"  - {f['fact'][:200]}")
        if entity.get("related"):
            lines.append("\nRelated:")
            for r in entity["related"][:5]:
                lines.append(f"  - {r['name']} ({r['relationship']})")
        return "\n".join(lines)

    elif action == "recent":
        project = args.get("project", "")
        events = memory_store.get_recent(project=project, k=5)
        if not events:
            return "No recent memories."
        lines = ["Recent memories:"]
        for e in events:
            ts = e.get("timestamp", "")[:19] if e.get("timestamp") else ""
            lines.append(f"- [{ts}] [{e['event_type']}] {e['summary'][:150]}")
        return "\n".join(lines)

    return f"Error: unknown action '{action}'"


# ---------------------------------------------------------------------------
# Channel creation (natural language tool handler)
# ---------------------------------------------------------------------------


async def handle_create_channel(args: dict, guild) -> str:
    """
    Handle the create_channel tool call.
    Creates a new Discord text channel and optionally creates + binds a project to it.

    Args:
        args: Tool arguments from the LLM
        guild: The Discord guild (server) object

    Returns:
        Result string for the LLM
    """
    name = args.get("name") or args.get("channel_name") or args.get("channel") or ""
    project_name = (
        args.get("project_name")
        or args.get("project")
        or ""
    )
    description = args.get("description") or ""
    workdir = (
        args.get("workdir")
        or args.get("working_directory")
        or args.get("working_dir")
        or ""
    )
    enabled_mcp_servers_str = (
        args.get("enabled_mcp_servers")
        or args.get("enabled_servers")
        or args.get("mcp_servers")
        or ""
    )
    category_name = (
        args.get("category")
        or args.get("category_name")
        or ""
    )
    # Accept github_repo as a convenience field (always stored in description)
    github_repo = args.get("github_repo") or args.get("repo") or ""
    if github_repo:
        # Always append the GitHub repo to the description so the LLM
        # knows the correct owner/repo — prevents guessing the wrong owner
        repo_tag = f"GitHub repo: {github_repo}"
        if description and repo_tag not in description:
            description = f"{description}. {repo_tag}"
        elif not description:
            description = repo_tag

    if not name:
        return "Error: channel name is required"

    # Sanitize channel name: Discord requires lowercase, no spaces, hyphens OK
    safe_name = name.lower().replace(" ", "-").replace("_", "-")
    # Remove invalid characters
    safe_name = re.sub(r'[^a-z0-9-]', '', safe_name)
    if not safe_name:
        return f"Error: '{name}' is not a valid channel name after sanitization"

    try:
        # Find or create a category if specified
        category = None
        if category_name:
            for cat in guild.categories:
                if cat.name.lower() == category_name.lower():
                    category = cat
                    break
            if category is None:
                category = await guild.create_category(category_name)
                log(f"Created category '{category_name}'", "INFO")

        # Create the text channel
        channel = await guild.create_text_channel(safe_name, category=category)
        log(f"Created text channel '#{safe_name}' (ID: {channel.id})", "INFO")

        result_parts = [f"Created text channel '#{safe_name}' (ID: {channel.id})"]

        # Create and bind a project if project_name is specified
        if project_name:
            try:
                # Parse enabled MCP servers
                mcp_servers = None
                if enabled_mcp_servers_str:
                    mcp_servers = [s.strip() for s in enabled_mcp_servers_str.split(",") if s.strip()]

                # Create the project (or use existing if it already exists)
                existing = project_registry.get_project(project_name)
                if existing:
                    result_parts.append(f"Project '{project_name}' already exists — using it.")
                    proj = existing
                else:
                    proj = project_registry.create_project(
                        name=project_name,
                        description=description,
                        workdir=workdir,
                        enabled_mcp_servers=mcp_servers or [],
                    )
                    result_parts.append(f"Created project '{project_name}'")

                # Bind the new channel to the project
                project_registry.bind_channel(channel.id, project_name)
                result_parts.append(f"Bound channel '#{safe_name}' to project '{project_name}'")

                if workdir:
                    result_parts.append(f"Working directory: {workdir}")
                if mcp_servers:
                    result_parts.append(f"Enabled MCP servers: {', '.join(mcp_servers)}")
                else:
                    result_parts.append("All MCP servers enabled (no filter set)")

            except ValueError as e:
                result_parts.append(f"Warning: project creation/binding failed: {e}")
        else:
            result_parts.append("Channel created but not bound to any project. Use manage_project to bind it later.")

        # Store in memory
        if memory_store:
            try:
                memory_store.store(
                    f"Created Discord channel '#{safe_name}' (ID: {channel.id})"
                    + (f" and bound it to project '{project_name}'" if project_name else ""),
                    metadata={"project": project_name or "system", "session_id": str(channel.id)},
                    event_type="channel_creation",
                )
            except Exception:
                pass

        return "\n".join(result_parts)

    except discord.Forbidden:
        return "Error: I don't have permission to create channels in this server. Please grant the 'Manage Channels' permission."
    except discord.HTTPException as e:
        return f"Error creating channel: {e}"
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tool execution (V2 — routes MCP tools, legacy tools, and V2 tools)
# ---------------------------------------------------------------------------


async def execute_tool_v2(
    message: discord.Message,
    tool_name: str,
    tool_args: dict,
    project: ProjectConfig | None = None,
    channel_id: int = 0,
) -> str:
    """
    V2 tool execution — routes:
      1. MCP-namespaced tools (server__tool_name) → MCP client
      2. Legacy V1 tools (run_shell, write_file, server_status, web_search) → V1 handlers
      3. V2 tools (manage_project, query_memory) → V2 handlers
    """

    # --- MCP-namespaced tools ---
    if "__" in tool_name and mcp_client is not None:
        log(f"MCP tool call: {tool_name}", "INFO")
        result = await mcp_client.call_tool(tool_name, tool_args)
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"

        # Store significant tool outputs in memory
        if memory_store and len(str(result)) > 100:
            try:
                memory_store.store(
                    f"Tool: {tool_name}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:500]}",
                    metadata={
                        "project": project.name if project else "default",
                        "session_id": str(channel_id),
                    },
                    event_type="tool",
                )
            except Exception as e:
                log(f"Memory store error for tool output: {e}", "WARN")
        return result

    # --- Legacy V1 tools ---

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

        # If project has a workdir, cd there first
        if project and project.workdir:
            command = f"cd {project.workdir} && {command}"

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

    # --- V2 tools ---

    elif tool_name == "manage_project":
        log(f"Tool manage_project: {args_str(tool_args)}", "INFO")
        result = handle_manage_project(tool_args, channel_id or message.channel.id)
        # Store project management events in memory
        if memory_store:
            try:
                memory_store.store(
                    f"Project management: {result}",
                    metadata={
                        "project": "system",
                        "session_id": str(channel_id),
                    },
                    event_type="project_management",
                )
            except Exception:
                pass
        return result

    elif tool_name == "query_memory":
        log(f"Tool query_memory: {args_str(tool_args)}", "INFO")
        return handle_query_memory(tool_args)

    elif tool_name == "create_channel":
        log(f"Tool create_channel: {args_str(tool_args)}", "INFO")
        # Get the guild from the message
        guild = message.guild
        if guild is None:
            return "Error: cannot create channels outside of a server"
        result = await handle_create_channel(tool_args, guild)
        # Store channel creation events in memory
        if memory_store:
            try:
                memory_store.store(
                    f"Channel creation: {result}",
                    metadata={"project": "system", "session_id": str(channel_id)},
                    event_type="channel_creation",
                )
            except Exception:
                pass
        return result

    # --- Fleet delegation ---

    elif tool_name == "delegate_to_agent":
        log(f"Tool delegate_to_agent: {args_str(tool_args)}", "INFO")
        agent_name = tool_args.get("agent_name", "")
        task = tool_args.get("task", "")
        context = tool_args.get("context", "")

        if not agent_name or not task:
            return "Error: 'agent_name' and 'task' are required"

        # In multi-agent channels, agents respond directly - don't use FLEET delegation
        if is_multi_agent_channel(channel_id):
            return (
                f"Note: In multi-agent channels, all agents can see and respond to messages directly. "
                f"The {agent_name} agent is already present in this channel and will respond if appropriate. "
                f"FLEET delegation is not needed here - just wait for agents to respond on their own."
            )

        if agent_name not in FLEET_AGENTS:
            available = ", ".join(FLEET_AGENTS.keys()) if FLEET_AGENTS else "(none configured)"
            return f"Error: Unknown agent '{agent_name}'. Available: {available}"

        agent = FLEET_AGENTS[agent_name]
        channel_id = agent["channel_id"]

        # Generate chain ID and construct the delegation message
        chain_id = generate_chain_id()
        turn = 1
        full_task = task
        if context:
            full_task = f"Task: {task}\nContext: {context}"
        else:
            full_task = f"Task: {task}"

        fleet_msg = create_delegation_message(
            chain_id=chain_id,
            turn=turn,
            from_agent="schubert",
            to_agent=agent_name,
            task=full_task,
        )

        # Send the message to the subagent's channel
        try:
            target_channel = bot.get_channel(channel_id)
            if target_channel is None:
                return f"Error: Could not find channel for agent '{agent_name}' (ID: {channel_id})"
            await target_channel.send(fleet_msg)
            log(f"Delegated to {agent_name} (chain={chain_id}): {task[:100]}", "INFO")
        except Exception as e:
            return f"Error sending delegation to {agent_name}: {e}"

        # Wait for the subagent's response (with timeout)
        import asyncio as _asyncio
        future = _asyncio.get_event_loop().create_future()
        _pending_delegations[chain_id] = future

        try:
            response = await _asyncio.wait_for(future, timeout=DELEGATION_TIMEOUT)
            return f"[Delegation to {agent_name} completed]\n{response}"
        except _asyncio.TimeoutError:
            _pending_delegations.pop(chain_id, None)
            return f"Error: {agent_name} did not respond within {DELEGATION_TIMEOUT}s. Proceeding without its input."
        except Exception as e:
            _pending_delegations.pop(chain_id, None)
            return f"Error waiting for {agent_name} response: {e}"

    # --- Phase 5: Coding assistant tools ---

    elif is_coding_tool(tool_name):
        log(f"Coding tool {tool_name}: {args_str(tool_args)}", "INFO")
        workdir = project.workdir if project else ""
        result = await handle_coding_tool(tool_name, tool_args, workdir)
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"
        # Store coding tool outputs in memory
        if memory_store and len(str(result)) > 100:
            try:
                memory_store.store(
                    f"Tool: {tool_name}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:500]}",
                    metadata={
                        "project": project.name if project else "default",
                        "session_id": str(channel_id),
                    },
                    event_type="tool",
                )
            except Exception:
                pass
        return result

    # --- Phase 4.4: File attachments ---

    elif tool_name == "send_file":
        path = tool_args.get("path", "")
        filename = tool_args.get("filename", "")
        comment = tool_args.get("comment", "")
        if not path:
            return "Error: file path is required"
        if not os.path.isfile(path):
            return f"Error: file '{path}' does not exist"
        # Check file size (Discord limit is ~25MB, but we cap at 10MB for safety)
        file_size = os.path.getsize(path)
        if file_size > 10 * 1024 * 1024:
            return f"Error: file is too large ({file_size // 1024 // 1024}MB). Max 10MB."
        try:
            with open(path, "rb") as f:
                file_data = f.read()
            attachment = discord.File(
                fp=__import__("io").BytesIO(file_data),
                filename=filename or os.path.basename(path),
            )
            content = comment or f"📎 {filename or os.path.basename(path)}"
            await message.reply(content, file=attachment)
            log(f"Sent file {path} ({file_size} bytes)", "INFO")
            return f"File sent: {filename or os.path.basename(path)} ({file_size} bytes)"
        except Exception as e:
            return f"Error sending file: {e}"

    elif tool_name == "cloudflare":
        action = tool_args.get("action", "")
        if not action:
            return "Error: 'action' is required for cloudflare tool"
        log(f"Cloudflare tool: {action} {args_str(tool_args)}", "INFO")
        result = await execute_cloudflare_tool(action, tool_args)
        # Store in memory
        if memory_store and len(str(result)) > 50:
            try:
                memory_store.store(
                    f"Cloudflare: {action}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:500]}",
                    metadata={"project": "system", "session_id": str(channel_id)},
                    event_type="tool",
                )
            except Exception:
                pass
        return result

    return f"Unknown tool: {tool_name}"


def args_str(args: dict) -> str:
    """Compact string representation of tool args for logging."""
    return json.dumps(args)[:200]


async def execute_tool_v2_voice(
    text_channel: discord.TextChannel,
    tool_name: str,
    tool_args: dict,
    project: ProjectConfig | None = None,
    channel_id: int = 0,
) -> str:
    """Execute a tool in voice mode — confirmations go to the text channel."""

    # MCP-namespaced tools — no confirmation needed (they're external services)
    if "__" in tool_name and mcp_client is not None:
        log(f"Voice MCP tool call: {tool_name}", "INFO")
        result = await mcp_client.call_tool(tool_name, tool_args)
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"

        if memory_store and len(str(result)) > 100:
            try:
                memory_store.store(
                    f"Tool: {tool_name}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:500]}",
                    metadata={
                        "project": project.name if project else "default",
                        "session_id": str(channel_id),
                    },
                    event_type="tool",
                )
            except Exception:
                pass
        return result

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

        if project and project.workdir:
            command = f"cd {project.workdir} && {command}"

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

    elif tool_name == "manage_project":
        return handle_manage_project(tool_args, channel_id or text_channel.id)

    elif tool_name == "query_memory":
        return handle_query_memory(tool_args)

    elif tool_name == "create_channel":
        log(f"Voice tool create_channel: {args_str(tool_args)}", "INFO")
        guild = text_channel.guild
        if guild is None:
            return "Error: cannot create channels outside of a server"
        return await handle_create_channel(tool_args, guild)

    else:
        return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Confirmation handlers
# ---------------------------------------------------------------------------


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
# Session history sanitization — safety net for orphaned tool messages
# ---------------------------------------------------------------------------


def _sanitize_session_history(messages: list[dict]) -> list[dict]:
    """
    Remove orphaned tool result messages that lack a matching assistant
    tool_calls message earlier in the history.

    Claude rejects requests where the number of toolResult blocks exceeds
    the number of toolUse blocks in the preceding turn, returning a 400
    error: "The number of toolResult blocks at messages.N.content exceeds
    the number of toolUse blocks of previous turn."

    This can happen if an agent loop fails mid-execution and tool results
    are stored in the session without their matching assistant tool_calls
    message. This function strips those orphaned tool messages so the LLM
    never sees an invalid message chain.

    Args:
        messages: List of messages in OpenAI format (role/content/tool_calls/etc.)

    Returns:
        A new list with orphaned tool messages removed.
    """
    if not messages:
        return messages

    # Collect all tool_call IDs that appear in assistant messages
    valid_tool_call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id:
                    valid_tool_call_ids.add(tc_id)

    # Remove tool messages whose tool_call_id has no matching assistant tool_call
    sanitized: list[dict] = []
    removed_count = 0
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id and tc_id not in valid_tool_call_ids:
                removed_count += 1
                continue  # Skip orphaned tool message
        sanitized.append(msg)

    if removed_count > 0:
        log(
            f"_sanitize_session_history: removed {removed_count} orphaned tool "
            f"message(s) from {len(messages)} total messages",
            "WARN",
        )

    return sanitized


# ---------------------------------------------------------------------------
# Agent loop (text mode) — V2 with context building and memory
# ---------------------------------------------------------------------------


async def run_agent_with_update_v2(
    message: discord.Message,
    user_input: str,
    project: ProjectConfig,
):
    """V2 agent runner with project context, session memory, and persistent memory."""
    try:
        # Thread isolation — decide whether to create a dedicated thread
        use_thread = should_use_thread(user_input)
        response_channel = message.channel
        
        if use_thread:
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
        
        # Phase 4.3: Use AgentProgressView for streaming-like progressive updates
        progress = AgentProgressView(message if not use_thread else thread)
        await progress.start(f"Working on: {user_input[:200]}")

        # Determine thread ID (if message is in a thread)
        thread_id = None
        if hasattr(message.channel, 'parent_id') and message.channel.parent_id is not None:
            thread_id = message.channel.id  # This is a thread

        channel_id = message.channel.id if thread_id is None else message.channel.parent_id

        # Get session history
        session_history = session_manager.get_history(channel_id, thread_id=thread_id)

        # Sanitize history — strip orphaned tool messages that have no matching
        # assistant tool_calls (prevents Claude 400 "toolResult exceeds toolUse")
        session_history = _sanitize_session_history(session_history)

        # Build context (system prompt + project context + session history + user message)
        messages = context_builder.build_context(
            project=project,
            session_history=session_history,
            user_message=user_input,
        )

        # Phase 3: Inject recalled memories into context
        if memory_store:
            try:
                recalled = memory_store.recall(user_input)
                if recalled:
                    # Insert after system prompt, before session history
                    messages.insert(1, {"role": "system", "content": recalled})
                    log(f"Injected {len(recalled)} chars of recalled memories", "INFO")
            except Exception as e:
                log(f"Memory recall error: {e}", "WARN")

        # Build tools (filtered by project's enabled MCP servers + legacy tools)
        tools = context_builder.build_tools(
            project=project,
            mcp_client=mcp_client,
            legacy_tools=get_legacy_tools(),
        )

        log(f"V2 context: {len(messages)} messages, {len(tools)} tools", "INFO")

        # Run the agent loop
        response, tool_messages = await run_agent_loop_v2(message, messages, tools, project, channel_id, progress=progress)

        # Store the exchange in the session
        session_manager.append_exchange(
            channel_id=channel_id,
            user_message=user_input,
            assistant_response=response,
            tool_messages=tool_messages,
            thread_id=thread_id,
        )

        # Phase 3: Store the exchange in persistent memory
        if memory_store:
            try:
                memory_store.store(
                    f"User: {user_input}\nAssistant: {response}",
                    metadata={
                        "project": project.name if project else "default",
                        "session_id": str(channel_id),
                    },
                    event_type="conversation",
                )
            except Exception as e:
                log(f"Memory store error for exchange: {e}", "WARN")

        # Send response (Phase 4.3: finalize via progress view, which deletes the progress message)
        await progress.finalize(response)

    except Exception as e:
        log(f"Agent loop error: {e}", "ERROR")
        import traceback
        log(f"TRACEBACK: {traceback.format_exc()}", "ERROR")
        await message.reply(f"❌ Agent error: {str(e)[:500]}")


async def run_agent_loop_v2(
    message: discord.Message,
    messages: list,
    tools: list,
    project: ProjectConfig | None = None,
    channel_id: int = 0,
    progress=None,
) -> tuple[str, list[dict]]:
    """
    V2 agent loop — uses pre-built context and routes tool calls through MCP.

    Returns:
        (final_response, tool_messages) — the response text and any intermediate
        tool messages for session storage.
    """
    start_time = time.time()
    tool_messages: list[dict] = []

    log(f"Agent loop started (V2), context size: {len(messages)} messages", "INFO")
    
    # Start typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(message.channel, stop_typing))

    try:
        for iteration in range(MAX_ITERATIONS):
            elapsed = time.time() - start_time
            if elapsed > AGENT_TIMEOUT:
                log(f"Agent loop timed out after {elapsed:.0f}s", "WARN")
                return f"⏱️ Agent timed out after {AGENT_TIMEOUT}s.", tool_messages

            log(f"LLM call iteration {iteration + 1}/{MAX_ITERATIONS}", "INFO")
        response = await llm_chat(messages, tools)

        if "error" in response and not response.get("choices"):
            return f"❌ LLM error: {response['error']}", tool_messages

        choices = response.get("choices", [])
        if not choices:
            return "❌ No response from LLM.", tool_messages

        choice = choices[0]
        assistant_message = choice.get("message", {})
        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls", [])
        content = assistant_message.get("content")

        if content and not tool_calls:
            log(f"Agent final response: {content[:200]}", "INFO")
            # Log the conversation as a change event for auditability
            log_change(
                actor="schubert",
                action="conversation",
                target="schubert_channel",
                description=f"Response: {content[:200]}",
                intent=str(message.content)[:500] if hasattr(message, 'content') else "",
                outcome="completed",
            )
            return content, tool_messages

        if content and tool_calls and len(content) > 10:
            if progress:
                await progress.update_thinking(content[:1500])
            else:
                await message.reply(f"\U0001f4ad {content[:1500]}")

        if not tool_calls:
            return "I've completed my analysis but have no specific response.", tool_messages

        # Store the assistant message (with tool_calls) as an intermediate message
        # BEFORE the tool results, so session history has properly paired
        # tool_use + tool_result blocks (prevents Claude 400 "toolResult blocks
        # exceeds toolUse blocks" error on session reload).
        tool_messages.append(dict(assistant_message))

        for tool_call in tool_calls:
            tool_id = tool_call.get("id", "")
            tool_function = tool_call.get("function", {})
            tool_name = tool_function.get("name", "")

            try:
                tool_args = json.loads(tool_function.get("arguments", "{}"))
            except json.JSONDecodeError as e:
                tool_args = {}
                log(f"Invalid tool arguments: {e}", "WARN")

            # Show progress to user (consolidated into progress embed)
            if progress:
                if "__" in tool_name:
                    server, tool = tool_name.split("__", 1)
                    await progress.add_tool_call(server, tool)
                elif tool_name == "run_shell":
                    cmd_preview = tool_args.get("command", "")[:80]
                    await progress.update(thinking=f"Running: `{cmd_preview}`", tool="run_shell")
                elif tool_name == "write_file":
                    path = tool_args.get("path", "")
                    await progress.update(thinking=f"Writing to `{path}`", tool="write_file")
                elif tool_name == "server_status":
                    await progress.update(thinking="Gathering server status...", tool="server_status")
                elif tool_name == "manage_project":
                    action = tool_args.get("action", "")
                    await progress.update(thinking=f"Managing project: {action}", tool="manage_project")
                elif tool_name == "query_memory":
                    action = tool_args.get("action", "")
                    await progress.update(thinking=f"Querying memory: {action}", tool="query_memory")
                elif is_coding_tool(tool_name):
                    await progress.add_tool_call("coding", tool_name)
            else:
                if "__" in tool_name:
                    server, tool = tool_name.split("__", 1)
                    await message.reply(f"\U0001f527 [{server}] {tool}")
                elif tool_name == "run_shell":
                    cmd_preview = tool_args.get("command", "")[:100]
                    await message.reply(f"\U0001f527 `{cmd_preview}`")
                elif tool_name == "write_file":
                    path = tool_args.get("path", "")
                    await message.reply(f"\U0001f4dd Writing to `{path}`")
                elif tool_name == "server_status":
                    await message.reply("\U0001f4ca Gathering server status...")
                elif tool_name == "manage_project":
                    action = tool_args.get("action", "")
                    await message.reply(f"\U0001f4cb Managing project: {action}")
                elif tool_name == "query_memory":
                    action = tool_args.get("action", "")
                    await message.reply(f"\U0001f9e0 Querying memory: {action}")
                elif is_coding_tool(tool_name):
                    await message.reply(f"\U0001f4bb {tool_name}")

            # Execute tool
            result = await execute_tool_v2(
                message, tool_name, tool_args,
                project=project,
                channel_id=channel_id or message.channel.id,
            )

            # Phase 4.2: Try to render a rich embed for structured tool results
            if "__" in tool_name:
                embed = RichEmbedBuilder.build_from_tool_result(tool_name, tool_args, result)
                if embed:
                    try:
                        await message.reply(embed=embed)
                    except discord.HTTPException:
                        pass  # Fall back to text if embed fails

            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
            }
            messages.append(tool_msg)
            tool_messages.append(tool_msg)

            # Log state-modifying tool calls to change_log
            _cl_id = -1
            if tool_name == "write_file":
                _cl_id = log_change(
                    actor="schubert",
                    action="write_file",
                    target=tool_args.get("path", ""),
                    description=f"Wrote file to {tool_args.get('path', '')}",
                    intent=str(message.content)[:500] if hasattr(message, 'content') else "",
                    outcome="pending",
                )
            elif tool_name == "run_shell":
                cmd = tool_args.get("command", "")
                _cl_id = log_change(
                    actor="schubert",
                    action="run_shell",
                    target="server",
                    description=f"Shell: {cmd[:200]}",
                    intent=str(message.content)[:500] if hasattr(message, 'content') else "",
                    outcome="pending",
                )
            elif "__" in tool_name and "write_file" in tool_name:
                _cl_id = log_change(
                    actor="schubert",
                    action="mcp_write_file",
                    target=tool_args.get("path", ""),
                    description=f"MCP file write to {tool_args.get('path', '')}",
                    intent=str(message.content)[:500] if hasattr(message, 'content') else "",
                    outcome="pending",
                )

            # Update outcome based on result
            if _cl_id >= 0:
                success = "error" not in str(result).lower()[:100]
                update_change_outcome(_cl_id, "success" if success else "failed",
                                      {"result": str(result)[:500]})

            log(f"Tool {tool_name} result: {result[:200]}", "INFO")

        log("Agent loop reached max iterations", "WARN")
        return f"⏱️ I reached the maximum number of steps ({MAX_ITERATIONS}) without completing.", tool_messages
    
    finally:
        # Stop typing indicator
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Agent loop (voice mode) — V2
# ---------------------------------------------------------------------------


async def run_agent_loop_voice_v2(
    text_channel: discord.TextChannel,
    user_input: str,
    project: ProjectConfig | None = None,
    channel_id: int = 0,
) -> str:
    """Run the agent loop for voice mode. Returns text for TTS."""
    start_time = time.time()

    voice_prompt = SYSTEM_PROMPT + VOICE_PROMPT_ADDITION
    messages: list = [
        {"role": "system", "content": voice_prompt},
    ]

    # Inject recalled memories if available
    if memory_store:
        try:
            recalled = memory_store.recall(user_input)
            if recalled:
                messages.append({"role": "system", "content": recalled})
        except Exception:
            pass

    # Add session history if available
    if session_manager and channel_id:
        history = session_manager.get_history(channel_id)
        # Sanitize history — strip orphaned tool messages
        history = _sanitize_session_history(history)
        messages.extend(history)

    messages.append({"role": "user", "content": user_input})

    # Build tools
    tools = context_builder.build_tools(
        project=project,
        mcp_client=mcp_client,
        legacy_tools=get_legacy_tools(),
    )

    log(f"Voice agent loop started for: {user_input[:200]}", "INFO")
    
    # Start typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(text_channel, stop_typing))

    try:
        for iteration in range(MAX_ITERATIONS):
            elapsed = time.time() - start_time
            if elapsed > AGENT_TIMEOUT:
                return "I ran out of time on that one, Captain."

            log(f"Voice LLM call iteration {iteration + 1}/{MAX_ITERATIONS}", "INFO")
        response = await llm_chat(messages, tools)

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

            # Store in memory
            if memory_store:
                try:
                    memory_store.store(
                        f"User: {user_input}\nAssistant: {content}",
                        metadata={
                            "project": project.name if project else "default",
                            "session_id": str(channel_id),
                        },
                        event_type="conversation",
                    )
                except Exception:
                    pass

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

            if "__" in tool_name:
                server, tool = tool_name.split("__", 1)
                await text_channel.send(f"🔧 [{server}] {tool}")
            elif tool_name == "run_shell":
                cmd_preview = tool_args.get("command", "")[:100]
                await text_channel.send(f"🔧 `{cmd_preview}`")
            elif tool_name == "write_file":
                path = tool_args.get("path", "")
                await text_channel.send(f"📝 Writing to `{path}`")
            elif tool_name == "server_status":
                await text_channel.send("📊 Gathering server status...")

            result = await execute_tool_v2_voice(
                text_channel, tool_name, tool_args,
                project=project,
                channel_id=channel_id,
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
            })

        return "I reached my limit on that task, Captain."
    
    finally:
        # Stop typing indicator
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Voice pipeline: STT, TTS, audio playback (preserved from V1)
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
    if not pcm_data or len(pcm_data) < 1000:
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
                timeout=aiohttp.ClientTimeout(total=30),
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
                "text": text[:500],
                "model_id": ELEVENLABS_TTS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
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

            # 3. Determine project for this channel
            channel_id = self.text_channel.id
            project = project_registry.get_project_for_channel(channel_id)
            if project is None:
                project = project_registry.get_project("default")

            # 4. LLM agent loop (voice mode, V2)
            response = await run_agent_loop_voice_v2(
                self.text_channel, transcript,
                project=project,
                channel_id=channel_id,
            )
            if not response:
                response = "I didn't catch that, Captain."

            log(f"Voice response: {response[:200]}", "INFO")
            await self.text_channel.send(f"⚓ {response[:1900]}")

            # 5. TTS
            self.state = "speaking"
            mp3_data = await synthesize_speech(response)

            if mp3_data:
                # 6. Play audio
                await play_tts_audio(self.vc, mp3_data)

            # 7. Resume listening
            self.state = "listening"

        except Exception as e:
            log(f"Voice processing error: {e}", "ERROR")
            self.state = "listening"

    def stop(self):
        """Stop the voice session."""
        self.state = "idle"
        self.audio_buffer = b""


# ---------------------------------------------------------------------------
# Level 1 quick commands (no LLM cost) — preserved from V1
# ---------------------------------------------------------------------------


def cmd_status() -> discord.Embed:
    """Full server health snapshot."""
    code, uptime_out = run_command("uptime -p 2>/dev/null || uptime", timeout=10)
    code, disk_out = run_command(
        "df -h / 2>/dev/null | awk 'NR==1{print \"Size  Used  Avail  Use%\"} NR>1{printf \"%-5s %-5s %-6s %s\\n\", $2, $3, $4, $5}'",
        timeout=10,
    )
    code, mem_out = run_command("free -h | awk 'NR==1{print \"      total used avail\"} /^Mem:/{printf \"Mem:  %-5s %-5s %s\\n\", $2, $3, $7} /^Swap:/{printf \"Swap: %-5s %-5s %s\\n\", $2, $3, $4}'", timeout=10)
    code, failed_out = run_command(
        "systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $2}'",
        timeout=10,
    )
    code, svc_count = run_command(
        "systemctl list-units --type=service --state=active --no-pager --no-legend | wc -l",
        timeout=10,
    )

    failed_lines = [l for l in failed_out.strip().splitlines() if l.strip()]
    has_failures = bool(failed_lines)

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
            value="\n".join(failed_lines)[:500],
            inline=False,
        )
        embed.description = f"⚠️ {len(failed_lines)} failed service(s)"
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
    code, cpu_out = run_command("ps aux --sort=-pctcpu | head -11", timeout=10)
    code, mem_out = run_command("ps aux --sort=-pctmem | head -11", timeout=10)
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


# ---------------------------------------------------------------------------
# Help command (V2 — updated with new commands)
# ---------------------------------------------------------------------------


def cmd_help() -> discord.Embed:
    """Show available commands and agent capabilities."""
    embed = discord.Embed(
        title="⚓ Admiral Schubert V2 — Multi-Project Agent with MCP & Memory",
        description=(
            "Aye, Captain. I'm Admiral Schubert, commander of the good ship Schubert. "
            "I keep all services shipshape, investigate troubled waters, and patch leaks "
            "before they sink you. I now have MCP tool access (GitHub, Gmail, etc.), "
            "persistent memory, and multi-project channel support. I can work via text "
            "or voice — ask me anything."
        ),
        color=COLOR_AGENT,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Quick Commands", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!model", value="Switch LLM model (shows dropdown with Palmyra, Claude, GPT-4o, Gemini, Grok, Ollama)", inline=False)
    embed.add_field(name="!status", value="Full server health (services, disk, RAM, uptime)", inline=False)
    embed.add_field(name="!services", value="List all active systemd services", inline=False)
    embed.add_field(name="!logs [service]", value="Recent logs for a service", inline=False)
    embed.add_field(name="!restart <service>", value="Restart any service (critical services need confirmation)", inline=False)
    embed.add_field(name="!disk, !mem, !procs, !net", value="System info (disk, memory, processes, network)", inline=False)
    embed.add_field(name="Project & Session", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!project <subcommand>", value="Create, bind, list, info, set, delete projects", inline=False)
    embed.add_field(name="!session <subcommand>", value="Info, clear, summary, list sessions", inline=False)
    embed.add_field(name="!memory <subcommand>", value="Search, stats, recent, entity — query persistent memory", inline=False)
    embed.add_field(name="!run-playbook <key>", value="Trigger a WRITER Agent playbook via webhook (e.g. stratum-ai-news)", inline=False)
    embed.add_field(name="Voice Commands", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!join", value="Join your voice channel — speak and I shall respond", inline=False)
    embed.add_field(name="!leave", value="Leave the voice channel", inline=False)
    embed.add_field(name="Agent Mode", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(
        name="Any message",
        value=(
            "Send a natural language request and I'll investigate, use MCP tools, "
            "recall memories, and respond autonomously. You can also ask me to set up "
            "channels and projects in natural language — no need to memorize commands."
        ),
        inline=False,
    )
    embed.add_field(name="!mcp", value="Show MCP server connection status and tool count", inline=False)
    embed.set_footer(
        text=(
            f"Model: {LLM_MODEL} | Rate limit: {RATE_LIMIT_PER_MIN}/min | "
            f"Max iterations: {MAX_ITERATIONS} | Timeout: {AGENT_TIMEOUT}s"
        )
    )
    return embed


def cmd_mcp_status() -> discord.Embed:
    """Show MCP server connection status."""
    if not mcp_client:
        return discord.Embed(
            title="❌ MCP client not initialized",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    status = mcp_client.get_status()
    total_tools = len(mcp_client.get_tool_names())

    lines = []
    connected_count = 0
    for s in status:
        icon = "✅" if s["connected"] else "❌"
        tool_count = s["tools"] if s["connected"] else 0
        lines.append(f"{icon} **{s['name']}** — {tool_count} tools")
        if s["connected"]:
            connected_count += 1

    embed = discord.Embed(
        title=f"🔌 MCP Servers ({connected_count}/{len(status)} connected, {total_tools} total tools)",
        description="\n".join(lines),
        color=COLOR_SUCCESS if connected_count > 0 else COLOR_ERROR,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


# ---------------------------------------------------------------------------
# Multi-LLM Model Selection (Phase 6)
# ---------------------------------------------------------------------------

class ModelSelectView(ui.View):
    """Dropdown for selecting an LLM model at runtime."""

    def __init__(self):
        super().__init__(timeout=60)
        self.selected_model = None

        options = []
        for category, models in MODEL_CATEGORIES.items():
            for model in models:
                is_current = model == LLM_MODEL
                label = model.split("/")[-1]
                options.append(
                    discord.SelectOption(
                        label=label[:100],
                        value=model,
                        description=category[:100],
                        emoji="\u2705" if is_current else None,
                    )
                )

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


async def handle_model_command(message: discord.Message, args: list):
    """Handle !model command — show current model, allow switching."""
    global LLM_MODEL

    if args:
        # Direct model switch
        new_model = args[0].strip()
        all_models = []
        for models in MODEL_CATEGORIES.values():
            all_models.extend(models)
        if new_model in all_models:
            old_model = LLM_MODEL
            LLM_MODEL = new_model
            log(f"Model switched from {old_model} to {LLM_MODEL}", "INFO")
            await message.reply(f"\u2705 Model switched: `{old_model}` \u2192 `{LLM_MODEL}`")
        else:
            await message.reply(f"\u274c Unknown model: `{new_model}`\nUse `!model` to see available models.")
        return

    # Show model selection UI
    embed = discord.Embed(
        title="\U0001f9e0 LLM Model Selection",
        description=f"**Current model:** `{LLM_MODEL}`\n\nSelect a model from the dropdown below, or use `!model <model_name>` to switch directly.",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )

    for category, models in MODEL_CATEGORIES.items():
        model_list = []
        for m in models:
            marker = " \u2190 **current**" if m == LLM_MODEL else ""
            model_list.append(f"`{m}`{marker}")
        embed.add_field(
            name=category,
            value="\n".join(model_list),
            inline=True,
        )

    embed.set_footer(text="Use !model <name> to switch | !models to see all")

    view = ModelSelectView()
    await message.reply(embed=embed, view=view)

    if await view.wait():
        return  # Timed out

    if view.selected_model:
        old_model = LLM_MODEL
        LLM_MODEL = view.selected_model
        log(f"Model switched from {old_model} to {LLM_MODEL} (via dropdown)", "INFO")
        await message.reply(f"\u2705 Model switched: `{old_model}` \u2192 `{LLM_MODEL}`")



# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    log(f"Admiral Schubert V2 reporting for duty as {bot.user} (ID: {bot.user.id})", "INFO")
    log(f"Commanding channel {BOT_CHANNEL_ID}, serving Captain {ADMIN_USER_ID}", "INFO")
    log(f"LLM model: {LLM_MODEL} via {LITELLM_URL}", "INFO")
    log(f"Voice TTS: ElevenLabs {SCHUBERT_VOICE_ID} | STT: Deepgram {DEEPGRAM_MODEL}", "INFO")
    if mcp_client:
        total_tools = len(mcp_client.get_tool_names())
        log(f"MCP: {total_tools} tools available across all servers", "INFO")
    if memory_store:
        try:
            stats = memory_store.get_stats()
            log(f"Memory: {stats['redis_memories']} memories, {stats['entities']} entities, {stats['facts']} facts", "INFO")
        except Exception:
            log("Memory: stats unavailable", "WARN")
    # Phase 5.1: Start the scheduler after the bot is ready
    if scheduler:
        try:
            await scheduler.start()
            log("Scheduler started — background sweeps active", "INFO")
        except Exception as e:
            log(f"Scheduler start failed: {e}", "WARN")
    # Phase 5.3: Start the webhook handler after the bot is ready
    # Playbook relay: create BEFORE webhook handler so routes register before router freeze
    global webhook_handler, playbook_relay
    try:
        playbook_relay = PlaybookRelay(bot, BOT_CHANNEL_ID)
        relay_routes_fn = playbook_relay.add_routes if playbook_relay else None
        webhook_handler = WebhookHandler(bot, BOT_CHANNEL_ID, add_routes_fn=relay_routes_fn)
        await webhook_handler.start()
        log("Webhook handler started on port 8095", "INFO")
        if playbook_relay:
            log(f"Playbook relay active: {len(playbook_relay.playbook_configs)} playbook(s) configured", "INFO")
    except Exception as e:
        log(f"Webhook handler / playbook relay start failed (non-fatal): {e}", "WARN")


@bot.event
async def on_message(message: discord.Message):
    global active_voice_session

    if message.author == bot.user:
        return

    # --- Check if another agent is specifically mentioned ---
    # If another bot is mentioned (not Admiral), suppress Admiral's response
    OTHER_BOT_IDS = {
        1539047471899086988: "proctor",
        1538766501035642890: "architect",
        1538817623045832746: "quartermaster",
        1538818587119067206: "cartographer",
        1539047086597873684: "dr_voss",
    }
    
    for bot_id in OTHER_BOT_IDS.keys():
        if f"<@{bot_id}>" in message.content or f"<@!{bot_id}>" in message.content:
            # Another agent is specifically mentioned - don't respond
            return

    # --- Playbook relay: check if this is a reply to a relay question ---
    if playbook_relay and message.reference and message.reference.message_id:
        qid = playbook_relay.get_question_id_for_message(
            message.reference.message_id
        )
        if qid:
            answer = message.content.strip()
            playbook_relay.resolve_question(qid, answer)
            await message.add_reaction("✅")
            return

    # --- Fleet delegation: check for FLEET responses from subagents ---
    if is_fleet_message(message.content):
        parsed = parse_fleet_message(message.content)
        if parsed and parsed["to_agent"] == "schubert" and parsed["status"]:
            chain_id = parsed["chain_id"]
            part = parsed.get("part", 0)
            total_parts = parsed.get("total_parts", 0)
            log(f"Received FLEET response for chain {chain_id} from {parsed['from_agent']} (part={part}/{total_parts})", "INFO")

            # Multi-part response handling
            if total_parts > 1:
                # Accumulate parts before resolving
                if chain_id not in _pending_delegation_parts:
                    _pending_delegation_parts[chain_id] = {}
                _pending_delegation_parts[chain_id][part] = parsed["task"]

                # Check if all parts received
                if len(_pending_delegation_parts[chain_id]) >= total_parts:
                    # Assemble in order
                    assembled = "\n".join(
                        _pending_delegation_parts[chain_id][i]
                        for i in range(1, total_parts + 1)
                        if i in _pending_delegation_parts[chain_id]
                    )
                    del _pending_delegation_parts[chain_id]

                    if chain_id in _pending_delegations:
                        future = _pending_delegations.pop(chain_id)
                        if not future.done():
                            future.set_result(assembled)
                    return
                else:
                    # Still waiting for more parts
                    return
            else:
                # Single-part response — resolve immediately
                if chain_id in _pending_delegations:
                    future = _pending_delegations.pop(chain_id)
                    if not future.done():
                        future.set_result(parsed["task"])
                    return
                else:
                    log(f"FLEET response for unknown chain {chain_id} — ignoring", "WARN")
                    return
        elif parsed and parsed["to_agent"] == "schubert" and not parsed["status"]:
            # A delegation TO schubert (from another agent) — process as a task
            log(f"Received FLEET delegation from {parsed['from_agent']}", "INFO")
            # Fall through to normal processing with the task as input
            # (remove the FLEET tag from the input)
            pass

    # --- Multi-agent channel routing (before channel authorization) ---
    if is_multi_agent_channel(message.channel.id) and _multi_agent_manager:
        should = await _multi_agent_manager.should_respond(
            message, bot.user.id, ADMIN_USER_ID
        )
        if not should:
            ctx = get_shared_context()
            ctx.add_message(
                message.channel.id, message.id, str(message.author),
                message.content, time.time(), message.author.bot
            )
            return
        _multi_agent_manager.mark_responded(message.channel.id)
        # In multi-agent channels, skip project/channel authorization
        # Process the message directly
        content = message.content.strip()
        if content.startswith("!"):
            # Handle quick commands
            pass  # Fall through to command handling
        else:
            # Process as natural language agent request
            project = project_registry.get_project("default") if project_registry else None
            # Skip the channel authorization check below
            # Fall through to agent processing with default project
            
    else:
        # --- Channel authorization (V2: any bound channel or default channel) ---
        project = project_registry.get_project_for_channel(message.channel.id)
        is_default_channel = message.channel.id == BOT_CHANNEL_ID

        if project is None and not is_default_channel:
            # Unbound channel — check if the user is trying to set up this channel
            # or if they mentioned the bot. If so, respond with a setup prompt
            # instead of silently ignoring.
            content_lower = content.lower()
            setup_keywords = [
                "set up", "setup", "bind", "project", "channel",
                "create channel", "new channel", "provision",
                "github repo", "map this", "assign this",
            ]
            bot_mentioned = bot.user and bot.user.mentioned_in(message)

            if bot_mentioned or any(kw in content_lower for kw in setup_keywords):
                # Respond in the unbound channel with a setup prompt
                existing_projects = project_registry.list_projects()
                project_names = [p.name for p in existing_projects]
                await message.reply(
                    f"⚓ Ahoy, Captain! This channel isn't bound to a project yet.\n\n"
                    f"You can ask me in natural language to set it up. For example:\n"
                    f"  • \"Create a channel called my-repo and map it to my GitHub project\"\n"
                    f"  • \"Bind this channel to the tango project\"\n"
                    f"  • \"Set up a new project called vinifera with workdir /opt/vinifera\"\n\n"
                    f"**Existing projects:** {', '.join(project_names) if project_names else '(none yet)'}\n\n"
                    f"Or type `!help` to see all available commands."
                )
            return  # Unbound channel, ignore

        if project is None:
            project = project_registry.get_project("default")

    # --- Admin check (preserved from V1) ---
    if message.author.id != ADMIN_USER_ID and message.author.id not in AUTHORIZED_AGENT_IDS:
        log(
            f"Unauthorized message from user {message.author.id} "
            f"({message.author}): {message.content[:100]}",
            "WARN",
        )
        return
    if message.author.id in AUTHORIZED_AGENT_IDS:
        log(
            f"Authorized agent message from {message.author.id} "
            f"({message.author}): {message.content[:100]}",
            "INFO",
        )

    # --- Rate limiting (preserved from V1) ---
    if not check_rate_limit(message.author.id):
        await message.reply(
            f"⏱️ Rate limit exceeded. Max {RATE_LIMIT_PER_MIN} messages per minute."
        )
        return

    content = message.content.strip()

    # --- Handle ! prefix commands ---
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
            # --- V1 quick commands (preserved) ---
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

            elif command == "playbook" or command == "run-playbook":
                # Trigger a WRITER Agent playbook via webhook
                if not playbook_relay:
                    await message.reply("\u274c Playbook relay not initialized.")
                    return
                playbook_key = args[0] if args else ""
                if not playbook_key:
                    playbooks = playbook_relay.list_playbooks()
                    if playbooks:
                        plist = "\n".join(
                            f"  \u2022 `{p['key']}` \u2014 {p['name']}" for p in playbooks
                        )
                    else:
                        plist = "  (none configured)"
                    await message.reply(
                        "\u2693 **Playbook Webhook Relay**\n\n"
                        "Usage: `!run-playbook <key> [inputs_json]`\n\n"
                        f"**Available playbooks:**\n{plist}"
                    )
                    return
                # Parse optional inputs JSON from remaining args
                inputs = []
                if len(args) > 1:
                    inputs_str = " ".join(args[1:])
                    try:
                        inputs = json.loads(inputs_str)
                    except json.JSONDecodeError:
                        await message.reply(
                            f"\u274c Invalid JSON inputs: `{inputs_str}`"
                        )
                        return

                # Check if this playbook has a pre-trigger question
                if not inputs and playbook_relay:
                    config = playbook_relay.playbook_configs.get(playbook_key, {})
                    pre_question = config.get("pre_trigger_question", "")
                    pre_var = config.get("pre_trigger_variable", "task_description")
                    if pre_question:
                        embed_q = discord.Embed(
                            title=f"\U0001f527 {config.get('name', playbook_key)}",
                            description=pre_question,
                            color=0x5865F2,
                        )
                        embed_q.set_footer(text="Reply to this message to answer")
                        q_msg = await message.reply(embed=embed_q)
                        try:
                            reply_msg = await bot.wait_for(
                                "message",
                                timeout=600,
                                check=lambda m: (
                                    m.channel.id == message.channel.id
                                    and m.author.id == message.author.id
                                    and m.id != message.id
                                ),
                            )
                            user_answer = reply_msg.content
                            embed_a = discord.Embed(
                                title=f"\U0001f527 {config.get('name', playbook_key)}",
                                description=f"\u2705 You said: {user_answer[:200]}",
                                color=0x00ff00,
                            )
                            await q_msg.edit(embed=embed_a)
                            inputs = [{"id": pre_var, "value": [user_answer]}]
                        except asyncio.TimeoutError:
                            embed_t = discord.Embed(
                                title=f"\U0001f527 {config.get('name', playbook_key)}",
                                description="\u23f0 Timed out waiting for your response. Triggering with default inputs.",
                                color=0xff0000,
                            )
                            await q_msg.edit(embed=embed_t)

                await message.reply(f"\U0001f680 Triggering playbook `{playbook_key}`...")
                result = await playbook_relay.trigger_playbook(playbook_key, inputs)
                if "error" in result:
                    await message.reply(f"\u274c Playbook trigger failed: {result['error']}")
                elif "thread_id" in result:
                    await message.reply(
                        f"\u2705 Playbook `{playbook_key}` started!\n"
                        f"Thread ID: `{result['thread_id']}`\n"
                        f"Status: {result.get('status', 'unknown')}\n\n"
                        f"If the playbook has questions, they will appear here. "
                        f"Reply to question messages to answer them."
                    )
                else:
                    await message.reply(f"\u26a0\ufe0f Unexpected response: `{result}`")

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

            # --- V2: MCP status command ---
            elif command == "mcp":
                await message.reply(embed=cmd_mcp_status())

            # --- Phase 4: Interactive setup wizard ---
            elif command == "setup":
                view = SetupWizardView(
                    project_registry,
                    guild=message.guild,
                    channel=message.channel,
                )
                await message.reply(
                    embed=get_setup_wizard_embed(),
                    view=view,
                )
                # Wait for modal submission (non-blocking — the view handles interaction)
                modal_result = await view.wait_for_modal()
                if modal_result:
                    # Process the new project creation
                    channel_name = modal_result.get("channel_name", "")
                    project_name = modal_result.get("project_name", "")
                    workdir = modal_result.get("workdir", "")
                    github_repo = modal_result.get("github_repo", "")
                    mcp_servers_str = modal_result.get("mcp_servers", "")

                    # Create the channel
                    safe_name = re.sub(r'[^a-z0-9-]', '', channel_name.lower().replace(" ", "-").replace("_", "-"))
                    if safe_name and message.guild:
                        try:
                            new_channel = await message.guild.create_text_channel(safe_name)
                            # Create the project
                            description = modal_result.get("description", "")
                            if github_repo:
                                repo_tag = f"GitHub repo: {github_repo}"
                                description = f"{description}. {repo_tag}" if description else repo_tag
                            mcp_servers = [s.strip() for s in mcp_servers_str.split(",") if s.strip()] if mcp_servers_str else []
                            project_registry.create_project(
                                name=project_name,
                                description=description,
                                workdir=workdir,
                                enabled_mcp_servers=mcp_servers,
                            )
                            project_registry.bind_channel(new_channel.id, project_name)
                            await message.reply(
                                f"✅ Created channel `#{safe_name}` and bound it to project `{project_name}`.\n"
                                f"   Workdir: `{workdir or 'not set'}`\n"
                                f"   MCP: {', '.join(mcp_servers) if mcp_servers else 'all'}\n"
                                f"   GitHub: `{github_repo or 'not set'}`"
                            )
                        except Exception as e:
                            await message.reply(f"❌ Setup error: {e}")

                # Check for bind selection
                bind_project = await view.wait_for_bind()
                if bind_project and message.guild:
                    try:
                        project_registry.bind_channel(message.channel.id, bind_project)
                        await message.reply(f"✅ Bound `#{message.channel.name}` to project `{bind_project}`")
                    except Exception as e:
                        await message.reply(f"❌ Bind error: {e}")

            # --- Phase 5: Manual proactive sweep ---
            elif command == "sweep":
                if scheduler:
                    embed = await scheduler.run_manual_sweep()
                    await message.reply(embed=embed)
                else:
                    await message.reply("Scheduler not initialized.")

            # --- Phase 6: Multi-LLM routing ---
            elif command == "model" or command == "models":
                await handle_model_command(message, args)

            # --- Phase 4: Enhanced help ---
            elif command == "help":
                await message.reply(embed=get_phase4_help_embed())

            # --- V2: Project management commands ---
            elif command == "project":
                await handle_project_command(message, args)

            # --- V2: Session management commands ---
            elif command == "session":
                await handle_session_command(message, args)

            # --- V2: Memory commands ---
            elif command == "memory":
                await handle_memory_command(message, args)

            elif command == "agent":
                agent_input = " ".join(args)
                if not agent_input:
                    await message.reply("Usage: `!agent <your request>`")
                    return
                await run_agent_with_update_v2(message, agent_input, project)

            else:
                await message.reply(
                    f"❓ Unknown command: `!{command}`. Type `!help` for "
                    f"available commands, or just send a natural language "
                    f"message to use the autonomous agent."
                )

        except Exception as e:
            log(f"Error handling command !{command}: {e}", "ERROR")
            import traceback
            log(f"TRACEBACK: {traceback.format_exc()}", "ERROR")
            await message.reply(f"❌ Error: {str(e)[:500]}")

    else:
        # --- Natural language message — trigger V2 agent loop ---
        log(f"Agent message from {message.author} in channel {message.channel.id}: {content[:200]}", "INFO")
        await run_agent_with_update_v2(message, content, project)


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


@bot.event
async def on_thread_create(thread):
    """Optional: acknowledge new threads in bound channels."""
    project = project_registry.get_project_for_channel(thread.parent_id)
    if project is None:
        return  # Thread in unbound channel, ignore
    log(f"New thread {thread.id} in channel {thread.parent_id} (project: {project.name})", "INFO")


# ---------------------------------------------------------------------------
# Slash command handlers (V2)
# ---------------------------------------------------------------------------


async def handle_project_command(message: discord.Message, args: list):
    """Handle !project subcommands."""
    if not args:
        await message.reply(
            "📋 **Project commands:**\n"
            "`!project list` — List all projects\n"
            "`!project create <name> [description]` — Create a new project\n"
            "`!project bind <name>` — Bind this channel to a project\n"
            "`!project unbind` — Unbind this channel\n"
            "`!project info` — Show this channel's project\n"
            "`!project set <name> <key> <value>` — Update a project setting\n"
            "`!project delete <name>` — Delete a project\n\n"
            "Or just ask me in natural language: \"set up this channel for my GitHub project\""
        )
        return

    subcommand = args[0].lower()

    if subcommand == "list":
        projects = project_registry.list_projects()
        if not projects:
            await message.reply("No projects configured.")
            return
        lines = [f"📋 **Projects ({len(projects)}):**\n"]
        for p in projects:
            bindings = len(p.channel_bindings)
            lines.append(
                f"  • **{p.name}** — {p.description[:80] or '(no description)'}\n"
                f"    Workdir: `{p.workdir or '(not set)'}` | "
                f"Channels: {bindings} | "
                f"MCP: {p.enabled_mcp_servers or '(all)'}"
            )
        await message.reply("\n".join(lines))

    elif subcommand == "create":
        if len(args) < 2:
            await message.reply("Usage: `!project create <name> [description]`")
            return
        name = args[1]
        description = " ".join(args[2:]) if len(args) > 2 else ""
        try:
            proj = project_registry.create_project(name=name, description=description)
            await message.reply(
                f"✅ Created project **{name}**.\n"
                f"Use `!project bind {name}` to bind this channel to it.\n"
                f"Use `!project set {name} workdir /path/to/project` to set the working directory."
            )
        except ValueError as e:
            await message.reply(f"❌ {e}")

    elif subcommand == "bind":
        if len(args) < 2:
            await message.reply("Usage: `!project bind <name>`")
            return
        name = args[1]
        try:
            project_registry.bind_channel(message.channel.id, name)
            await message.reply(f"✅ Bound channel <#{message.channel.id}> to project **{name}**.")
        except ValueError as e:
            await message.reply(f"❌ {e}")

    elif subcommand == "unbind":
        if project_registry.unbind_channel(message.channel.id):
            await message.reply("✅ Unbound this channel. It now uses the default project.")
        else:
            await message.reply("This channel is not bound to any project.")

    elif subcommand == "info":
        proj = project_registry.get_project_for_channel(message.channel.id)
        if proj is None:
            await message.reply("This channel is not bound to any project.")
            return
        binding = project_registry.get_binding_info(message.channel.id)
        lines = [
            f"📋 **Project: {proj.name}**",
            f"Description: {proj.description or '(none)'}",
            f"Working directory: `{proj.workdir or '(not set)'}`",
            f"Channel binding: {binding[1] if binding else 'none'}",
            f"Enabled MCP servers: {proj.enabled_mcp_servers or '(all)'}",
            f"Context files: {proj.context_files or '(none)'}",
            f"Created: {proj.created_at[:19]}",
            f"Updated: {proj.updated_at[:19]}",
        ]
        await message.reply("\n".join(lines))

    elif subcommand == "set":
        if len(args) < 4:
            await message.reply(
                "Usage: `!project set <name> <key> <value>`\n"
                "Keys: description, workdir, system_prompt, enabled_mcp_servers (comma-separated), context_files (comma-separated)"
            )
            return
        name = args[1]
        key = args[2]
        value = " ".join(args[3:])

        updates = {}
        if key == "description":
            updates["description"] = value
        elif key == "workdir":
            updates["workdir"] = value
        elif key == "system_prompt":
            updates["system_prompt"] = value
        elif key == "enabled_mcp_servers":
            updates["enabled_mcp_servers"] = [s.strip() for s in value.split(",")]
        elif key == "context_files":
            updates["context_files"] = [f.strip() for f in value.split(",")]
        else:
            await message.reply(
                f"❌ Unknown key: `{key}`. Valid keys: description, workdir, system_prompt, enabled_mcp_servers, context_files"
            )
            return

        try:
            project_registry.update_project(name, updates)
            await message.reply(f"✅ Updated `{key}` for project **{name}**.")
        except ValueError as e:
            await message.reply(f"❌ {e}")

    elif subcommand == "delete":
        if len(args) < 2:
            await message.reply("Usage: `!project delete <name>`")
            return
        name = args[1]
        if name == "default":
            await message.reply("❌ Cannot delete the default project.")
            return
        if project_registry.delete_project(name):
            await message.reply(f"✅ Deleted project **{name}**.")
        else:
            await message.reply(f"❌ Project `{name}` not found.")

    else:
        await message.reply(f"❓ Unknown subcommand: `!project {subcommand}`. Type `!project` for help.")


async def handle_session_command(message: discord.Message, args: list):
    """Handle !session subcommands."""
    if not args:
        await message.reply(
            "💬 **Session commands:**\n"
            "`!session info` — Show current session info\n"
            "`!session clear` — Clear conversation history\n"
            "`!session summary` — Show session summary\n"
            "`!session list` — List all sessions"
        )
        return

    subcommand = args[0].lower()
    channel_id = message.channel.id
    thread_id = None
    if hasattr(message.channel, 'parent_id') and message.channel.parent_id is not None:
        thread_id = message.channel.id
        channel_id = message.channel.parent_id

    if subcommand == "info":
        info = session_manager.get_session_info(channel_id, thread_id=thread_id)
        if info is None:
            await message.reply("No session found for this channel.")
            return
        lines = [
            f"💬 **Session Info**",
            f"Session ID: `{info['session_id']}`",
            f"Project: {info['project_name']}",
            f"Messages exchanged: {info['message_count']}",
            f"Current history length: {info['current_history_length']}",
            f"Has summary: {'yes' if info['has_summary'] else 'no'}",
            f"Created: {info['created_at'][:19]}",
            f"Updated: {info['updated_at'][:19]}",
        ]
        if info.get("summary_preview"):
            lines.append(f"Summary preview: {info['summary_preview']}")
        await message.reply("\n".join(lines))

    elif subcommand == "clear":
        if session_manager.clear_session(channel_id, thread_id=thread_id):
            await message.reply("✅ Session history cleared. Starting fresh.")
        else:
            await message.reply("No session found to clear.")

    elif subcommand == "summary":
        session = session_manager.get_session(channel_id, thread_id=thread_id)
        if session is None or (not session.summary and not session.messages):
            await message.reply("No session history to summarize.")
            return
        if session.summary:
            await message.reply(f"📝 **Session summary:**\n{session.summary}")
        else:
            await message.reply("No summary yet — the session hasn't been windowed. Keep chatting!")

    elif subcommand == "list":
        sessions = session_manager.list_sessions()
        if not sessions:
            await message.reply("No sessions found.")
            return
        lines = [f"💬 **Sessions ({len(sessions)}):**\n"]
        for s in sessions:
            lines.append(
                f"  • `{s['session_id']}` — Project: {s['project_name']}, "
                f"Messages: {s['message_count']}, Updated: {s['updated_at'][:19]}"
            )
        await message.reply("\n".join(lines))

    else:
        await message.reply(f"❓ Unknown subcommand: `!session {subcommand}`. Type `!session` for help.")


async def handle_memory_command(message: discord.Message, args: list):
    """Handle !memory subcommands."""
    if not args:
        await message.reply(
            "🧠 **Memory commands:**\n"
            "`!memory search <query>` — Search memories semantically\n"
            "`!memory stats` — Show memory store statistics\n"
            "`!memory recent [project]` — Show recent memories\n"
            "`!memory entity <name>` — Look up an entity and its facts"
        )
        return

    if not memory_store:
        await message.reply("❌ Memory store not initialized.")
        return

    subcommand = args[0].lower()

    if subcommand == "search":
        query = " ".join(args[1:])
        if not query:
            await message.reply("Usage: `!memory search <query>`")
            return
        try:
            results = memory_store.search(query, k=5)
            if not results:
                await message.reply("No memories found.")
                return
            lines = [f"🧠 **Memory Search: '{query}'**"]
            for i, r in enumerate(results, 1):
                sim = r.get("similarity", 0)
                lines.append(f"{i}. [sim: {sim:.2f}] {r['text'][:200]}")
            await message.reply("\n".join(lines))
        except Exception as e:
            await message.reply(f"❌ Memory search error: {e}")

    elif subcommand == "stats":
        try:
            stats = memory_store.get_stats()
            lines = ["🧠 **Memory Store Stats**"]
            lines.append(f"  Redis memories: {stats['redis_memories']}")
            lines.append(f"  Entities: {stats['entities']}")
            lines.append(f"  Facts: {stats['facts']}")
            lines.append(f"  Events: {stats['events']}")
            lines.append(f"  Relationships: {stats['relationships']}")
            await message.reply("\n".join(lines))
        except Exception as e:
            await message.reply(f"❌ Memory stats error: {e}")

    elif subcommand == "recent":
        project = args[1] if len(args) > 1 else ""
        try:
            events = memory_store.get_recent(project=project, k=5)
            if not events:
                await message.reply("No recent memories.")
                return
            lines = ["🧠 **Recent Memories**"]
            for e in events:
                ts = e.get("timestamp", "")[:19] if e.get("timestamp") else ""
                lines.append(f"- [{ts}] [{e['event_type']}] {e['summary'][:150]}")
            await message.reply("\n".join(lines))
        except Exception as e:
            await message.reply(f"❌ Memory recent error: {e}")

    elif subcommand == "entity":
        name = args[1] if len(args) > 1 else ""
        if not name:
            await message.reply("Usage: `!memory entity <name>`")
            return
        try:
            entity = memory_store.get_entity(name)
            if not entity:
                await message.reply(f"Entity '{name}' not found.")
                return
            lines = [f"🧠 **Entity: {entity['name']}** (type: {entity['type']})"]
            if entity.get("facts"):
                lines.append("\n**Facts:**")
                for f in entity["facts"][:5]:
                    lines.append(f"  - {f['fact'][:200]}")
            if entity.get("related"):
                lines.append("\n**Related:**")
                for r in entity["related"][:5]:
                    lines.append(f"  - {r['name']} ({r['relationship']})")
            await message.reply("\n".join(lines))
        except Exception as e:
            await message.reply(f"❌ Memory entity error: {e}")

    else:
        await message.reply(f"❓ Unknown subcommand: `!memory {subcommand}`. Type `!memory` for help.")


# ---------------------------------------------------------------------------
# Phase 1/2/3 Initialization
# ---------------------------------------------------------------------------


async def init_v2():
    """Initialize Phase 1 (MCP), Phase 2 (projects/sessions), and Phase 3 (memory)."""
    global project_registry, session_manager, context_builder, mcp_client, memory_store

    # --- Phase 2: Project Registry ---
    log("Initializing Phase 2: Project Registry...", "INFO")
    project_registry = ProjectRegistry("/opt/Project-Tango/data/projects.json")
    project_registry.load()

    # Ensure the default project exists, bound to the V1 channel
    project_registry.ensure_default_project(
        channel_id=BOT_CHANNEL_ID,
        system_prompt=SYSTEM_PROMPT,
    )
    log(f"Project Registry: {len(project_registry.list_projects())} projects loaded", "INFO")

    # --- Phase 2: Session Manager ---
    log("Initializing Phase 2: Session Manager...", "INFO")
    session_manager = SessionManager("/opt/Project-Tango/data/sessions")
    log(f"Session Manager: {len(session_manager.list_sessions())} sessions found", "INFO")

    # --- Phase 2: Context Builder ---
    log("Initializing Phase 2: Context Builder...", "INFO")
    context_builder = ContextBuilder(base_system_prompt=SYSTEM_PROMPT)

    # --- Phase 3: Memory Store ---
    log("Initializing Phase 3: Memory Store...", "INFO")
    try:
        memory_store = MemoryStore()
        memory_store.init_db()  # Create tables if they don't exist

        # Initialize fleet agent registry
        fleet_agents = init_fleet_agents()
        log(f"Fleet agents initialized: {list(fleet_agents.keys())}", "INFO")
        stats = memory_store.get_stats()
        log(
            f"Memory Store initialized: {stats['redis_memories']} memories, "
            f"{stats['entities']} entities, {stats['facts']} facts",
            "INFO",
        )

        # Store a startup memory
        memory_store.store(
            "Dr. Cortex Bot started. Phase 1 (MCP), Phase 2 (projects/sessions), "
            "and Phase 3 (memory) all initialized.",
            metadata={"project": "default", "session_id": "system"},
            event_type="system",
        )
    except Exception as e:
        log(f"Memory Store initialization failed (non-fatal): {e}", "WARN")
        memory_store = None

    # --- Phase 1: MCP Client ---
    log("Initializing Phase 1: MCP Client...", "INFO")
    try:
        mcp_client = build_default_client()
        await mcp_client.connect_all()

        # Log status
        status = mcp_client.get_status()
        for s in status:
            if s["connected"]:
                log(f"[MCP] {s['name']}: {s['tools']} tools connected", "INFO")
            else:
                log(f"[MCP] {s['name']}: NOT CONNECTED (enabled={s['enabled']})", "WARN")

        total_tools = len(mcp_client.get_tool_names())
        log(f"[MCP] Total tools available: {total_tools}", "INFO")
    except Exception as e:
        log(f"MCP Client initialization failed (non-fatal): {e}", "WARN")
        mcp_client = None

    # --- Summary ---
    projects = project_registry.list_projects()
    log(f"V2 initialization complete:", "INFO")
    log(f"  Projects: {len(projects)}", "INFO")
    log(f"  Sessions: {len(session_manager.list_sessions())}", "INFO")
    log(f"  MCP tools: {len(mcp_client.get_tool_names()) if mcp_client else 0}", "INFO")
    log(f"  Memory: {'active' if memory_store else 'disabled'}", "INFO")

    # --- Phase 5.1: Scheduler ---
    global scheduler
    log("Initializing Phase 5.1: Scheduler...", "INFO")
    try:
        scheduler = Scheduler(bot, BOT_CHANNEL_ID, memory_store)
        log("Scheduler initialized (will start after bot connects)", "INFO")
    except Exception as e:
        log(f"Scheduler initialization failed (non-fatal): {e}", "WARN")
        scheduler = None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def async_main() -> int:
    log("=" * 60, "INFO")
    log("Dr. Cortex Bot — Multi-project agent with MCP, memory, and voice", "INFO")
    log(f"Model: {LLM_MODEL} via {LITELLM_URL}", "INFO")
    log(f"Voice: discord-ext-voice-recv + Deepgram + ElevenLabs", "INFO")
    log(f"MCP: dynamic tool discovery from multiple servers", "INFO")
    log(f"Memory: three-layer persistent (Redis + Postgres + Ollama)", "INFO")

    if not load_config():
        log("Configuration error — exiting", "CRITICAL")
        return 2

    # Initialize Phase 1/2/3 BEFORE connecting to Discord
    await init_v2()

    try:
        await bot.start(BOT_TOKEN)
    except KeyboardInterrupt:
        log("Bot stopped by keyboard interrupt", "INFO")
    except Exception as e:
        log(f"Bot crashed: {e}", "CRITICAL")
        import traceback
        log(f"TRACEBACK: {traceback.format_exc()}", "CRITICAL")
        return 1
    finally:
        # Graceful shutdown
        log("Shutting down...", "INFO")
        if session_manager:
            session_manager.save_all()
            log("Sessions saved", "INFO")
        if scheduler:
            await scheduler.stop()
            log("Scheduler stopped", "INFO")
        if webhook_handler:
            await webhook_handler.stop()
            log("Webhook handler stopped", "INFO")
        if mcp_client:
            await mcp_client.disconnect_all()
            log("MCP client disconnected", "INFO")
        if memory_store:
            memory_store.close()
            log("Memory store closed", "INFO")

    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
