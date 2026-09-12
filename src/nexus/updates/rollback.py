"""Rollback Manager — restores bots to previous manifest versions.

Manages rollback snapshots, restores previous configurations, restarts
services, and publishes health alerts when rollbacks occur.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import FleetManifest
from nexus.updates.deployer import BotDeployer

logger = logging.getLogger(__name__)

# Rollback store directory
_ROLLBACK_DIR = Path("/opt/Project-Tango/.rollback")


@dataclass
class RollbackResult:
    """Result of a rollback operation."""

    bot_id: str
    to_version: str
    success: bool
    restored_manifest: FleetManifest | None
    service_active: bool
    health_restored: bool
    error: str | None = None


class RollbackManager:
    """Manages rollback snapshots and restores previous bot versions."""

    def __init__(
        self,
        deployer: BotDeployer,
        nexus: NexusBus,
    ) -> None:
        self._deployer = deployer
        self._nexus = nexus

    async def rollback(self, bot_id: str, to_version: str) -> RollbackResult:
        """Restore bot to previous manifest version.

        1. Load manifest at to_version (from rollback store or git)
        2. Restart bot service with old config
        3. Verify service active and health restored
        4. Publish health.alert with rollback details
        5. Alert human operator via Discord
        """
        start = time.monotonic()

        # Load the previous manifest from rollback store
        restored_manifest = self._load_rollback_manifest(bot_id, to_version)

        if restored_manifest is None:
            return RollbackResult(
                bot_id=bot_id,
                to_version=to_version,
                success=False,
                restored_manifest=None,
                service_active=False,
                health_restored=False,
                error=f"No rollback snapshot found for bot '{bot_id}' at version '{to_version}'",
            )

        # Set the manifest on the deployer
        self._deployer._manifest = restored_manifest

        # Restart the service with old config
        restart_ok = await self._deployer.restart_service(bot_id)

        if not restart_ok:
            return RollbackResult(
                bot_id=bot_id,
                to_version=to_version,
                success=False,
                restored_manifest=restored_manifest,
                service_active=False,
                health_restored=False,
                error=f"Failed to restart service for bot '{bot_id}' during rollback",
            )

        # Verify service is active
        service_active = await self._deployer.wait_for_active(bot_id, timeout=60)

        # Verify health is restored
        health_restored = False
        if service_active:
            health_restored = await self._deployer.wait_for_healthy(bot_id, timeout=60)

        success = service_active and health_restored

        # Publish health.alert event
        await self._publish_rollback_alert(bot_id, to_version, success)

        duration = time.monotonic() - start
        logger.info(
            "Rollback for bot '%s' to version '%s' completed in %.2fs (success=%s)",
            bot_id, to_version, duration, success,
        )

        return RollbackResult(
            bot_id=bot_id,
            to_version=to_version,
            success=success,
            restored_manifest=restored_manifest,
            service_active=service_active,
            health_restored=health_restored,
            error=None if success else "Rollback completed but health not fully restored",
        )

    async def snapshot_previous(
        self, bot_id: str, commit_sha: str, manifest: FleetManifest
    ) -> None:
        """Snapshot current manifest as rollback point before new deploy."""
        rollback_dir = _ROLLBACK_DIR / bot_id
        rollback_dir.mkdir(parents=True, exist_ok=True)

        # Use short commit SHA for filename
        short_sha = commit_sha[:12] if len(commit_sha) >= 12 else commit_sha
        rollback_path = rollback_dir / f"{short_sha}.yaml"

        try:
            manifest_dict = manifest.model_dump(mode="json")
            rollback_path.write_text(
                yaml.dump(manifest_dict, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            logger.info(
                "Snapshot saved for bot '%s' at commit '%s' -> %s",
                bot_id, short_sha, rollback_path,
            )
        except OSError as exc:
            logger.error("Failed to write rollback snapshot: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_rollback_manifest(self, bot_id: str, commit_sha: str) -> FleetManifest | None:
        """Load a manifest from the rollback store."""
        rollback_dir = _ROLLBACK_DIR / bot_id
        short_sha = commit_sha[:12] if len(commit_sha) >= 12 else commit_sha
        rollback_path = rollback_dir / f"{short_sha}.yaml"

        if not rollback_path.exists():
            logger.warning("No rollback snapshot at %s", rollback_path)
            return None

        try:
            data = yaml.safe_load(rollback_path.read_text(encoding="utf-8"))
            if data is None:
                return None
            return FleetManifest.model_validate(data)
        except (yaml.YAMLError, OSError, ValueError) as exc:
            logger.error("Failed to load rollback manifest from %s: %s", rollback_path, exc)
            return None

    async def _publish_rollback_alert(
        self, bot_id: str, to_version: str, success: bool
    ) -> None:
        """Publish a health.alert event with rollback details."""
        alert_event = NexusEvent.create(
            event_type=EventType.HEALTH_ALERT,
            source="rollback-manager",
            target="broadcast",
            payload={
                "bot_id": bot_id,
                "alert_type": "rollback",
                "severity": "critical" if not success else "warning",
                "message": f"Bot '{bot_id}' rolled back to version '{to_version}'",
                "details": {
                    "to_version": to_version,
                    "success": success,
                    "alert_channels": ["discord"],
                },
            },
        )
        await self._nexus.publish(alert_event)
        logger.info("Published rollback health.alert for bot '%s'", bot_id)
