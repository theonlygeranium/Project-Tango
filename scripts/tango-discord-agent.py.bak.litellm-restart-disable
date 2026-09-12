#!/usr/bin/env python3
"""
Tango Discord Agent — Level 3 autonomous agent for Project Tango operations.

An LLM-powered Discord bot that investigates issues, fixes code, restarts
services, and commits changes autonomously. Uses writer/claude-sonnet-4-5 via
LiteLLM for reasoning. Asks for confirmation only before git push operations.

Security:
- Admin allowlist: only DISCORD_ADMIN_USER_ID can issue commands
- Channel lock: bot only responds in DISCORD_BOT_CHANNEL_ID
- Hard blocks: rm -rf, mkfs, dd, forbidden services, AGENTS.md, .env commits,
  git push to main, package installs, shutdown/reboot, chmod 777
- Confirmation required: git push (to feature branches only)
- Loop safety: max 20 iterations, 5-minute timeout
- Full audit logging to /var/log/tango-discord-agent.log

Usage:
    python3 tango-discord-agent.py

Interaction:
    Natural language messages trigger the autonomous agent loop.
    Quick commands (prefixed with !) run without LLM cost:
        !status   — quick service health snapshot
        !health   — full 6-layer health check
        !logs     — recent tango-backend logs
        !restart  — restart a service (requires confirmation)
        !billing  — check ElevenLabs subscription
        !tts      — test TTS synthesis
        !help     — show available commands
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import aiohttp
import discord

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = "/opt/Project-Tango/.env"
ENV_FILE_POLYGLOT = "/opt/polyglot/.env.runtime"
LOG_FILE = "/var/log/tango-discord-agent.log"

# LLM
LITELLM_URL = "http://127.0.0.1:4000/v1"
LLM_MODEL = "writer/claude-sonnet-4-5"
LLM_TIMEOUT = 90          # seconds per LLM call
LLM_MAX_TOKENS = 4096
LLM_TEMPERATURE = 0.3

# Agent loop safety
MAX_ITERATIONS = 20
AGENT_TIMEOUT = 300       # 5 minutes total
TOOL_OUTPUT_LIMIT = 4000  # chars sent back to LLM per tool result
SHELL_TIMEOUT = 120       # seconds for shell commands

# Discord
RATE_LIMIT_PER_MIN = 10
RESTART_CONFIRM_TIMEOUT = 30

# Services
BACKEND_SERVICE = "tango-backend.service"
WEB_SERVICE = "tango-web.service"
LITELLM_SERVICE = "polyglot-litellm.service"
TTS_SERVICE = "tango-tts.service"

FORBIDDEN_SERVICES = {
    "caddy.service",
    "cloudflared.service",
    "postgresql@18-main.service",
    "tailscaled.service",
}

FORBIDDEN_SERVICE_PREFIXES = ("meetscribe", "foxtrot", "ollama")

SAFE_SERVICES = {BACKEND_SERVICE, WEB_SERVICE, LITELLM_SERVICE, TTS_SERVICE}

# ElevenLabs
ELEVENLABS_SUBSCRIPTION_URL = "https://api.us.elevenlabs.io/v1/user/subscription"
TTS_TEST_TEXT = "OK"
TTS_TEST_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"
TTS_TEST_MODEL = "eleven_flash_v2_5"

# Log viewing
LOG_LINES = 50

# Discord embed colors
COLOR_INFO = 0x5865F2     # blurple
COLOR_SUCCESS = 0x57F287  # green
COLOR_WARN = 0xFEE75C     # yellow
COLOR_ERROR = 0xED4245    # red
COLOR_AGENT = 0x9B59B6    # purple

# ---------------------------------------------------------------------------
# Guardrails — hard-blocked command patterns (never execute)
# ---------------------------------------------------------------------------

HARD_BLOCKED_PATTERNS = [
    (r"rm\s+-rf\s+/?(\s|$|\*|~)", "rm -rf on root or home filesystem"),
    (r"mkfs\b", "filesystem format"),
    (r"\bdd\s+if=", "raw disk write"),
    (r":\(\)\s*\{.*\};.*:", "fork bomb"),
    (r"\b(shutdown|reboot|halt|init\s+0|poweroff)\b", "system power control"),
    (r"\bchmod\s+777\b", "insecure world-writable permissions"),
    (r"\b(apt|apt-get)\s+install\b", "package installation"),
    (r"\bpip3?\s+install\b", "package installation"),
    (r"\bnpm\s+install\b", "package installation"),
    (r"git\s+push\s+.*\bmain\b", "push to main branch"),
    (r">\s*/etc/(passwd|shadow|fstab|sudoers)", "critical system file overwrite"),
]

# Patterns that require user confirmation before execution
CONFIRM_PATTERNS = [
    (r"\bgit\s+push\b", "git push"),
]

# File paths that cannot be overwritten via write_file tool
BLOCKED_WRITE_PATHS = [
    "AGENTS.md",
    "/opt/Project-Tango/AGENTS.md",
    ".env",
    "/opt/Project-Tango/.env",
]

# ---------------------------------------------------------------------------
# Globals (loaded from .env at startup)
# ---------------------------------------------------------------------------

BOT_TOKEN = ""
ADMIN_USER_ID = 0
BOT_CHANNEL_ID = 0
LITELLM_MASTER_KEY = ""

_command_timestamps: dict[int, list[float]] = {}
_pending_restarts: dict[int, tuple[str, float]] = {}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(message: str, level: str = "INFO") -> None:
    """Write a timestamped log line to the log file and stdout."""
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
    """Load environment variables from .env files."""
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
    """Load bot configuration from .env. Returns True if all required values found."""
    global BOT_TOKEN, ADMIN_USER_ID, BOT_CHANNEL_ID, LITELLM_MASTER_KEY

    env = load_env()
    BOT_TOKEN = env.get("DISCORD_BOT_TOKEN", "")
    LITELLM_MASTER_KEY = env.get(
        "LITELLM_MASTER_KEY", os.environ.get("LITELLM_MASTER_KEY", "")
    )
    admin_id_str = env.get("DISCORD_ADMIN_USER_ID", "")
    channel_id_str = env.get("DISCORD_BOT_CHANNEL_ID", "")

    if not BOT_TOKEN:
        log("DISCORD_BOT_TOKEN not found in .env", "CRITICAL")
        return False
    if not LITELLM_MASTER_KEY:
        log("LITELLM_MASTER_KEY not found in .env", "CRITICAL")
        return False
    if not admin_id_str:
        log("DISCORD_ADMIN_USER_ID not found in .env", "CRITICAL")
        return False
    if not channel_id_str:
        log("DISCORD_BOT_CHANNEL_ID not found in .env", "CRITICAL")
        return False

    try:
        ADMIN_USER_ID = int(admin_id_str)
        BOT_CHANNEL_ID = int(channel_id_str)
    except ValueError:
        log("Invalid admin or channel ID format", "CRITICAL")
        return False

    log(
        f"Config loaded: admin={ADMIN_USER_ID}, channel={BOT_CHANNEL_ID}, "
        f"model={LLM_MODEL}",
        "INFO",
    )
    return True


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


def run_command(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Run a shell command, return (exit_code, output)."""
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
    """Check if command matches any hard-blocked pattern. Returns reason or None."""
    for pattern, reason in HARD_BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def check_forbidden_service(command: str) -> str | None:
    """Check if command operates on a forbidden service."""
    for svc in FORBIDDEN_SERVICES:
        if svc in command:
            return svc
    for prefix in FORBIDDEN_SERVICE_PREFIXES:
        if re.search(rf"\b{prefix}\w*", command, re.IGNORECASE):
            return prefix
    return None


def needs_confirmation(command: str) -> str | None:
    """Check if command needs user confirmation. Returns reason or None."""
    for pattern, reason in CONFIRM_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def is_blocked_write_path(path: str) -> bool:
    """Check if a file path is blocked from writing."""
    abs_path = os.path.abspath(path)
    for blocked in BLOCKED_WRITE_PATHS:
        if abs_path == os.path.abspath(blocked) or abs_path.endswith(blocked):
            return True
    return False


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def check_rate_limit(user_id: int) -> bool:
    """Check if user is within rate limit. Returns True if allowed."""
    now = time.time()
    if user_id not in _command_timestamps:
        _command_timestamps[user_id] = []
    _command_timestamps[user_id] = [
        t for t in _command_timestamps[user_id] if now - t < 60
    ]
    if len(_command_timestamps[user_id]) >= RATE_LIMIT_PER_MIN:
        return False
    _command_timestamps[user_id].append(now)
    return True# ---------------------------------------------------------------------------
# System prompt and tool definitions
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Tango Agent, an autonomous AI assistant operating on the Schubert server for Project Tango. You have full autonomy to investigate issues, fix code, restart services, and commit changes. You must ask for confirmation only before git push operations.

## Environment
- Server: Schubert (Ubuntu Linux)
- Project path: /opt/Project-Tango/
- Python venv: /opt/Project-Tango/backend/venv/bin/python
- LiteLLM endpoint: http://127.0.0.1:4000 (for LLM queries)
- Git branch: fix/route-all-personas-to-elevenlabs (feature branch)

## Services
Safe to restart: tango-backend.service, tango-web.service, polyglot-litellm.service, tango-tts.service
NEVER touch: caddy.service, cloudflared.service, postgresql@18-main.service, tailscaled.service, meetscribe-*, foxtrot-*, ollama.service

## Git Operations
- All git operations MUST run as user z121532: `sudo -u z121532 git ...`
- Conventional Commits format required (feat:, fix:, perf:, refactor:, docs:, etc.)
- CHANGELOG.md must be updated on every commit
- NEVER commit .env (it's gitignored)
- NEVER modify AGENTS.md (human owner only)
- NEVER push to main branch (push to feature branches only)
- Git push ALWAYS requires user confirmation — the system will intercept and ask

## Tools Available
1. run_shell: Execute any shell command on Schubert. Use for diagnostics, file operations, git, systemctl, etc. Dangerous commands are blocked. Git push requires confirmation.
2. write_file: Write content to a file. Useful for code patches. AGENTS.md and .env are blocked.
3. health_check: Run the 6-layer Tango health check script for a full system diagnosis.

## Operating Guidelines
1. Investigate before acting — read logs, check service status, examine code
2. When fixing code, explain what you're changing and why
3. After making changes, verify they work (restart service, check logs, test)
4. Use Conventional Commits format for git commits
5. Update CHANGELOG.md with every commit
6. Run git operations as z121532: `sudo -u z121532 git ...`
7. Keep responses concise — focus on actions and results
8. If you encounter errors, diagnose and fix them autonomously
9. Only ask for confirmation before git push (the system handles this automatically)
10. Do NOT attempt to push to main — push to feature branches only

## What NOT to do
- Do not run rm -rf, mkfs, dd, or other destructive commands
- Do not install packages (apt, pip, npm)
- Do not modify AGENTS.md
- Do not commit .env
- Do not push to main branch
- Do not touch forbidden services
- Do not run shutdown, reboot, or halt
- Do not run chmod 777
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Execute a shell command on Schubert. Use for diagnostics, file "
                "operations, git commands, service management, etc. Dangerous "
                "commands (rm -rf, mkfs, dd, package installs) are blocked. "
                "Git push requires user confirmation."
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
                "Write content to a file on Schubert. AGENTS.md and .env are "
                "blocked. Use for code patches and configuration changes."
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
            "name": "health_check",
            "description": (
                "Run the 6-layer Tango health check script for a full system "
                "diagnosis. Returns the health check output."
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
    """Call the LiteLLM API for chat completion with tool support."""
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
                    log(
                        f"LLM API error {resp.status}: {error_text[:500]}",
                        "ERROR",
                    )
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
    """Execute a tool call with guardrails. Returns the result string."""

    if tool_name == "run_shell":
        command = tool_args.get("command", "")
        if not command:
            return "Error: no command provided"

        log(f"Tool run_shell: {command[:200]}", "INFO")

        # Check hard blocks
        block_reason = check_hard_blocks(command)
        if block_reason:
            log(f"BLOCKED: {block_reason} — command: {command[:100]}", "WARN")
            return f"BLOCKED: {block_reason}. This command is not allowed."

        # Check forbidden services
        forbidden = check_forbidden_service(command)
        if forbidden:
            log(
                f"BLOCKED: forbidden service {forbidden} — command: {command[:100]}",
                "WARN",
            )
            return (
                f"BLOCKED: {forbidden} is a forbidden service. "
                "Do not modify it."
            )

        # Check if confirmation needed
        confirm_reason = needs_confirmation(command)
        if confirm_reason:
            log(
                f"Confirmation needed: {confirm_reason} — command: {command[:100]}",
                "INFO",
            )
            confirmed = await ask_confirmation(message, command)
            if not confirmed:
                return "User denied this command."

        # Execute
        code, output = run_command(command, timeout=SHELL_TIMEOUT)
        result = f"Exit code: {code}\n{output}"

        # Truncate for LLM context
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

        # Check blocked paths
        if is_blocked_write_path(path):
            log(f"BLOCKED: write to {path}", "WARN")
            return f"BLOCKED: Cannot write to {path}. This file is protected."

        try:
            # Create parent directories if needed
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

    elif tool_name == "health_check":
        log("Tool health_check", "INFO")
        code, output = run_command(
            "sudo python3 /opt/Project-Tango/scripts/tango-healthcheck.py 2>&1",
            timeout=120,
        )
        result = f"Exit code: {code}\n{output}"
        if len(result) > TOOL_OUTPUT_LIMIT:
            result = result[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"
        return result

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


async def ask_confirmation(message: discord.Message, command: str) -> bool:
    """Ask user for confirmation via Discord. Returns True if confirmed."""
    # Truncate command for display
    display_cmd = command[:500]
    if len(command) > 500:
        display_cmd += "..."

    await message.reply(
        f"⚠️ **Confirmation required**\n"
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


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


async def run_agent_loop(message: discord.Message, user_input: str) -> str:
    """Run the LLM agent loop. Returns the final response text."""
    start_time = time.time()

    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    log(f"Agent loop started for: {user_input[:200]}", "INFO")

    for iteration in range(MAX_ITERATIONS):
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > AGENT_TIMEOUT:
            log(f"Agent loop timed out after {elapsed:.0f}s", "WARN")
            return (
                f"⏱️ Agent timed out after {AGENT_TIMEOUT}s. "
                "I was working on your request but ran out of time."
            )

        # Call LLM
        log(f"LLM call iteration {iteration + 1}/{MAX_ITERATIONS}", "INFO")
        response = await llm_chat(messages, TOOLS)

        if "error" in response and not response.get("choices"):
            return f"❌ LLM error: {response['error']}"

        choices = response.get("choices", [])
        if not choices:
            return "❌ No response from LLM."

        choice = choices[0]
        assistant_message = choice.get("message", {})

        # Add assistant message to conversation history
        messages.append(assistant_message)

        # Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])

        # If there's content without tool calls, this is the final response
        content = assistant_message.get("content")
        if content and not tool_calls:
            log(f"Agent final response: {content[:200]}", "INFO")
            return content

        # If there's content WITH tool calls, send it as a status update
        if content and tool_calls and len(content) > 10:
            await message.reply(f"💭 {content[:1500]}")

        if not tool_calls:
            return "I've completed my analysis but have no specific response."

        # Execute each tool call
        for tool_call in tool_calls:
            tool_id = tool_call.get("id", "")
            tool_function = tool_call.get("function", {})
            tool_name = tool_function.get("name", "")

            try:
                tool_args = json.loads(tool_function.get("arguments", "{}"))
            except json.JSONDecodeError as e:
                tool_args = {}
                log(f"Invalid tool arguments: {e}", "WARN")

            # Send tool execution update to Discord
            if tool_name == "run_shell":
                cmd_preview = tool_args.get("command", "")[:100]
                await message.reply(f"🔧 `{cmd_preview}`")
            elif tool_name == "write_file":
                path = tool_args.get("path", "")
                await message.reply(f"📝 Writing to `{path}`")
            elif tool_name == "health_check":
                await message.reply("🏥 Running health check...")

            # Execute tool
            result = await execute_tool(message, tool_name, tool_args)

            # Add tool result to conversation
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result,
                }
            )

            log(f"Tool {tool_name} result: {result[:200]}", "INFO")

    log("Agent loop reached max iterations", "WARN")
    return (
        f"⏱️ I reached the maximum number of steps ({MAX_ITERATIONS}) "
        "without completing. Here's what I've done so far — "
        "you may need to follow up."
    )# ---------------------------------------------------------------------------
# Level 1 quick commands (no LLM cost)
# ---------------------------------------------------------------------------


def cmd_status() -> discord.Embed:
    """Quick service health snapshot."""
    services = sorted(SAFE_SERVICES | FORBIDDEN_SERVICES)
    active_count = 0
    inactive = []

    for svc in services:
        if systemctl_is_active(svc):
            active_count += 1
        else:
            inactive.append(svc)

    embed = discord.Embed(
        title="📊 Tango Service Status",
        color=COLOR_SUCCESS if not inactive else COLOR_ERROR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Services", value=f"{active_count}/{len(services)} active", inline=True
    )

    if inactive:
        embed.add_field(name="Inactive", value="\n".join(inactive), inline=False)
        embed.description = f"⚠️ {len(inactive)} service(s) inactive"
    else:
        embed.description = "✅ All services running"

    return embed


def cmd_health() -> discord.Embed:
    """Run the full 6-layer health check."""
    log("Running full health check via bot command", "INFO")
    code, output = run_command(
        "sudo python3 /opt/Project-Tango/scripts/tango-healthcheck.py 2>&1",
        timeout=120,
    )

    lines = output.strip().split("\n")
    issues_found = False
    key_lines = []

    for line in lines:
        if "issue(s) found" in line:
            issues_found = True
            key_lines.append(line.split("] ", 1)[-1] if "] " in line else line)
        elif any(
            layer in line
            for layer in [
                "Layer 1:", "Layer 2:", "Layer 3:",
                "Layer 4:", "Layer 5:", "Layer 6:",
            ]
        ):
            key_lines.append(line.split("] ", 1)[-1] if "] " in line else line)
        elif "all systems nominal" in line:
            key_lines.append("✅ All systems nominal")

    embed = discord.Embed(
        title="🏥 Health Check Results",
        color=COLOR_WARN if issues_found else COLOR_SUCCESS,
        timestamp=datetime.now(timezone.utc),
    )

    if key_lines:
        embed.description = "\n".join(key_lines[:20])
    else:
        embed.description = "Health check completed (see log for details)"

    if len(embed.description) > 4000:
        embed.description = embed.description[:3990] + "\n... (truncated)"

    return embed


def cmd_logs() -> discord.Embed:
    """Show recent tango-backend logs."""
    code, output = run_command(
        f"sudo journalctl -u {BACKEND_SERVICE} --no-pager -n {LOG_LINES} -o cat 2>&1",
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
        title=f"📋 Recent {BACKEND_SERVICE} logs (last {LOG_LINES} lines)",
        description=f"```\n{output}\n```",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def cmd_billing() -> discord.Embed:
    """Check ElevenLabs subscription status."""
    env = load_env()
    api_key = env.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        return discord.Embed(
            title="❌ ElevenLabs API key not configured",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    code, output = run_command(
        f'curl -s -w "\\n%{{http_code}}" --max-time 10 '
        f"{ELEVENLABS_SUBSCRIPTION_URL} "
        f'-H "xi-api-key: {api_key}"',
        timeout=15,
    )

    if code != 0:
        return discord.Embed(
            title="❌ ElevenLabs API unreachable",
            description=f"Network error: {output[:500]}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    parts = output.strip().rsplit("\n", 1)
    if len(parts) != 2:
        return discord.Embed(
            title="❌ Unexpected response from ElevenLabs",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    body, http_code = parts[0], parts[1].strip()

    if http_code != "200":
        return discord.Embed(
            title="❌ ElevenLabs API error",
            description=f"HTTP {http_code}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    try:
        data = json.loads(body)
        status = data.get("status", "unknown")
        char_count = data.get("character_count", 0)
        char_limit = data.get("character_limit", 0)
        tier = data.get("tier", "unknown")

        is_active = status == "active"
        pct = (char_count / char_limit * 100) if char_limit > 0 else 0

        embed = discord.Embed(
            title="💳 ElevenLabs Subscription",
            color=COLOR_SUCCESS if is_active else COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Status",
            value=f"{'✅' if is_active else '❌'} {status}",
            inline=True,
        )
        embed.add_field(name="Tier", value=tier, inline=True)
        embed.add_field(
            name="Characters",
            value=f"{char_count:,} / {char_limit:,} ({pct:.1f}%)",
            inline=False,
        )
        return embed
    except json.JSONDecodeError:
        return discord.Embed(
            title="❌ Invalid response from ElevenLabs",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )


def cmd_tts() -> discord.Embed:
    """Test TTS synthesis with a small request."""
    env = load_env()
    api_key = env.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        return discord.Embed(
            title="❌ ElevenLabs API key not configured",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    base_url = env.get("ELEVENLABS_BASE_URL", "https://api.us.elevenlabs.io/v1")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    tts_url = f"{base_url}/text-to-speech/{TTS_TEST_VOICE_ID}"
    payload = json.dumps(
        {
            "text": TTS_TEST_TEXT,
            "model_id": TTS_TEST_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
        }
    )

    code, output = run_command(
        f'curl -s -o /dev/null -w "%{{http_code}}|%{{size_download}}" '
        f'--max-time 15 -X POST "{tts_url}" '
        f'-H "xi-api-key: {api_key}" '
        f'-H "Content-Type: application/json" '
        f"-d '{payload}'",
        timeout=20,
    )

    if code != 0:
        return discord.Embed(
            title="❌ TTS test failed (network error)",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    parts = output.strip().split("|")
    if len(parts) != 2:
        return discord.Embed(
            title="❌ TTS test failed (bad response)",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    http_code = parts[0]
    size = int(parts[1]) if parts[1].isdigit() else 0

    if http_code == "200" and size > 100:
        return discord.Embed(
            title="✅ TTS Synthesis Test",
            description=(
                f"HTTP 200, {size:,} bytes returned\n"
                f"Voice: {TTS_TEST_VOICE_ID}\n"
                f"Model: {TTS_TEST_MODEL}\n"
                f'Text: "{TTS_TEST_TEXT}"'
            ),
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
    else:
        return discord.Embed(
            title="❌ TTS Synthesis Failed",
            description=(
                f"HTTP {http_code}, {size:,} bytes\n"
                f"Voice: {TTS_TEST_VOICE_ID}\n"
                f"Model: {TTS_TEST_MODEL}"
            ),
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )


def cmd_restart(service: str) -> discord.Embed:
    """Restart a service. Returns an embed."""
    if service not in SAFE_SERVICES:
        return discord.Embed(
            title="❌ Service not restartable",
            description=(
                f"`{service}` is not in the allowlist of safe services.\n"
                f"Safe services: {', '.join(sorted(SAFE_SERVICES))}"
            ),
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
        title="🤖 Tango Agent — Level 3 Autonomous",
        description=(
            "I'm an autonomous agent powered by Claude Sonnet 4.5. "
            "Send me a natural language message and I'll investigate, fix, "
            "restart, and commit — asking only before git push."
        ),
        color=COLOR_AGENT,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Quick Commands", value="━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!status", value="Quick service health snapshot", inline=False)
    embed.add_field(name="!health", value="Full 6-layer health check", inline=False)
    embed.add_field(name="!logs", value="Recent tango-backend logs", inline=False)
    embed.add_field(
        name="!restart [service]", value="Restart a service (requires confirmation)", inline=False
    )
    embed.add_field(name="!billing", value="Check ElevenLabs subscription", inline=False)
    embed.add_field(name="!tts", value="Test TTS synthesis", inline=False)
    embed.add_field(name="Agent Mode", value="━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(
        name="Any message",
        value=(
            "Send a natural language request and I'll investigate, fix, "
            "restart, and commit autonomously. I only ask before git push."
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
    log(
        f"Tango Discord Agent connected as {bot.user} (ID: {bot.user.id})",
        "INFO",
    )
    log(
        f"Listening in channel {BOT_CHANNEL_ID}, admin: {ADMIN_USER_ID}",
        "INFO",
    )
    log(f"LLM model: {LLM_MODEL} via {LITELLM_URL}", "INFO")


@bot.event
async def on_message(message: discord.Message):
    # Ignore our own messages
    if message.author == bot.user:
        return

    # Only respond in the configured channel
    if message.channel.id != BOT_CHANNEL_ID:
        return

    # Only respond to the admin user
    if message.author.id != ADMIN_USER_ID:
        log(
            f"Unauthorized message from user {message.author.id} "
            f"({message.author}): {message.content[:100]}",
            "WARN",
        )
        return

    # Rate limiting
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

            elif command == "health":
                await message.reply("⏳ Running full health check (may take up to 30 seconds)...")
                await message.reply(embed=cmd_health())

            elif command == "logs":
                await message.reply(embed=cmd_logs())

            elif command == "billing":
                await message.reply(embed=cmd_billing())

            elif command == "tts":
                await message.reply("⏳ Testing TTS synthesis...")
                await message.reply(embed=cmd_tts())

            elif command == "restart":
                service = args[0] if args else BACKEND_SERVICE

                # Check for pending confirmation
                if message.author.id in _pending_restarts:
                    pending_svc, pending_time = _pending_restarts.pop(
                        message.author.id
                    )
                    if time.time() - pending_time > RESTART_CONFIRM_TIMEOUT:
                        await message.reply(
                            "⏱️ Confirmation timed out. Please run !restart again."
                        )
                        return
                    if service == pending_svc or (
                        not args and pending_svc == BACKEND_SERVICE
                    ):
                        await message.reply(f"⏳ Restarting {pending_svc}...")
                        await message.reply(embed=cmd_restart(pending_svc))
                        return
                    else:
                        await message.reply(
                            "❌ Service mismatch. Please run !restart again."
                        )
                        return

                # New restart request — ask for confirmation
                if service not in SAFE_SERVICES:
                    await message.reply(embed=cmd_restart(service))
                    return

                _pending_restarts[message.author.id] = (service, time.time())
                await message.reply(
                    f"⚠️ Are you sure you want to restart `{service}`?\n"
                    f"Type `!restart` again within {RESTART_CONFIRM_TIMEOUT}s to confirm."
                )

            elif command == "agent":
                # Explicit agent invocation
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


async def run_agent_with_update(message: discord.Message, user_input: str):
    """Run the agent loop and send the response to Discord."""
    try:
        await message.reply(f"🤖 Working on: {user_input[:200]}")
        response = await run_agent_loop(message, user_input)

        # Send the final response (split if too long for Discord)
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
    log("Tango Discord Agent (Level 3) starting", "INFO")
    log(f"Model: {LLM_MODEL} via {LITELLM_URL}", "INFO")

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