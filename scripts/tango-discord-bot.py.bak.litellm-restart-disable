#!/usr/bin/env python3
"""
Tango Discord Bot — Level 1 command bot for Project Tango operations.

A lightweight Discord bot that responds to fixed commands for health checks,
log viewing, service restarts, and billing verification. Only the configured
admin user can issue commands, and only in the configured channel.

Runs as a systemd service (tango-discord-bot.service) on Schubert.

Security:
- Admin allowlist: only DISCORD_ADMIN_USER_ID can issue commands
- Channel lock: bot only responds in DISCORD_BOT_CHANNEL_ID
- Command allowlist: only fixed, predefined commands execute
- Confirmation required for destructive actions (restart)
- All commands and results logged to /var/log/tango-discord-bot.log

Usage:
    python3 tango-discord-bot.py

Commands (all prefixed with !):
    !status   — quick service health snapshot (dry-run health check)
    !health   — full 6-layer health check with auto-remediation
    !logs     — recent tango-backend logs (last 50 lines)
    !restart  — restart tango-backend.service (requires confirmation)
    !billing  — check ElevenLabs subscription status
    !tts      — test TTS synthesis with a 2-char request
    !help     — list available commands
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import discord

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = "/opt/Project-Tango/.env"
LOG_FILE = "/var/log/tango-discord-bot.log"

# Services
BACKEND_SERVICE = "tango-backend.service"
WEB_SERVICE = "tango-web.service"
LITELLM_SERVICE = "polyglot-litellm.service"
TTS_SERVICE = "tango-tts.service"

# Forbidden services (alert-only, never restart via bot)
FORBIDDEN_SERVICES = {
    "caddy.service",
    "cloudflared.service",
    "postgresql@18-main.service",
    "tailscaled.service",
}

SAFE_SERVICES = {BACKEND_SERVICE, WEB_SERVICE, LITELLM_SERVICE, TTS_SERVICE}

# ElevenLabs API
ELEVENLABS_SUBSCRIPTION_URL = "https://api.us.elevenlabs.io/v1/user/subscription"

# TTS test
TTS_TEST_TEXT = "OK"
TTS_TEST_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"
TTS_TEST_MODEL = "eleven_flash_v2_5"

# Log viewing
LOG_LINES = 50

# Restart confirmation timeout (seconds)
RESTART_CONFIRM_TIMEOUT = 30

# Rate limiting: max commands per minute per user
RATE_LIMIT_PER_MIN = 10

# Color for Discord embeds
COLOR_INFO = 0x5865F2     # blurple
COLOR_SUCCESS = 0x57F287  # green
COLOR_WARN = 0xFEE75C     # yellow
COLOR_ERROR = 0xED4245    # red

# ---------------------------------------------------------------------------
# Globals (loaded from .env at startup)
# ---------------------------------------------------------------------------

BOT_TOKEN = ""
ADMIN_USER_ID = 0
BOT_CHANNEL_ID = 0

# Rate limiting state
_command_timestamps: dict[int, list[float]] = {}

# Pending restart confirmations: {user_id: (service, timestamp)}
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
    """Load environment variables from the .env file."""
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


def load_config() -> bool:
    """Load bot configuration from .env. Returns True if all required values found."""
    global BOT_TOKEN, ADMIN_USER_ID, BOT_CHANNEL_ID

    env = load_env()
    BOT_TOKEN = env.get("DISCORD_BOT_TOKEN", "")
    admin_id_str = env.get("DISCORD_ADMIN_USER_ID", "")
    channel_id_str = env.get("DISCORD_BOT_CHANNEL_ID", "")

    if not BOT_TOKEN:
        log("DISCORD_BOT_TOKEN not found in .env", "CRITICAL")
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
        log(f"Invalid admin or channel ID format", "CRITICAL")
        return False

    log(f"Config loaded: admin={ADMIN_USER_ID}, channel={BOT_CHANNEL_ID}", "INFO")
    return True


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


def run_command(cmd: str, timeout: int = 30) -> tuple[int, str]:
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
# Rate limiting
# ---------------------------------------------------------------------------


def check_rate_limit(user_id: int) -> bool:
    """Check if user is within rate limit. Returns True if allowed."""
    now = time.time()
    if user_id not in _command_timestamps:
        _command_timestamps[user_id] = []
    # Remove timestamps older than 60 seconds
    _command_timestamps[user_id] = [t for t in _command_timestamps[user_id] if now - t < 60]
    if len(_command_timestamps[user_id]) >= RATE_LIMIT_PER_MIN:
        return False
    _command_timestamps[user_id].append(now)
    return True


# ---------------------------------------------------------------------------
# Command implementations
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
        name="Services",
        value=f"{active_count}/{len(services)} active",
        inline=True,
    )

    if inactive:
        embed.add_field(
            name="Inactive",
            value="\n".join(inactive),
            inline=False,
        )
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

    # Parse the output for key results
    lines = output.strip().split("\n")
    issues_found = False
    key_lines = []

    for line in lines:
        if "issue(s) found" in line:
            issues_found = True
            key_lines.append(line.split("] ", 1)[-1] if "] " in line else line)
        elif any(layer in line for layer in ["Layer 1:", "Layer 2:", "Layer 3:", "Layer 4:", "Layer 5:", "Layer 6:"]):
            key_lines.append(line.split("] ", 1)[-1] if "] " in line else line)
        elif "all systems nominal" in line:
            key_lines.append("✅ All systems nominal")

    embed = discord.Embed(
        title="🏥 Health Check Results",
        color=COLOR_WARN if issues_found else COLOR_SUCCESS,
        timestamp=datetime.now(timezone.utc),
    )

    if key_lines:
        embed.description = "\n".join(key_lines[:20])  # Discord embed limit
    else:
        embed.description = "Health check completed (see log for details)"

    # Truncate if too long
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

    # Truncate for Discord limits
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
        f'curl -s -w "\\n%{{http_code}}" --max-time 10 {ELEVENLABS_SUBSCRIPTION_URL} '
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

    lines = output.strip().rsplit("\n", 1)
    if len(lines) != 2:
        return discord.Embed(
            title="❌ Unexpected response from ElevenLabs",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    body, http_code = lines[0], lines[1].strip()

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

        embed.add_field(name="Status", value=f"{'✅' if is_active else '❌'} {status}", inline=True)
        embed.add_field(name="Tier", value=tier, inline=True)
        embed.add_field(name="Characters", value=f"{char_count:,} / {char_limit:,} ({pct:.1f}%)", inline=False)

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
    payload = json.dumps({
        "text": TTS_TEST_TEXT,
        "model_id": TTS_TEST_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
    })

    code, output = run_command(
        f'curl -s -o /dev/null -w "%{{http_code}}|%{{size_download}}" --max-time 15 '
        f'-X POST "{tts_url}" '
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

    http_code, size = parts[0], int(parts[1]) if parts[1].isdigit() else 0

    if http_code == "200" and size > 100:
        return discord.Embed(
            title="✅ TTS Synthesis Test",
            description=f"HTTP 200, {size:,} bytes returned\nVoice: {TTS_TEST_VOICE_ID}\nModel: {TTS_TEST_MODEL}\nText: \"{TTS_TEST_TEXT}\"",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
    else:
        return discord.Embed(
            title="❌ TTS Synthesis Failed",
            description=f"HTTP {http_code}, {size:,} bytes\nVoice: {TTS_TEST_VOICE_ID}\nModel: {TTS_TEST_MODEL}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )


def cmd_restart(service: str) -> discord.Embed:
    """Restart a service. Returns an embed."""
    if service not in SAFE_SERVICES:
        return discord.Embed(
            title="❌ Service not restartable",
            description=f"`{service}` is not in the allowlist of safe services.\n"
                        f"Safe services: {', '.join(sorted(SAFE_SERVICES))}",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )

    log(f"Restarting {service} via bot command", "WARN")
    code, output = run_command(f"sudo systemctl restart {service}", timeout=30)

    if code == 0:
        # Wait a moment and check if it's active
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
    """Show available commands."""
    embed = discord.Embed(
        title="🤖 Tango Bot Commands",
        description="All commands are prefixed with `!`",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="!status", value="Quick service health snapshot", inline=False)
    embed.add_field(name="!health", value="Full 6-layer health check with auto-remediation", inline=False)
    embed.add_field(name="!logs", value="Recent tango-backend logs (last 50 lines)", inline=False)
    embed.add_field(name="!restart", value="Restart tango-backend (requires confirmation)", inline=False)
    embed.add_field(name="!restart <service>", value="Restart a specific safe service", inline=False)
    embed.add_field(name="!billing", value="Check ElevenLabs subscription status", inline=False)
    embed.add_field(name="!tts", value="Test TTS synthesis (2-char request)", inline=False)
    embed.add_field(name="!help", value="Show this help message", inline=False)
    embed.set_footer(text=f"Rate limit: {RATE_LIMIT_PER_MIN} commands/min")
    return embed


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    log(f"Tango Discord Bot connected as {bot.user} (ID: {bot.user.id})", "INFO")
    log(f"Listening in channel {BOT_CHANNEL_ID}, admin: {ADMIN_USER_ID}", "INFO")


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
        log(f"Unauthorized command from user {message.author.id} ({message.author}): {message.content[:100]}", "WARN")
        return

    # Only respond to commands (starting with !)
    if not message.content.startswith("!"):
        return

    # Rate limiting
    if not check_rate_limit(message.author.id):
        await message.reply(f"⏱️ Rate limit exceeded. Max {RATE_LIMIT_PER_MIN} commands per minute.")
        return

    # Parse command
    parts = message.content[1:].strip().split()
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

            # Check if there's a pending confirmation
            if message.author.id in _pending_restarts:
                pending_svc, pending_time = _pending_restarts.pop(message.author.id)
                if time.time() - pending_time > RESTART_CONFIRM_TIMEOUT:
                    await message.reply("⏱️ Confirmation timed out. Please run !restart again.")
                    return
                if service == pending_svc or (not args and pending_svc == BACKEND_SERVICE):
                    await message.reply(f"⏳ Restarting {pending_svc}...")
                    await message.reply(embed=cmd_restart(pending_svc))
                    return
                else:
                    await message.reply("❌ Service mismatch. Please run !restart again.")
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

        else:
            await message.reply(
                f"❓ Unknown command: `!{command}`. Type `!help` for available commands."
            )

    except Exception as e:
        log(f"Error handling command !{command}: {e}", "ERROR")
        await message.reply(f"❌ Error processing command: {str(e)[:500]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    log("=" * 60, "INFO")
    log("Tango Discord Bot starting", "INFO")

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