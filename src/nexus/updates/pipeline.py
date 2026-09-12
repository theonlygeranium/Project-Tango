"""Update Pipeline — phased rollout with canary-first deployment and health gates.

Coordinates the full update propagation pipeline: manifest diffing, severity
classification, canary deployment, phased rollout, and automatic rollback on
health failures.
"""

from __future__ import annotations

import logging
import time

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import BotConfig, FleetManifest
from nexus.updates.canary import CanaryDeployer, CanaryResult
from nexus.updates.deployer import BotDeployer
from nexus.updates.models import (
    SEVERITY_RANK,
    ChangeSeverity,
    DeployResult,
    ManifestChange,
)
from nexus.updates.rollback import RollbackManager, RollbackResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Update Pipeline
# ---------------------------------------------------------------------------

class UpdatePipeline:
    """Orchestrates canary-first phased rollouts with health-gated verification."""

    def __init__(
        self,
        nexus: NexusBus,
        manifest: FleetManifest,
        canary_bot_id: str = "cartographer",
        health_check_wait: int = 60,
        deploy_timeout: int = 120,
    ) -> None:
        self._nexus = nexus
        self._manifest = manifest
        self._canary_bot_id = canary_bot_id
        self._health_check_wait = health_check_wait
        self._deploy_timeout = deploy_timeout

        self._deployer = BotDeployer(nexus=nexus, timeout=deploy_timeout)
        self._canary_deployer = CanaryDeployer(
            deployer=self._deployer, nexus=nexus, health_wait=health_check_wait
        )
        self._rollback_manager = RollbackManager(
            deployer=self._deployer, nexus=nexus
        )

    async def deploy_update(self, change: ManifestChange) -> DeployResult:
        """Deploy a manifest change to all affected bots, canary-first.

        1. Run canary on the canary bot first.
        2. On canary pass, roll out to remaining bots in rollout order.
        3. On any health failure, rollback that bot and abort.
        4. Publish update.deploy for each bot.
        """
        start = time.monotonic()
        deployed_bots: list[str] = []
        failed_bots: list[str] = []
        rollback_count = 0

        # Determine rollout order
        rollout_order = self._rollout_order(change.affected_bots, change.severity)

        # Phase 1: Canary deployment
        canary_bot = self._canary_bot_id
        if canary_bot in rollout_order:
            logger.info("Starting canary deployment for bot '%s'", canary_bot)
            canary_result = await self.canary_deploy(canary_bot, change)

            if not canary_result.healthy:
                logger.warning("Canary deployment failed for bot '%s': %s", canary_bot, canary_result.error)
                if canary_result.rolled_back:
                    rollback_count += 1
                failed_bots.append(canary_bot)
                duration = time.monotonic() - start
                return DeployResult(
                    change_id=change.change_id,
                    success=False,
                    deployed_bots=deployed_bots,
                    failed_bots=failed_bots,
                    canary_passed=False,
                    rollback_count=rollback_count,
                    duration_seconds=duration,
                    error=f"Canary deployment failed: {canary_result.error}",
                )

            logger.info("Canary deployment passed for bot '%s'", canary_bot)
            deployed_bots.append(canary_bot)
            await self._publish_update_deploy(change.change_id, canary_bot, change.new_manifest.version)

        # Phase 2: Roll out to remaining bots
        for bot_id in rollout_order:
            if bot_id == canary_bot:
                continue
            if bot_id not in change.affected_bots:
                continue

            logger.info("Deploying to bot '%s'", bot_id)

            # Snapshot previous version before deploying
            old_bot_config = change.old_manifest.bots.get(bot_id)
            if old_bot_config is not None:
                await self._rollback_manager.snapshot_previous(
                    bot_id, change.old_commit, change.old_manifest
                )

            deploy_result = await self._deployer.deploy(
                bot_id=bot_id,
                new_manifest=change.new_manifest,
                old_commit=change.old_commit,
                old_manifest=change.old_manifest,
            )

            if not deploy_result.success:
                logger.error("Deployment failed for bot '%s': %s", bot_id, deploy_result.error)
                if deploy_result.rolled_back:
                    rollback_count += 1
                else:
                    # Deployer didn't rollback, trigger explicit rollback
                    rb_result = await self.rollback(bot_id, change.old_commit)
                    if rb_result.success:
                        rollback_count += 1
                failed_bots.append(bot_id)
                duration = time.monotonic() - start
                return DeployResult(
                    change_id=change.change_id,
                    success=False,
                    deployed_bots=deployed_bots,
                    failed_bots=failed_bots,
                    canary_passed=True,
                    rollback_count=rollback_count,
                    duration_seconds=duration,
                    error=f"Deployment failed for bot '{bot_id}': {deploy_result.error}",
                )

            # Health check after deploy
            healthy = await self.check_health_after_deploy(
                bot_id, self._health_check_wait
            )
            if not healthy:
                logger.error("Health check failed for bot '%s' after deploy", bot_id)
                rb_result = await self.rollback(bot_id, change.old_commit)
                rollback_count += 1
                failed_bots.append(bot_id)
                duration = time.monotonic() - start
                return DeployResult(
                    change_id=change.change_id,
                    success=False,
                    deployed_bots=deployed_bots,
                    failed_bots=failed_bots,
                    canary_passed=True,
                    rollback_count=rollback_count,
                    duration_seconds=duration,
                    error=f"Health check failed for bot '{bot_id}' after deploy",
                )

            deployed_bots.append(bot_id)
            await self._publish_update_deploy(change.change_id, bot_id, change.new_manifest.version)

        duration = time.monotonic() - start
        return DeployResult(
            change_id=change.change_id,
            success=True,
            deployed_bots=deployed_bots,
            failed_bots=failed_bots,
            canary_passed=True,
            rollback_count=rollback_count,
            duration_seconds=duration,
        )

    async def canary_deploy(self, bot_id: str, change: ManifestChange) -> CanaryResult:
        """Deploy to the canary bot and run health gate checks."""
        # Snapshot previous version before canary deploy
        old_bot_config = change.old_manifest.bots.get(bot_id)
        if old_bot_config is not None:
            await self._rollback_manager.snapshot_previous(
                bot_id, change.old_commit, change.old_manifest
            )
        return await self._canary_deployer.deploy(bot_id, change)

    async def rollback(self, bot_id: str, to_version: str) -> RollbackResult:
        """Rollback a bot to a previous manifest version."""
        return await self._rollback_manager.rollback(bot_id, to_version)

    async def check_health_after_deploy(self, bot_id: str, wait_seconds: int = 60) -> bool:
        """Wait for health checks to stabilize after a deploy.

        Returns True if the bot is healthy after the wait period.
        """
        logger.info("Waiting %ds for bot '%s' health to stabilize", wait_seconds, bot_id)

        # Wait for service to become active
        active = await self._deployer.wait_for_active(bot_id, timeout=30)
        if not active:
            logger.warning("Bot '%s' did not become active", bot_id)
            return False

        # Wait for healthy state
        healthy = await self._deployer.wait_for_healthy(bot_id, timeout=wait_seconds)
        return healthy

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _diff_manifests(self, old: FleetManifest, new: FleetManifest) -> list[str]:
        """Identify which bots changed between manifest versions."""
        affected: list[str] = []

        all_bot_ids = set(old.bots.keys()) | set(new.bots.keys())

        for bot_id in all_bot_ids:
            old_bot = old.bots.get(bot_id)
            new_bot = new.bots.get(bot_id)

            if old_bot is None and new_bot is not None:
                affected.append(bot_id)
                continue

            if old_bot is not None and new_bot is None:
                affected.append(bot_id)
                continue

            if old_bot is not None and new_bot is not None:
                if old_bot.model_dump() != new_bot.model_dump():
                    affected.append(bot_id)

        return affected

    def _classify_severity(self, old: FleetManifest, new: FleetManifest, bot_id: str) -> str:
        """Classify change severity for a single bot.

        Returns the highest severity across all changed attributes.
        """
        old_bot = old.bots.get(bot_id)
        new_bot = new.bots.get(bot_id)

        if old_bot is None or new_bot is None:
            return ChangeSeverity.MAJOR

        max_severity = ChangeSeverity.CONFIG_TWEAK

        # Model change is high severity
        if old_bot.model != new_bot.model:
            max_severity = self._max_severity(max_severity, ChangeSeverity.MODEL_CHANGE)

        # System prompt change
        if old_bot.system_prompt_file != new_bot.system_prompt_file:
            max_severity = self._max_severity(max_severity, ChangeSeverity.SYSTEM_PROMPT)

        # Tool changes
        if set(old_bot.tools) != set(new_bot.tools):
            max_severity = self._max_severity(max_severity, ChangeSeverity.TOOL_CHANGE)

        # Other config changes (tier, port, interval, etc.)
        other_fields = [
            "tier", "discord_token_env", "health_check_interval",
            "port", "systemd_service_name", "circuit_breaker_config",
        ]
        for field_name in other_fields:
            if getattr(old_bot, field_name) != getattr(new_bot, field_name):
                max_severity = self._max_severity(max_severity, ChangeSeverity.CONFIG_TWEAK)
                break

        return max_severity

    def _rollout_order(self, affected_bots: list[str], severity: str) -> list[str]:
        """Determine rollout order: canary first, then ascending tier, Admiral last."""
        # Start with the canary bot if it's in the affected set
        order: list[str] = []

        canary = self._canary_bot_id
        if canary in affected_bots:
            order.append(canary)

        # Remaining bots sorted by tier (ascending), Admiral (tier 0) last
        remaining = [b for b in affected_bots if b != canary]

        def tier_of(bot_id: str) -> int:
            bot = self._manifest.bots.get(bot_id)
            if bot is None:
                return 99
            # Admiral (tier 0) should be last, so give it a high sort key
            if bot.tier == 0:
                return 100
            return bot.tier

        remaining.sort(key=tier_of)
        order.extend(remaining)

        return order

    @staticmethod
    def _max_severity(a: str, b: str) -> str:
        """Return the higher of two severity levels."""
        rank_a = SEVERITY_RANK.get(a, 0)
        rank_b = SEVERITY_RANK.get(b, 0)
        return a if rank_a >= rank_b else b

    async def _publish_update_deploy(
        self, change_id: str, bot_id: str, version: str
    ) -> None:
        """Publish an update.deploy event to the Nexus Bus."""
        event = NexusEvent.create(
            event_type=EventType.UPDATE_DEPLOY,
            source="update-pipeline",
            target=bot_id,
            payload={
                "update_id": change_id,
                "bot_id": bot_id,
                "version": version,
                "artifact_url": None,
            },
        )
        await self._nexus.publish(event)
        logger.info("Published update.deploy for bot '%s' (change_id=%s)", bot_id, change_id)
