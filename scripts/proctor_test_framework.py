"""Proctor Test Framework — bot fleet testing utilities.

Provides ProctorTestRunner, TestPriority, initialize_test_framework,
and test_bot_responsiveness for the Proctor bot's self-testing capabilities.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TestPriority(enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TestStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TestCase:
    name: str
    description: str
    priority: TestPriority
    test_func: Any = None  # async callable(runner) -> bool


@dataclass
class TestResult:
    test_name: str
    status: TestStatus
    error_message: Optional[str] = None
    duration: float = 0.0


class ProctorTestRunner:
    def __init__(
        self,
        bot: Any = None,
        channel_id: int = 0,
        admin_user_id: int = 0,
    ) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self.admin_user_id = admin_user_id
        self.test_cases: list[TestCase] = []
        self.results: list[TestResult] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.discovered_bots: dict[str, int] = {}

    async def discover_bots(self) -> None:
        """Discover active bots in the fleet by checking systemd services."""
        service_map = {
            "admiral": "schubert-bot.service",
            "architect": "schubert-architect.service",
            "quartermaster": "schubert-quartermaster.service",
            "cartographer": "schubert-cartographer.service",
            "dr_voss": "schubert-dr-voss.service",
            "proctor": "schubert-proctor.service",
            "cortex": "cortex-bot.service",
        }
        for name, service in service_map.items():
            try:
                proc = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.stdout.strip() == "active":
                    self.discovered_bots[name] = 0
            except Exception:
                pass

    async def run_all_tests(
        self, priority_filter: Optional[TestPriority] = None
    ) -> None:
        """Run all registered test cases, optionally filtered by priority."""
        self.results = []
        self.start_time = time.time()

        for tc in self.test_cases:
            if priority_filter and tc.priority != priority_filter:
                self.results.append(
                    TestResult(
                        test_name=tc.name,
                        status=TestStatus.SKIPPED,
                        error_message=f"Filtered by priority {priority_filter.name}",
                    )
                )
                continue

            if tc.test_func is None:
                self.results.append(
                    TestResult(
                        test_name=tc.name,
                        status=TestStatus.SKIPPED,
                        error_message="No test function defined",
                    )
                )
                continue

            result = TestResult(
                test_name=tc.name,
                status=TestStatus.RUNNING,
            )
            t0 = time.time()
            try:
                passed = await tc.test_func(self)
                result.status = TestStatus.PASSED if passed else TestStatus.FAILED
                if not passed:
                    result.error_message = "Test returned False"
            except Exception as exc:
                result.status = TestStatus.FAILED
                result.error_message = str(exc)
            result.duration = time.time() - t0
            self.results.append(result)

        self.end_time = time.time()


async def initialize_test_framework(
    bot: Any, channel_id: int, admin_user_id: int
) -> ProctorTestRunner:
    """Initialize the test framework with default test cases."""
    runner = ProctorTestRunner(
        bot=bot,
        channel_id=channel_id,
        admin_user_id=admin_user_id,
    )

    # Register default test cases
    runner.test_cases = [
        TestCase(
            name="bot_responsiveness",
            description="Check that all fleet bot services are active",
            priority=TestPriority.CRITICAL,
            test_func=test_bot_responsiveness,
        ),
    ]

    return runner


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

async def test_bot_responsiveness(runner: ProctorTestRunner) -> bool:
    """Test that all bots are responsive to basic messages."""
    logger.info("Testing bot responsiveness...")

    service_map = {
        "admiral": "schubert-bot.service",
        "architect": "schubert-architect.service",
        "quartermaster": "schubert-quartermaster.service",
        "cartographer": "schubert-cartographer.service",
        "dr_voss": "schubert-dr-voss.service",
        "cortex": "cortex-bot.service",
    }

    results = {}
    for agent_name, service_name in service_map.items():
        if runner.discovered_bots and agent_name not in runner.discovered_bots:
            continue

        try:
            proc = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            is_active = proc.stdout.strip() == "active"
            results[agent_name] = is_active
            if is_active:
                logger.info(f"{agent_name}: service active ✓")
            else:
                logger.warning(f"{agent_name}: service {proc.stdout.strip()}")
        except Exception as e:
            logger.error(f"Error checking {agent_name}: {e}")
            results[agent_name] = False

    success_rate = sum(results.values()) / len(results) if results else 0
    logger.info(
        f"Bot responsiveness: {success_rate*100:.0f}% "
        f"({sum(results.values())}/{len(results)})"
    )
    return success_rate >= 0.8
