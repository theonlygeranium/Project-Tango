"""Crash-Loop Detector — monitors systemd restart counts and masks services in a loop.

When a bot's systemd service restarts too many times within a time window,
the detector masks the service (preventing further restarts), writes a marker
file, and publishes alerts to the Nexus Bus.
"""

from __future__ import annotations

import asyncio
import logging
import re
from enum import Enum
from pathlib import Path

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent

logger = logging.getLogger(__name__)

_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9@:_.\-]+$")


class CrashLoopStatus(Enum):
    HEALTHY = "healthy"
    CRASH_LOOP_DETECTED = "crash_loop_detected"
    SERVICE_MASKED = "service_masked"
    CHECK_FAILED = "check_failed"


class CrashLoopDetector:
    """Detects crash loops via systemd restart counts and remediates by masking."""

    MARKER_DIR = Path("/tmp")

    def __init__(
        self,
        bot_id: str,
        service_name: str,
        max_consecutive_failures: int = 5,
        window_seconds: int = 120,
        nexus_bus: NexusBus | None = None,
    ) -> None:
        self._bot_id = bot_id
        self._service_name = service_name
        self._max_consecutive_failures = max_consecutive_failures
        self._window_seconds = window_seconds
        self._nexus_bus = nexus_bus
        self._marker_path = self.MARKER_DIR / f"{bot_id}-crash-loop-marker"

    async def check_and_remediate(self) -> CrashLoopStatus:
        """Check restart count and remediate if a crash loop is detected."""
        try:
            if self._marker_exists():
                logger.warning("Crash-loop marker already exists for %s", self._bot_id)
                return CrashLoopStatus.SERVICE_MASKED

            restart_count = await self._get_systemd_restart_count()

            if restart_count >= self._max_consecutive_failures:
                logger.error(
                    "Crash loop detected for %s (restarts=%d, threshold=%d)",
                    self._bot_id,
                    restart_count,
                    self._max_consecutive_failures,
                )
                await self._mask_service()
                self._write_marker()
                await self._publish_alert(restart_count)
                return CrashLoopStatus.CRASH_LOOP_DETECTED

            return CrashLoopStatus.HEALTHY
        except Exception as exc:
            logger.error("Crash-loop check failed for %s: %s", self._bot_id, exc)
            return CrashLoopStatus.CHECK_FAILED

    async def get_restart_count(self) -> int:
        """Return the current systemd restart count for the service."""
        return await self._get_systemd_restart_count()

    async def suppress_restart(self) -> None:
        """Suppress further restarts by masking the service and writing the marker."""
        await self._mask_service()
        self._write_marker()
        logger.info("Restart suppressed for %s", self._bot_id)

    async def _get_systemd_restart_count(self) -> int:
        """Parse systemctl output to get the NRestarts count."""
        if not _SERVICE_NAME_RE.match(self._service_name):
            raise ValueError(f"Invalid service name: {self._service_name}")

        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "show",
            self._service_name,
            "--property=NRestarts",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            logger.warning("systemctl show failed: %s", stderr_text)
            return 0

        output = stdout.decode().strip()
        # Parse "NRestarts=5"
        for line in output.splitlines():
            if line.startswith("NRestarts="):
                try:
                    return int(line.split("=", 1)[1])
                except ValueError:
                    logger.warning("Could not parse NRestarts from: %s", line)
                    return 0
        return 0

    async def _is_service_active(self) -> bool:
        """Check if the systemd service is currently active."""
        if not _SERVICE_NAME_RE.match(self._service_name):
            raise ValueError(f"Invalid service name: {self._service_name}")

        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            self._service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise

        return stdout.decode().strip() == "active"

    async def _mask_service(self) -> None:
        """Mask the systemd service to prevent restarts."""
        if not _SERVICE_NAME_RE.match(self._service_name):
            raise ValueError(f"Invalid service name: {self._service_name}")

        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "mask",
            self._service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise

        logger.warning("Service %s masked due to crash loop", self._service_name)

    def _marker_exists(self) -> bool:
        """Check if the crash-loop marker file exists."""
        return self._marker_path.exists()

    def _write_marker(self) -> None:
        """Write the crash-loop marker file."""
        try:
            self._marker_path.write_text(
                f"bot_id={self._bot_id}\nservice={self._service_name}\n"
            )
        except OSError as exc:
            logger.error("Failed to write marker file: %s", exc)

    def _clear_marker(self) -> None:
        """Remove the crash-loop marker file."""
        try:
            if self._marker_path.exists():
                self._marker_path.unlink()
        except OSError as exc:
            logger.error("Failed to clear marker file: %s", exc)

    async def _publish_alert(self, restart_count: int) -> None:
        """Publish health.alert and task.new events to the Nexus Bus."""
        if self._nexus_bus is None:
            return

        alert_event = NexusEvent.create(
            event_type=EventType.HEALTH_ALERT,
            source=self._bot_id,
            target="broadcast",
            payload={
                "bot_id": self._bot_id,
                "alert_type": "crash_loop",
                "severity": "critical",
                "message": f"Crash loop detected: {restart_count} restarts",
                "details": {
                    "service_name": self._service_name,
                    "restart_count": restart_count,
                    "threshold": self._max_consecutive_failures,
                },
            },
        )
        await self._nexus_bus.publish(alert_event)

        task_event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source=self._bot_id,
            target="voss",
            payload={
                "task_id": f"crash-loop-{self._bot_id}",
                "task_type": "remediation",
                "description": f"Bot {self._bot_id} entered crash loop ({restart_count} restarts). Service masked. Manual intervention required.",
                "priority": "critical",
                "deadline": None,
            },
        )
        await self._nexus_bus.publish(task_event)
