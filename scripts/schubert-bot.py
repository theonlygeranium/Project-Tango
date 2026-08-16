#!/usr/bin/env python3
"""
Schubert Bot — Level 3 autonomous agent for server-wide Schubert operations.

An LLM-powered Discord bot that supervises the entire Schubert server. It can
investigate issues, manage services, read logs, monitor system health, and
work with any project on the server. Uses writer/claude-sonnet-4-5 via
LiteLLM for reasoning. Asks for confirmation before git push and before
restarting critical services (caddy, cloudflared, postgresql, tailscaled).

Security:
- Admin allowlist: only SCHUBERT_BOT_ADMIN_USER_ID can issue commands
- Channel lock: bot only responds in SCHUBERT_BOT_CHANNEL_ID
- Hard blocks: rm -rf, mkfs, dd, shutdown/reboot, chmod 777, package installs
- Confirmation required: git push, restarting critical services
- Loop safety: max 20 iterations, 5-minute timeout
- Full audit logging to /var/log/schubert-bot.log

Usage:
    python3 schubert-bot.py

Interaction:
    Natural language messages trigger the autonomous agent loop.
    Quick commands (prefixed with !) run without LLM cost:
        !status    — full server health (services, disk, RAM, CPU, uptime)
        !services  — list all systemd services and their status
        !logs <s>  — recent logs for a service (default: tango-backend)
        !restart <s> — restart a service (critical services need confirmation)
        !disk      — disk usage overview
        !mem       — memory and swap usage
        !procs     — top processes by CPU and memory
        !net       — network connections and listening ports
        !help      — show available commands
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
LOG_FILE = "/var/log/schubert-bot.log"

# LLM
LITELLM_URL = "http://127.0.0.1:4000/v1"
LLM_MODEL = "writer/claude-sonnet-4-5"
LLM_TIMEOUT = 90
LLM_MAX_TOKENS = 4096
LLM_TEMPERATURE = 0.3

# Agent loop safety
MAX_ITERATIONS = 20
AGENT_TIMEOUT = 300
TOOL_OUTPUT_LIMIT = 4000
SHELL_TIMEOUT = 120

# Discord
RATE_LIMIT_PER_MIN = 10
RESTART_CONFIRM_TIMEOUT = 30

# Critical services — restart requires confirmation
CRITICAL_SERVICES = {
    "caddy.service",
    "cloudflared.service",
    "postgresql@18-main.service",
    "tailscaled.service",
}

# Services that should never be touched even by Schubert Bot
NEVER_TOUCH_SERVICES = {
    "schubert-bot.service",  # Don't restart yourself
}

# Log viewing
LOG_LINES = 50

# Discord embed colors
COLOR_INFO = 0x5865F2
COLOR_SUCCESS = 0x57F287
COLOR_WARN = 0xFEE75C
COLOR_ERROR = 0xED4245
COLOR_AGENT = 0xE67E22  # orange

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
    (r">\s*/etc/(passwd|shadow|fstab|sudoers)", "critical system file overwrite"),
]

# Patterns that require user confirmation before execution
CONFIRM_PATTERNS = [
    (r"\bgit\s+push\b", "git push"),
    (r"\bsystemctl\s+(restart|stop)\s+", "service restart/stop"),
]

# File paths that cannot be overwritten via write_file tool
BLOCKED_WRITE_PATHS = [
    "AGENTS.md",
    "/opt/Project-Tango/AGENTS.md",
    ".env",
    "/opt/Project-Tango/.env",
    "/opt/polyglot/.env.runtime",
]

# ---------------------------------------------------------------------------
# Globals
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

    env = load_env()
    BOT_TOKEN = env.get("SCHUBERT_BOT_TOKEN", "")
    LITELLM_MASTER_KEY = env.get(
        "LITELLM_MASTER_KEY", os.environ.get("LITELLM_MASTER_KEY", "")
    )
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
        f"model={LLM_MODEL}",
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
    return True# ---------------------------------------------------------------------------
# System prompt and tool definitions
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Schubert Bot, an autonomous AI assistant with full access to the Schubert server. You supervise all projects and services on the server, not just Project Tango. You have full autonomy to investigate issues, manage services, read logs, monitor system health, fix code, and commit changes. You must ask for confirmation before git push and before restarting critical services.

## Environment
- Server: Schubert (Ubuntu Linux)
- Full server access — all projects, all services, all files
- Python venv: /opt/Project-Tango/backend/venv/bin/python
- LiteLLM endpoint: http://127.0.0.1:4000 (for LLM queries)

## Projects on Schubert
- Project Tango: /opt/Project-Tango/ (voice agents, LiveKit, Discord bots)
- Polyglot: /opt/polyglot/ (LiteLLM proxy, multi-LLM routing)
- Watson AI: /opt/watson-ai/ (AI assistant platform)
- Other services: meetscribe-*, foxtrot-* (separate projects)

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
5. Keep responses concise — focus on actions and results
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
"""

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
]


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
                message, command,
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
        return False# ---------------------------------------------------------------------------
# Server status helpers
# ---------------------------------------------------------------------------


def get_server_status_text() -> str:
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
# Agent loop
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
            messages.append({"role": "tool", "tool_call_id": tool_id, "content": result})
            log(f"Tool {tool_name} result: {result[:200]}", "INFO")
    log("Agent loop reached max iterations", "WARN")
    return f"⏱️ I reached the maximum number of steps ({MAX_ITERATIONS}) without completing."


# ---------------------------------------------------------------------------
# Level 1 quick commands (no LLM cost)
# ---------------------------------------------------------------------------


def cmd_status() -> discord.Embed:
    code, uptime_out = run_command("uptime -p 2>/dev/null || uptime", timeout=10)
    code, disk_out = run_command("df -h / /home /opt /tmp 2>/dev/null | grep -E '^/dev|^Filesystem'", timeout=10)
    code, mem_out = run_command("free -h | grep -E 'Mem|Swap'", timeout=10)
    code, failed_out = run_command("systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $1}'", timeout=10)
    code, svc_count = run_command("systemctl list-units --type=service --state=active --no-pager --no-legend | wc -l", timeout=10)
    has_failures = bool(failed_out.strip())
    embed = discord.Embed(title="📊 Schubert Server Status", color=COLOR_ERROR if has_failures else COLOR_SUCCESS, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Uptime", value=uptime_out.strip()[:200], inline=False)
    embed.add_field(name="Active Services", value=svc_count.strip(), inline=True)
    if has_failures:
        embed.add_field(name="⚠️ Failed Services", value=failed_out.strip()[:500], inline=False)
        embed.description = f"⚠️ {len(failed_out.strip().split())} failed service(s)"
    else:
        embed.description = "✅ All services running"
    embed.add_field(name="Disk", value=f"```\n{disk_out}\n```", inline=False)
    embed.add_field(name="Memory", value=f"```\n{mem_out}\n```", inline=False)
    return embed


def cmd_services() -> discord.Embed:
    code, output = run_command("systemctl list-units --type=service --state=active --no-pager --no-legend | awk '{print $1, $4}' | sort", timeout=15)
    if code != 0:
        return discord.Embed(title="❌ Failed to list services", description=f"Error: {output[:500]}", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    code, failed = run_command("systemctl list-units --type=service --state=failed --no-pager --no-legend 2>/dev/null | awk '{print $1}'", timeout=10)
    lines = output.strip().split("\n")
    if len(lines) > 30:
        display = "\n".join(lines[:30]) + f"\n... and {len(lines) - 30} more"
    else:
        display = "\n".join(lines)
    if failed.strip():
        display += f"\n\n⚠️ FAILED: {failed.strip()}"
    embed = discord.Embed(title=f"📋 Active Services ({len(lines)})", description=f"```\n{display}\n```", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    return embed


def cmd_logs(service: str) -> discord.Embed:
    if not service:
        service = "tango-backend.service"
    if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
        return discord.Embed(title="❌ Invalid service name", description=f"`{service}` is not a valid service name.", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    code, output = run_command(f"sudo journalctl -u {service} --no-pager -n {LOG_LINES} -o cat 2>&1", timeout=15)
    if code != 0:
        return discord.Embed(title="❌ Failed to retrieve logs", description=f"Error: {output[:500]}", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    if len(output) > 1900:
        output = "...\n" + output[-1900:]
    embed = discord.Embed(title=f"📋 Recent {service} logs (last {LOG_LINES} lines)", description=f"```\n{output}\n```", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    return embed


def cmd_disk() -> discord.Embed:
    code, output = run_command("df -h --total 2>/dev/null", timeout=10)
    if code != 0:
        return discord.Embed(title="❌ Failed to get disk usage", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    if len(output) > 1900:
        output = output[-1900:]
    embed = discord.Embed(title="💾 Disk Usage", description=f"```\n{output}\n```", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    return embed


def cmd_mem() -> discord.Embed:
    code, output = run_command("free -h", timeout=10)
    embed = discord.Embed(title="🧠 Memory & Swap", description=f"```\n{output}\n```", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    return embed


def cmd_procs() -> discord.Embed:
    code, cpu_out = run_command("ps aux --sort=-%cpu | head -11", timeout=10)
    code, mem_out = run_command("ps aux --sort=-%mem | head -11", timeout=10)
    embed = discord.Embed(title="⚡ Top Processes", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="By CPU", value=f"```\n{cpu_out[:1000]}\n```", inline=False)
    embed.add_field(name="By Memory", value=f"```\n{mem_out[:1000]}\n```", inline=False)
    return embed


def cmd_net() -> discord.Embed:
    code, output = run_command("ss -tlnp | head -40", timeout=10)
    if len(output) > 1900:
        output = output[:1900] + "\n... (truncated)"
    embed = discord.Embed(title="🌐 Listening Ports & Connections", description=f"```\n{output}\n```", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    return embed


def cmd_restart(service: str) -> discord.Embed:
    if not service:
        return discord.Embed(title="❌ No service specified", description="Usage: `!restart <service-name>`", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    if not re.match(r'^[a-zA-Z0-9@._-]+\.service$', service):
        return discord.Embed(title="❌ Invalid service name", description=f"`{service}` is not a valid service name.", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    if service in NEVER_TOUCH_SERVICES:
        return discord.Embed(title="❌ Cannot restart self", description=f"Cannot restart {service} — self-protection.", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))
    log(f"Restarting {service} via bot command", "WARN")
    code, output = run_command(f"sudo systemctl restart {service}", timeout=30)
    if code == 0:
        time.sleep(3)
        active = systemctl_is_active(service)
        return discord.Embed(title=f"{'✅' if active else '⚠️'} {service} restarted", description=f"Service is {'active' if active else 'not active after restart'}", color=COLOR_SUCCESS if active else COLOR_WARN, timestamp=datetime.now(timezone.utc))
    else:
        return discord.Embed(title=f"❌ Failed to restart {service}", description=f"Error: {output[:500]}", color=COLOR_ERROR, timestamp=datetime.now(timezone.utc))


def cmd_help() -> discord.Embed:
    embed = discord.Embed(title="🤖 Schubert Bot — Server-Wide Autonomous Agent", description=("I'm an autonomous agent with full access to the Schubert server. I can manage all services, monitor system health, investigate issues, fix code, and commit changes across all projects. I ask for confirmation before git push and before restarting critical services."), color=COLOR_AGENT, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Quick Commands", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="!status", value="Full server health (services, disk, RAM, uptime)", inline=False)
    embed.add_field(name="!services", value="List all active systemd services", inline=False)
    embed.add_field(name="!logs [service]", value="Recent logs for a service (default: tango-backend)", inline=False)
    embed.add_field(name="!restart <service>", value="Restart any service (critical services need confirmation)", inline=False)
    embed.add_field(name="!disk", value="Disk usage overview", inline=False)
    embed.add_field(name="!mem", value="Memory and swap usage", inline=False)
    embed.add_field(name="!procs", value="Top processes by CPU and memory", inline=False)
    embed.add_field(name="!net", value="Listening ports and network connections", inline=False)
    embed.add_field(name="Agent Mode", value="━━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="Any message", value=("Send a natural language request and I'll investigate, fix, restart, and commit autonomously across the entire server."), inline=False)
    embed.add_field(name="!agent <request>", value="Explicit agent invocation", inline=False)
    embed.set_footer(text=(f"Model: {LLM_MODEL} | Rate limit: {RATE_LIMIT_PER_MIN}/min | Max iterations: {MAX_ITERATIONS} | Timeout: {AGENT_TIMEOUT}s"))
    return embed


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    log(f"Schubert Bot connected as {bot.user} (ID: {bot.user.id})", "INFO")
    log(f"Listening in channel {BOT_CHANNEL_ID}, admin: {ADMIN_USER_ID}", "INFO")
    log(f"LLM model: {LLM_MODEL} via {LITELLM_URL}", "INFO")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    if message.channel.id != BOT_CHANNEL_ID:
        return
    if message.author.id != ADMIN_USER_ID:
        log(f"Unauthorized message from user {message.author.id} ({message.author}): {message.content[:100]}", "WARN")
        return
    if not check_rate_limit(message.author.id):
        await message.reply(f"⏱️ Rate limit exceeded. Max {RATE_LIMIT_PER_MIN} messages per minute.")
        return
    content = message.content.strip()
    if content.startswith("!"):
        parts = content[1:].strip().split()
        if not parts:
            return
        command = parts[0].lower()
        args = parts[1:]
        log(f"Command from {message.author}: !{command} {' '.join(args)}".strip(), "INFO")
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
                    pending_svc, pending_time = _pending_restarts.pop(message.author.id)
                    if time.time() - pending_time > RESTART_CONFIRM_TIMEOUT:
                        await message.reply("⏱️ Confirmation timed out. Please run !restart again.")
                        return
                    if service == pending_svc or (not args and pending_svc):
                        await message.reply(f"⏳ Restarting {pending_svc}...")
                        await message.reply(embed=cmd_restart(pending_svc))
                        return
                    else:
                        await message.reply("❌ Service mismatch. Please run !restart again.")
                        return
                if not service:
                    await message.reply("Usage: `!restart <service-name>`")
                    return
                if service in NEVER_TOUCH_SERVICES:
                    await message.reply(f"❌ Cannot restart {service} — self-protection.")
                    return
                if service in CRITICAL_SERVICES:
                    _pending_restarts[message.author.id] = (service, time.time())
                    await message.reply(f"⚠️ **{service}** is a critical service.\nRestarting it may briefly interrupt server access.\nType `!restart {service}` again within {RESTART_CONFIRM_TIMEOUT}s to confirm.")
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
            elif command == "agent":
                agent_input = " ".join(args)
                if not agent_input:
                    await message.reply("Usage: `!agent <your request>`")
                    return
                await run_agent_with_update(message, agent_input)
            else:
                await message.reply(f"❓ Unknown command: `!{command}`. Type `!help` for available commands, or just send a natural language message to use the autonomous agent.")
        except Exception as e:
            log(f"Error handling command !{command}: {e}", "ERROR")
            await message.reply(f"❌ Error: {str(e)[:500]}")
    else:
        log(f"Agent message from {message.author}: {content[:200]}", "INFO")
        await run_agent_with_update(message, content)


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
    log("Schubert Bot (Level 3 server-wide agent) starting", "INFO")
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