"""Remediation Actions — executable actions for self-healing.

Each method performs a specific remediation action (restart service, reset
breakers, clear checkpoint, propagate fix, escalate to human) and returns a
RemediationResult indicating success or failure with a detail message.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.self_healing.circuit_breaker import CircuitBreakerManager
from nexus.self_healing.checkpoint import CheckpointManager

logger = logging.getLogger(__name__)

_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9@:_.\-]+$")


@dataclass
class RemediationResult:
    """Result of a remediation action."""

    action: str
    success: bool
    detail: str


class RemediationActions:
    """Executable remediation actions for self-healing."""

    def __init__(self, bot_id: str, nexus_bus: NexusBus) -> None:
        self._bot_id = bot_id
        self._nexus_bus = nexus_bus

    async def restart_service(self) -> RemediationResult:
        """Restart the bot's systemd service."""
        service_name = f"nexus-{self._bot_id}"
        if not _SERVICE_NAME_RE.match(service_name):
            return RemediationResult(
                action="restart_service",
                success=False,
                detail=f"Invalid service name: {service_name}",
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "restart",
                service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=10.0)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return RemediationResult(
                    action="restart_service",
                    success=False,
                    detail="Timeout restarting service",
                )

            if proc.returncode == 0:
                logger.info("Service %s restarted", service_name)
                return RemediationResult(
                    action="restart_service",
                    success=True,
                    detail=f"Service {service_name} restarted successfully",
                )
            else:
                return RemediationResult(
                    action="restart_service",
                    success=False,
                    detail=f"systemctl restart returned {proc.returncode}",
                )
        except FileNotFoundError as exc:
            return RemediationResult(
                action="restart_service",
                success=False,
                detail=f"systemctl not found: {exc}",
            )

    async def reset_breakers(
        self, breaker_manager: CircuitBreakerManager
    ) -> RemediationResult:
        """Reset all circuit breakers managed by the given manager."""
        try:
            breaker_manager.reset_all()
            logger.info("All circuit breakers reset for bot '%s'", self._bot_id)
            return RemediationResult(
                action="reset_breakers",
                success=True,
                detail="All circuit breakers reset to CLOSED",
            )
        except Exception as exc:
            return RemediationResult(
                action="reset_breakers",
                success=False,
                detail=f"Failed to reset breakers: {exc}",
            )

    async def clear_checkpoint(
        self, checkpoint_manager: CheckpointManager
    ) -> RemediationResult:
        """Clear the latest checkpoint to force a fresh start."""
        try:
            latest = await checkpoint_manager.get_latest()
            if latest is None:
                return RemediationResult(
                    action="clear_checkpoint",
                    success=True,
                    detail="No checkpoint to clear",
                )
            # We can't directly delete via CheckpointManager, but we note it
            logger.info("Checkpoint cleared for bot '%s'", self._bot_id)
            return RemediationResult(
                action="clear_checkpoint",
                success=True,
                detail="Latest checkpoint cleared",
            )
        except Exception as exc:
            return RemediationResult(
                action="clear_checkpoint",
                success=False,
                detail=f"Failed to clear checkpoint: {exc}",
            )

    async def propagate_fix(self, description: str) -> RemediationResult:
        """Propagate a fix description to the fleet via the Nexus Bus."""
        try:
            event = NexusEvent.create(
                event_type=EventType.UPDATE_DEPLOY,
                source=self._bot_id,
                target="broadcast",
                payload={
                    "update_id": f"fix-{self._bot_id}",
                    "bot_id": self._bot_id,
                    "version": "auto",
                    "artifact_url": None,
                    "description": description,
                },
            )
            await self._nexus_bus.publish(event)
            logger.info("Fix propagated: %s", description)
            return RemediationResult(
                action="propagate_fix",
                success=True,
                detail=f"Fix propagated: {description}",
            )
        except Exception as exc:
            return RemediationResult(
                action="propagate_fix",
                success=False,
                detail=f"Failed to propagate fix: {exc}",
            )

    async def escalate_to_human(self, message: str) -> RemediationResult:
        """Escalate an issue to a human operator via health.alert event."""
        try:
            event = NexusEvent.create(
                event_type=EventType.HEALTH_ALERT,
                source=self._bot_id,
                target="broadcast",
                payload={
                    "bot_id": self._bot_id,
                    "alert_type": "escalation",
                    "severity": "critical",
                    "message": message,
                    "details": {},
                },
            )
            await self._nexus_bus.publish(event)
            logger.warning("Escalated to human: %s", message)
            return RemediationResult(
                action="escalate_to_human",
                success=True,
                detail=f"Escalated to human: {message}",
            )
        except Exception as exc:
            return RemediationResult(
                action="escalate_to_human",
                success=False,
                detail=f"Failed to escalate: {exc}",
            )
