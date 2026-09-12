"""Nexus Fleet Model deployment script.

Deploys the Nexus framework to the Schubert V2 environment.

Usage:
    python -m scripts.deploy_nexus          # Full deployment
    python -m scripts.deploy_nexus --check   # Validate only (no changes)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from nexus.manifest import load_manifest

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "fleet-manifest.yaml"
VENV_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
SUDO_USER = "z121532"


async def deploy() -> None:
    """Full deployment sequence:
    1. Validate fleet manifest
    2. Install dependencies
    3. Run test suite
    4. Initialize Nexus Bus consumer groups
    5. Start bot services in rollout order
    6. Verify fleet health
    """
    logger.info("=== Nexus Fleet Model Deployment ===")

    manifest = await validate_manifest()
    if manifest is None:
        logger.error("Manifest validation failed — aborting deployment")
        sys.exit(1)

    await install_dependencies()
    await run_tests()
    await initialize_bus(manifest)
    await start_services(manifest)
    await verify_health(manifest)

    logger.info("=== Deployment Complete ===")


async def validate_manifest() -> Any | None:
    """Load and validate fleet-manifest.yaml."""
    logger.info("Step 1: Validating fleet manifest")
    try:
        manifest = load_manifest(MANIFEST_PATH)
        logger.info(
            "Manifest validated: v%s with %d bots",
            manifest.version,
            len(manifest.bots),
        )
        for bot_id, bot_config in manifest.bots.items():
            logger.info(
                "  %s: tier=%d, port=%d, service=%s",
                bot_id,
                bot_config.tier,
                bot_config.port,
                bot_config.systemd_service_name,
            )
        return manifest
    except Exception as exc:
        logger.error("Manifest validation failed: %s", exc)
        return None


async def install_dependencies() -> None:
    """Install Python dependencies from pyproject.toml."""
    logger.info("Step 2: Installing dependencies")
    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PYTHON), "-m", "pip", "install", "-e", ".[dev]",
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        if proc.returncode == 0:
            logger.info("Dependencies installed successfully")
        else:
            logger.error(
                "pip install failed: %s",
                stderr.decode() if stderr else "unknown error",
            )
            sys.exit(1)
    except TimeoutError:
        logger.error("pip install timed out")
        sys.exit(1)
    except OSError as exc:
        logger.error("Failed to run pip install: %s", exc)
        sys.exit(1)


async def run_tests() -> None:
    """Run the full test suite."""
    logger.info("Step 3: Running test suite")
    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PYTHON), "-m", "pytest", "src/nexus/tests/", "-v", "--tb=short",
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode == 0:
            logger.info("All tests passed")
        else:
            logger.error(
                "Test suite failed:\n%s",
                stdout.decode() if stdout else "",
            )
            sys.exit(1)
    except TimeoutError:
        logger.error("Test suite timed out")
        sys.exit(1)
    except OSError as exc:
        logger.error("Failed to run test suite: %s", exc)
        sys.exit(1)


async def initialize_bus(manifest: Any) -> None:
    """Create Nexus Bus consumer groups for all bots."""
    logger.info("Step 4: Initializing Nexus Bus consumer groups")

    from nexus.bus.client import STREAM_MAP

    redis_url = manifest.defaults.redis_url
    logger.info("Connecting to Redis at %s", redis_url)

    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await redis_client.ping()
        logger.info("Redis connection verified")

        group_name = manifest.nexus_bus.consumer_group
        streams = set(STREAM_MAP.values())
        for stream in streams:
            try:
                await redis_client.xgroup_create(stream, group_name, id="0")
                logger.info("Created consumer group '%s' on stream '%s'", group_name, stream)
            except Exception as exc:
                if "BUSYGROUP" in str(exc):
                    logger.debug("Group '%s' already exists on stream '%s'", group_name, stream)
                else:
                    logger.warning("Failed to create group on %s: %s", stream, exc)

        logger.info("Nexus Bus consumer groups initialized")
    finally:
        await redis_client.aclose()


async def start_services(manifest: Any) -> None:
    """Start bot services in rollout order."""
    logger.info("Step 5: Starting bot services in rollout order")

    rollout_order = manifest.updates.rollout_order
    if not rollout_order:
        rollout_order = list(manifest.bots.keys())

    for bot_id in rollout_order:
        bot_config = manifest.bots.get(bot_id)
        if bot_config is None:
            logger.warning("Bot %s not in manifest, skipping", bot_id)
            continue

        service_name = bot_config.systemd_service_name
        logger.info("Starting %s (%s)...", bot_id, service_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-u", SUDO_USER, "systemctl", "start", service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode == 0:
                logger.info("  Started %s", service_name)
            else:
                logger.error(
                    "  Failed to start %s: %s",
                    service_name,
                    stderr.decode().strip() if stderr else "unknown",
                )
        except TimeoutError:
            logger.error("  Timeout starting %s", service_name)
        except OSError as exc:
            logger.error("  Failed to execute systemctl: %s", exc)

        # Wait between starts for health stabilization
        logger.info("  Waiting 60s for health stabilization...")
        await asyncio.sleep(60)

        # Check if service is active
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-u", SUDO_USER, "systemctl", "is-active", service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            status = stdout.decode().strip() if stdout else "unknown"
            if status == "active":
                logger.info("  %s is active", service_name)
            else:
                logger.warning("  %s is not active (status=%s)", service_name, status)
        except Exception as exc:
            logger.warning("  Could not check status of %s: %s", service_name, exc)


async def verify_health(manifest: Any) -> None:
    """Verify all bots are healthy after deployment."""
    logger.info("Step 6: Verifying fleet health")

    all_healthy = True
    for bot_id, bot_config in manifest.bots.items():
        service_name = bot_config.systemd_service_name
        port = bot_config.port

        # Check systemd service
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-u", SUDO_USER, "systemctl", "is-active", service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            is_active = stdout.decode().strip() == "active" if stdout else False
        except Exception:
            is_active = False

        if is_active:
            logger.info("  %s: service active", bot_id)
        else:
            logger.error("  %s: service NOT active", bot_id)
            all_healthy = False

    if all_healthy:
        logger.info("All bots are healthy — deployment successful")
    else:
        logger.warning("Some bots are not healthy — check logs for details")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(deploy())
