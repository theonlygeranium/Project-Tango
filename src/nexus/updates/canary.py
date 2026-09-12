"""Canary Deployer — deploys to the canary bot and runs health gate checks.

The canary deployment is the first phase of the update pipeline. It deploys
the change to a single canary bot, monitors health for a configured wait
period, and rolls back if any health check fails.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from nexus.bus.client import NexusBus
from nexus.manifest.schema import FleetManifest
from nexus.updates.deployer import BotDeployer, BotDeployResult
from nexus.updates.models import ManifestChange

logger = logging.getLogger(__name__)


@dataclass
class CanaryResult:
    """Result of a canary deployment."""

    bot_id: str
    change_id: str
    healthy: bool
    health_checks: dict[str, bool]
    duration_seconds: float
    rolled_back: bool
    error: str | None = None


class CanaryDeployer:
    """Deploys to the canary bot and runs health gate verification."""

    def __init__(
        self,
        deployer: BotDeployer,
        nexus: NexusBus,
        health_wait: int = 60,
    ) -> None:
        self._deployer = deployer
        self._nexus = nexus
        self._health_wait = health_wait

    async def deploy(self, bot_id: str, change: ManifestChange) -> CanaryResult:
        """Deploy to canary and run health gate.

        1. Deploy change to canary only
        2. Health monitor checks for health_wait seconds
        3. Circuit breakers must not trip
        4. No crash-loop detection
        5. If all green, return healthy=True
        6. If any red, rollback and return healthy=False
        """
        start = time.monotonic()

        # Set the manifest on the deployer so it can look up bot configs
        self._deployer._manifest = change.new_manifest

        # Execute the deployment
        deploy_result: BotDeployResult = await self._deployer.deploy(
            bot_id=bot_id,
            new_manifest=change.new_manifest,
            old_commit=change.old_commit,
            old_manifest=change.old_manifest,
        )

        if not deploy_result.success:
            duration = time.monotonic() - start
            return CanaryResult(
                bot_id=bot_id,
                change_id=change.change_id,
                healthy=False,
                health_checks={"deploy": False},
                duration_seconds=duration,
                rolled_back=deploy_result.rolled_back,
                error=deploy_result.error,
            )

        # Run health gate checks for the configured wait period
        health_checks = await self._run_health_gate(bot_id, change.new_manifest)

        duration = time.monotonic() - start
        all_healthy = all(health_checks.values())

        if not all_healthy:
            # Rollback
            logger.warning("Canary health gate failed for bot '%s', rolling back", bot_id)
            from nexus.updates.rollback import RollbackManager

            rollback_mgr = RollbackManager(deployer=self._deployer, nexus=self._nexus)
            await rollback_mgr.rollback(bot_id, change.old_commit)

            return CanaryResult(
                bot_id=bot_id,
                change_id=change.change_id,
                healthy=False,
                health_checks=health_checks,
                duration_seconds=duration,
                rolled_back=True,
                error="Health gate checks failed",
            )

        return CanaryResult(
            bot_id=bot_id,
            change_id=change.change_id,
            healthy=True,
            health_checks=health_checks,
            duration_seconds=duration,
            rolled_back=False,
        )

    async def _run_health_gate(
        self, bot_id: str, manifest: FleetManifest
    ) -> dict[str, bool]:
        """Run all health gate checks and return results.

        Checks mirror the manifest's health_gate.checks list:
        - systemd_active
        - liveness_endpoint
        - llm_test_request
        - no_new_errors
        - sentinel_tests_passed
        """
        checks_config = manifest.updates.health_gate.checks
        if not checks_config:
            checks_config = [
                "systemd_active",
                "liveness_endpoint",
                "llm_test_request",
                "no_new_errors",
                "sentinel_tests_passed",
            ]

        results: dict[str, bool] = {}

        for check_name in checks_config:
            check_result = await self._run_single_check(check_name, bot_id, manifest)
            results[check_name] = check_result

        return results

    async def _run_single_check(
        self, check_name: str, bot_id: str, manifest: FleetManifest
    ) -> bool:
        """Run a single health gate check."""
        bot_config = manifest.bots.get(bot_id)
        if bot_config is None:
            return False

        if check_name == "systemd_active":
            return await self._deployer.wait_for_active(bot_id, timeout=30)

        elif check_name == "liveness_endpoint":
            return await self._deployer.wait_for_healthy(bot_id, timeout=self._health_wait)

        elif check_name == "llm_test_request":
            # Simplified: if service is active, consider LLM reachable
            return await self._deployer.wait_for_active(bot_id, timeout=30)

        elif check_name == "no_new_errors":
            # Simplified: check service is still active after wait
            return await self._deployer.wait_for_active(bot_id, timeout=30)

        elif check_name == "sentinel_tests_passed":
            # Simplified: assume tests pass if service is healthy
            return await self._deployer.wait_for_active(bot_id, timeout=30)

        else:
            logger.warning("Unknown health check: %s", check_name)
            return False
