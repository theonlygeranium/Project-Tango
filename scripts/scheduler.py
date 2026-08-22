"""
Scheduler — Proactive Monitoring & Scheduled Sweeps (Phase 5.1)
================================================================
Runs periodic background tasks on the bot:

1. Server health sweep — checks disk, memory, CPU, and service status
2. Service monitoring — detects services that have crashed or restarted
3. Disk space alerts — warns when disk usage exceeds threshold
4. Memory store decay — periodically applies time-weighted relevance decay

All sweeps send alerts to the configured Discord channel when issues are detected.

Usage:
    scheduler = Scheduler(bot, channel_id, memory_store)
    await scheduler.start()  # starts all background tasks
    await scheduler.stop()   # stops all background tasks
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from memory_store import MemoryStore

logger = logging.getLogger("schubert-bot.scheduler")

# ---------------------------------------------------------------------------
# Fleet config (non-breaking: missing/corrupt file → hardcoded defaults)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from fleet_config_loader import get_fleet_config
    _fleet = get_fleet_config()
except Exception:
    _fleet = {}

_scheduler = _fleet.get("scheduler", {}) if isinstance(_fleet.get("scheduler", {}), dict) else {}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HEALTH_CHECK_INTERVAL = _scheduler.get("health_check_interval", 300)
SERVICE_CHECK_INTERVAL = _scheduler.get("service_check_interval", 120)
DISK_ALERT_INTERVAL = _scheduler.get("disk_alert_interval", 600)
MEMORY_DECAY_INTERVAL = _scheduler.get("memory_decay_interval", 3600)
DISK_WARNING_THRESHOLD = _scheduler.get("disk_warning_threshold", 80)
DISK_CRITICAL_THRESHOLD = _scheduler.get("disk_critical_threshold", 90)
MEM_WARNING_THRESHOLD = _scheduler.get("mem_warning_threshold", 85)
CPU_WARNING_THRESHOLD = _scheduler.get("cpu_warning_threshold", 90)

# Services to monitor (critical services that should always be running)
MONITORED_SERVICES = [
    "caddy.service",
    "cloudflared.service",
    "postgresql@18-main.service",
    "tailscaled.service",
    "schubert-bot.service",
    "polyglot-litellm.service",
    "github-mcp-server.service",
    "gmail-mcp-freelance.service",
]


class Scheduler:
    """
    Background task scheduler for proactive monitoring.

    Runs periodic sweeps and sends Discord alerts when issues are detected.
    """

    def __init__(
        self,
        bot: discord.Client,
        channel_id: int,
        memory_store: Optional["MemoryStore"] = None,
    ):
        self.bot = bot
        self.channel_id = channel_id
        self.memory_store = memory_store
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._last_service_states: dict[str, str] = {}  # service -> "active"|"inactive"|"failed"
        self._alerted: dict[str, float] = {}  # alert_key -> last_alert_time (for dedup)

    async def start(self):
        """Start all background sweep tasks."""
        if self._running:
            return

        self._running = True
        logger.info("Scheduler starting — background sweeps active")

        self._tasks = [
            asyncio.create_task(self._health_sweep_loop()),
            asyncio.create_task(self._service_monitor_loop()),
            asyncio.create_task(self._disk_alert_loop()),
        ]

        if self.memory_store:
            self._tasks.append(asyncio.create_task(self._memory_decay_loop()))

    async def stop(self):
        """Stop all background tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("Scheduler stopped")

    # -----------------------------------------------------------------------
    # Alert deduplication — don't spam the same alert repeatedly
    # -----------------------------------------------------------------------

    def _should_alert(self, alert_key: str, cooldown: int = 1800) -> bool:
        """Check if enough time has passed since the last alert of this type."""
        now = time.time()
        last = self._alerted.get(alert_key, 0)
        if now - last > cooldown:
            self._alerted[alert_key] = now
            return True
        return False

    def _dispatch_n8n_alert(self, embed: discord.Embed) -> None:
        """Mirror scheduler alerts to the n8n hub without replacing Discord."""
        try:
            from alert_dispatcher import get_dispatcher

            color = getattr(embed, "color", None)
            color_value = getattr(color, "value", None)
            if color_value in {0xE74C3C, 0xED4245}:
                severity = "CRITICAL"
            elif color_value in {0x2ECC71, 0x57F287}:
                severity = "INFO"
            else:
                severity = "WARN"
            title = embed.title or "Scheduler alert"
            message = embed.description or title
            alert_type = "service_failed" if "Service" in title else "scheduler_alert"
            get_dispatcher().send_generic(
                source="scheduler",
                severity=severity,
                alert_type=alert_type,
                title=title,
                message=message,
                bot_name="Scheduler",
            )
        except Exception as e:
            logger.debug("n8n alert dispatch skipped: %s", e)

    async def _send_alert(self, embed: discord.Embed):
        """Send an alert embed to the configured channel and the n8n hub."""
        self._dispatch_n8n_alert(embed)
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                await channel.send(embed=embed, silent=True)
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")

    # -----------------------------------------------------------------------
    # Health sweep — comprehensive server health check
    # -----------------------------------------------------------------------

    async def _health_sweep_loop(self):
        """Periodic server health sweep."""
        while self._running:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                await self._do_health_sweep()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health sweep error: {e}")
                await asyncio.sleep(60)

    async def _do_health_sweep(self):
        """Run a health check and alert on issues."""
        # Check CPU load (1-minute average)
        load_avg = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        cpu_pct = (load_avg / cpu_count) * 100

        # Check memory
        mem_info = self._get_memory_info()

        # Check disk
        disk_info = self._get_disk_info()

        alerts = []

        if cpu_pct > CPU_WARNING_THRESHOLD:
            if self._should_alert("cpu_high"):
                alerts.append(discord.Embed(
                    title="⚠️ High CPU Load",
                    description=f"CPU load is at {cpu_pct:.0f}% (load avg: {load_avg:.2f}, {cpu_count} cores)",
                    color=0xF39C12,
                    timestamp=datetime.now(timezone.utc),
                ))

        if mem_info and mem_info["used_pct"] > MEM_WARNING_THRESHOLD:
            if self._should_alert("mem_high"):
                alerts.append(discord.Embed(
                    title="⚠️ High Memory Usage",
                    description=f"Memory at {mem_info['used_pct']:.0f}% ({mem_info['used']} / {mem_info['total']})",
                    color=0xF39C12,
                    timestamp=datetime.now(timezone.utc),
                ))

        for mount, usage in disk_info.items():
            if usage >= DISK_CRITICAL_THRESHOLD:
                if self._should_alert(f"disk_critical_{mount}"):
                    alerts.append(discord.Embed(
                        title="🚨 Critical Disk Usage",
                        description=f"`{mount}` is at {usage:.0f}% — immediate action needed!",
                        color=0xE74C3C,
                        timestamp=datetime.now(timezone.utc),
                    ))
            elif usage >= DISK_WARNING_THRESHOLD:
                if self._should_alert(f"disk_warn_{mount}"):
                    alerts.append(discord.Embed(
                        title="⚠️ High Disk Usage",
                        description=f"`{mount}` is at {usage:.0f}%",
                        color=0xF39C12,
                        timestamp=datetime.now(timezone.utc),
                    ))

        for alert in alerts:
            await self._send_alert(alert)

        if alerts:
            logger.info(f"Health sweep: {len(alerts)} alert(s) sent")
        else:
            logger.debug("Health sweep: all clear")

    # -----------------------------------------------------------------------
    # Service monitoring — detect crashed/restarted services
    # -----------------------------------------------------------------------

    async def _service_monitor_loop(self):
        """Periodic service status monitoring."""
        # Initialize service states
        await self._init_service_states()

        while self._running:
            try:
                await asyncio.sleep(SERVICE_CHECK_INTERVAL)
                await self._do_service_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Service monitor error: {e}")
                await asyncio.sleep(30)

    async def _init_service_states(self):
        """Record initial service states."""
        for svc in MONITORED_SERVICES:
            self._last_service_states[svc] = self._get_service_state(svc)

    async def _do_service_check(self):
        """Check all monitored services for state changes."""
        for svc in MONITORED_SERVICES:
            current_state = self._get_service_state(svc)
            previous_state = self._last_service_states.get(svc, "unknown")

            if current_state != previous_state:
                if current_state == "failed":
                    if self._should_alert(f"svc_failed_{svc}"):
                        embed = discord.Embed(
                            title=f"🚨 Service Failed: {svc}",
                            description=f"**{svc}** has entered a **failed** state.\nPrevious: {previous_state} → Current: {current_state}",
                            color=0xE74C3C,
                            timestamp=datetime.now(timezone.utc),
                        )
                        embed.add_field(
                            name="Recovery",
                            value=f"Run `!restart {svc}` or investigate with `!logs {svc}`",
                            inline=False,
                        )
                        await self._send_alert(embed)

                elif current_state == "inactive" and previous_state == "active":
                    if self._should_alert(f"svc_stopped_{svc}"):
                        embed = discord.Embed(
                            title=f"⚠️ Service Stopped: {svc}",
                            description=f"**{svc}** was **active** and is now **inactive**.",
                            color=0xF39C12,
                            timestamp=datetime.now(timezone.utc),
                        )
                        await self._send_alert(embed)

                elif current_state == "active" and previous_state in ("failed", "inactive"):
                    # Service recovered — good news, low priority alert
                    if self._should_alert(f"svc_recovered_{svc}", cooldown=600):
                        embed = discord.Embed(
                            title=f"✅ Service Recovered: {svc}",
                            description=f"**{svc}** is back to **active** (was {previous_state}).",
                            color=0x2ECC71,
                            timestamp=datetime.now(timezone.utc),
                        )
                        await self._send_alert(embed)

            self._last_service_states[svc] = current_state

    # -----------------------------------------------------------------------
    # Disk alert — dedicated disk space monitoring
    # -----------------------------------------------------------------------

    async def _disk_alert_loop(self):
        """Periodic disk space check."""
        while self._running:
            try:
                await asyncio.sleep(DISK_ALERT_INTERVAL)
                # Disk is also checked in health sweep, but this runs
                # independently with different interval for redundancy
                disk_info = self._get_disk_info()
                for mount, usage in disk_info.items():
                    if usage >= DISK_CRITICAL_THRESHOLD:
                        if self._should_alert(f"disk_alert_{mount}", cooldown=DISK_ALERT_INTERVAL):
                            embed = discord.Embed(
                                title="🚨 Disk Space Critical",
                                description=f"`{mount}` is at {usage:.0f}% capacity.",
                                color=0xE74C3C,
                                timestamp=datetime.now(timezone.utc),
                            )
                            embed.add_field(
                                name="Action Needed",
                                value="Consider cleaning up old logs, Docker images, or temporary files.",
                                inline=False,
                            )
                            await self._send_alert(embed)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Disk alert error: {e}")
                await asyncio.sleep(60)

    # -----------------------------------------------------------------------
    # Memory decay — time-weighted relevance scoring
    # -----------------------------------------------------------------------

    async def _memory_decay_loop(self):
        """Periodically apply relevance decay to stored memories."""
        while self._running:
            try:
                await asyncio.sleep(MEMORY_DECAY_INTERVAL)
                if self.memory_store:
                    self._apply_memory_decay()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory decay error: {e}")
                await asyncio.sleep(300)

    def _apply_memory_decay(self):
        """
        Apply time-weighted relevance decay to memories.

        Older memories receive a lower relevance score, making them less
        likely to be recalled unless they match the query very closely.
        """
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.environ.get("PG_HOST", "/var/run/postgresql"),
                dbname=os.environ.get("PG_DB", "tango"),
                user=os.environ.get("POSTGRES_USER", "root"),
            )
            cur = conn.cursor()

            # Update relevance based on age: newer = higher relevance
            # Relevance decays by ~1% per day, floor at 0.1
            cur.execute("""
                UPDATE memory_facts
                SET relevance = GREATEST(0.1, 1.0 - EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400 * 0.01)
                WHERE relevance IS NOT NULL
            """)
            conn.commit()
            cur.close()
            conn.close()
            logger.info("Memory decay applied")
        except Exception as e:
            logger.error(f"Memory decay failed: {e}")

    # -----------------------------------------------------------------------
    # System info helpers
    # -----------------------------------------------------------------------

    def _get_service_state(self, service: str) -> str:
        """Get the current state of a systemd service."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def _get_memory_info(self) -> Optional[dict]:
        """Get memory usage info."""
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            info = {}
            for line in lines:
                if line.startswith("MemTotal:"):
                    info["total"] = int(line.split()[1]) // 1024  # KB to MB
                elif line.startswith("MemAvailable:"):
                    info["available"] = int(line.split()[1]) // 1024
            if "total" in info and "available" in info:
                info["used"] = info["total"] - info["available"]
                info["used_pct"] = (info["used"] / info["total"]) * 100
                return info
        except Exception:
            pass
        return None

    def _get_disk_info(self) -> dict[str, float]:
        """Get disk usage for physical mounts only."""
        # Exclude Docker overlays, virtual fs, credentials, and user mounts
        EXCLUDE_PREFIXES = (
            "/var/lib/docker",
            "/run/credentials",
            "/run/user",
            "/dev/shm",
            "/sys/",
        )
        try:
            result = subprocess.run(
                ["df", "-h", "--output=target,pcent"],
                capture_output=True, text=True, timeout=10,
            )
            disk = {}
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    mount = parts[0]
                    usage_str = parts[1].replace("pct", "")
                    try:
                        usage = float(usage_str)
                        # Skip excluded and non-physical mounts
                        if any(mount.startswith(p) for p in EXCLUDE_PREFIXES):
                            continue
                        if mount.startswith("/dev") or mount.startswith("/"):
                            disk[mount] = usage
                    except ValueError:
                        pass
            # Safety cap: limit to 10 mounts to prevent embed overflow
            if len(disk) > 10:
                priority = ["/", "/boot", "/tmp"]
                kept = {m: u for m, u in disk.items() if m in priority}
                remaining = {m: u for m, u in disk.items() if m not in priority}
                kept.update(dict(sorted(remaining.items(), key=lambda x: -x[1])[:10 - len(kept)]))
                disk = kept
            return disk
        except Exception:
            return {}

    # -----------------------------------------------------------------------
    # Manual sweep — can be triggered by the bot on demand
    # -----------------------------------------------------------------------

    async def run_manual_sweep(self) -> discord.Embed:
        """Run a manual health sweep and return an embed with results."""
        load_avg = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        cpu_pct = (load_avg / cpu_count) * 100
        mem_info = self._get_memory_info()
        disk_info = self._get_disk_info()
        service_states = {svc: self._get_service_state(svc) for svc in MONITORED_SERVICES}

        embed = discord.Embed(
            title="🔍 Proactive Sweep Results",
            color=0x1ABC9C,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="CPU",
            value=f"{cpu_pct:.0f}% (load: {load_avg:.2f}, {cpu_count} cores)",
            inline=True,
        )

        if mem_info:
            embed.add_field(
                name="Memory",
                value=f"{mem_info['used_pct']:.0f}% ({mem_info['used']}MB / {mem_info['total']}MB)",
                inline=True,
            )

        disk_lines = []
        for mount, usage in disk_info.items():
            icon = "🚨" if usage >= DISK_CRITICAL_THRESHOLD else "⚠️" if usage >= DISK_WARNING_THRESHOLD else "✅"
            disk_lines.append(f"{icon} `{mount}`: {usage:.0f}%")
        embed.add_field(
            name="Disk",
            value="\n".join(disk_lines) if disk_lines else "No data",
            inline=False,
        )

        svc_lines = []
        for svc, state in service_states.items():
            icon = "✅" if state == "active" else "🔴" if state == "failed" else "⚪"
            svc_lines.append(f"{icon} `{svc}`: {state}")
        embed.add_field(
            name="Monitored Services",
            value="\n".join(svc_lines),
            inline=False,
        )

        embed.set_footer(text="Phase 5.1 — Proactive Monitoring")
        return embed
