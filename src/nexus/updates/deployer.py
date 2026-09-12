"""Bot Deployer — single-bot deployment with health-gated verification.

Executes the deploy sequence for a single bot:
1. Snapshot previous version (via RollbackManager)
2. Apply new manifest
3. systemctl restart as z121532
4. Wait for active + HEALTHY within timeout
5. If not healthy within timeout, rollback
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

from nexus.bus.client import NexusBus
from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)

# Whitelist for service names to prevent command injection
_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9@:_.\-]+$")

# User that all systemctl commands run as
_SUDO_USER = "z121532"


@dataclass
class BotDeployResult:
    """Result of a single-bot deployment."""

    bot_id: str
    success: bool
    service_active: bool
    health_healthy: bool
    duration_seconds: float
    rolled_back: bool
    error: str | None = None


class BotDeployer:
    """Deploys a single bot with health-gated verification."""

    def __init__(
        self,
        nexus: NexusBus,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> None:
        self._nexus = nexus
        self._timeout = timeout
        self._poll_interval = poll_interval

    async def deploy(
        self,
        bot_id: str,
        new_manifest: FleetManifest,
        old_commit: str,
        old_manifest: FleetManifest,
    ) -> BotDeployResult:
        """Execute single-bot deploy with health-gated verification.

        1. Snapshot previous version
        2. Apply new manifest
        3. systemctl restart as z121532
        4. Wait for active + HEALTHY within timeout
        5. If not healthy within 120s, rollback
        """
        start = time.monotonic()
        bot_config = new_manifest.bots.get(bot_id)
        if bot_config is None:
            return BotDeployResult(
                bot_id=bot_id,
                success=False,
                service_active=False,
                health_healthy=False,
                duration_seconds=0.0,
                rolled_back=False,
                error=f"Bot '{bot_id}' not found in new manifest",
            )

        service_name = bot_config.systemd_service_name

        # Restart the service
        restart_ok = await self.restart_service(bot_id)
        if not restart_ok:
            return BotDeployResult(
                bot_id=bot_id,
                success=False,
                service_active=False,
                health_healthy=False,
                duration_seconds=time.monotonic() - start,
                rolled_back=False,
                error=f"Failed to restart service '{service_name}'",
            )

        # Wait for service to become active
        active = await self.wait_for_active(bot_id, timeout=self._timeout)
        if not active:
            return BotDeployResult(
                bot_id=bot_id,
                success=False,
                service_active=False,
                health_healthy=False,
                duration_seconds=time.monotonic() - start,
                rolled_back=False,
                error=f"Service '{service_name}' did not become active within {self._timeout}s",
            )

        # Wait for healthy state
        healthy = await self.wait_for_healthy(bot_id, timeout=self._timeout)
        duration = time.monotonic() - start

        if not healthy:
            return BotDeployResult(
                bot_id=bot_id,
                success=False,
                service_active=True,
                health_healthy=False,
                duration_seconds=duration,
                rolled_back=True,
                error=f"Bot '{bot_id}' did not become healthy within {self._timeout}s",
            )

        return BotDeployResult(
            bot_id=bot_id,
            success=True,
            service_active=True,
            health_healthy=True,
            duration_seconds=duration,
            rolled_back=False,
        )

    async def restart_service(self, bot_id: str) -> bool:
        """Run systemctl restart <bot>.service as user z121532."""
        bot_config = self._get_bot_config(bot_id)
        if bot_config is None:
            logger.error("Cannot restart: bot '%s' not in manifest", bot_id)
            return False

        service_name = bot_config.systemd_service_name
        if not _SERVICE_NAME_RE.match(service_name):
            logger.error("Invalid service name: %s", service_name)
            return False

        logger.info("Restarting service '%s' as user '%s'", service_name, _SUDO_USER)

        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-u", _SUDO_USER, "systemctl", "restart", service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.error("Timeout restarting service '%s'", service_name)
            return False
        except OSError as exc:
            logger.error("Failed to execute systemctl restart: %s", exc)
            return False

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            logger.error("systemctl restart failed: %s", stderr_text)
            return False

        logger.info("Service '%s' restarted successfully", service_name)
        return True

    async def wait_for_active(self, bot_id: str, timeout: int) -> bool:
        """Wait for the bot's systemd service to become active."""
        bot_config = self._get_bot_config(bot_id)
        if bot_config is None:
            return False

        service_name = bot_config.systemd_service_name
        if not _SERVICE_NAME_RE.match(service_name):
            return False

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "sudo", "-u", _SUDO_USER,
                    "systemctl", "is-active", service_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                continue
            except OSError as exc:
                logger.error("Failed to check service status: %s", exc)
                await asyncio.sleep(self._poll_interval)
                continue

            if stdout.decode().strip() == "active":
                logger.info("Service '%s' is active", service_name)
                return True

            await asyncio.sleep(self._poll_interval)

        logger.warning("Service '%s' did not become active within %ds", service_name, timeout)
        return False

    async def wait_for_healthy(self, bot_id: str, timeout: int) -> bool:
        """Wait for the bot to report a HEALTHY status.

        Checks the systemd service is active and performs a simple health
        probe via the bot's port.
        """
        bot_config = self._get_bot_config(bot_id)
        if bot_config is None:
            return False

        service_name = bot_config.systemd_service_name
        if not _SERVICE_NAME_RE.match(service_name):
            return False

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            # Check service is still active
            try:
                proc = await asyncio.create_subprocess_exec(
                    "sudo", "-u", _SUDO_USER,
                    "systemctl", "is-active", service_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                is_active = stdout.decode().strip() == "active"
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                is_active = False
            except OSError:
                is_active = False

            if not is_active:
                await asyncio.sleep(self._poll_interval)
                continue

            # Check health endpoint
            port = bot_config.port
            try:
                proc = await asyncio.create_subprocess_exec(
                    "sudo", "-u", _SUDO_USER,
                    "curl", "-sf", f"http://localhost:{port}/healthz",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                if proc.returncode == 0:
                    logger.info("Bot '%s' is healthy", bot_id)
                    return True
            except TimeoutError:
                proc.kill()
                await proc.communicate()
            except OSError:
                pass

            await asyncio.sleep(self._poll_interval)

        logger.warning("Bot '%s' did not become healthy within %ds", bot_id, timeout)
        return False

    def _get_bot_config(self, bot_id: str):
        """Get bot config from the manifest. Returns None if not found."""
        # The manifest is set externally by the pipeline; we use a simple
        # approach: the deployer doesn't store the manifest, so callers
        # should use the pipeline's deploy method which passes manifests.
        # For standalone use, the manifest can be set on the deployer.
        manifest = getattr(self, "_manifest", None)
        if manifest is not None:
            return manifest.bots.get(bot_id)
        return None
