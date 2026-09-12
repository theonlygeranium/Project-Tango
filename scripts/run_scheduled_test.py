#!/usr/bin/env python3
"""
Scheduled Test Runner for Proctor Bot
======================================
Runs the test suite programmatically without requiring Discord interaction.
Used by systemd timer for automated hourly testing.

Author: Jeff Geronimo
Date: 2026-08-18
"""

import asyncio
import sys
import os
import logging

# Add scripts directory to path
sys.path.insert(0, "/opt/Project-Tango/scripts")

from proctor_test_framework import (
    ProctorTestRunner,
    TestPriority,
    TestStatus,
    initialize_test_framework
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/proctor-scheduled-tests.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class MockDiscordBot:
    """Mock Discord bot for programmatic testing."""

    def __init__(self):
        self.user = type('User', (), {'id': 1539047471899086988})()

    def get_channel(self, channel_id):
        """Mock get_channel - returns None since we're not posting to Discord."""
        return None

    async def wait_for(self, event, check, timeout):
        """Mock wait_for - never waits."""
        raise asyncio.TimeoutError()


async def run_scheduled_tests():
    """Run the test suite programmatically."""
    logger.info("=" * 60)
    logger.info("SCHEDULED TEST RUN STARTING")
    logger.info("=" * 60)

    # Create mock Discord bot
    mock_bot = MockDiscordBot()

    # Initialize test runner using the framework's initialization function
    # Channel ID and admin user ID don't matter since we won't post to Discord
    runner = await initialize_test_framework(
        bot=mock_bot,
        channel_id=1539104999941079103,  # Proctor channel
        admin_user_id=1075596247966167131
    )

    logger.info(f"Registered {len(runner.test_cases)} test cases")

    # Discover bots before running tests
    await runner.discover_bots()
    logger.info(f"Discovered {len(runner.discovered_bots)} bots")

    # Run all tests
    await runner.run_all_tests()

    # Calculate results
    passed = sum(1 for r in runner.results if r.status == TestStatus.PASSED)
    failed = sum(1 for r in runner.results if r.status == TestStatus.FAILED)
    skipped = sum(1 for r in runner.results if r.status == TestStatus.SKIPPED)
    duration = runner.end_time - runner.start_time if runner.end_time and runner.start_time else 0

    # Log summary
    logger.info("=" * 60)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Passed:  {passed}")
    logger.info(f"Failed:  {failed}")
    logger.info(f"Skipped: {skipped}")
    logger.info(f"Duration: {duration:.2f}s")
    logger.info("=" * 60)

    # Log individual results
    for result in runner.results:
        status_emoji = "✅" if result.status == TestStatus.PASSED else "❌" if result.status == TestStatus.FAILED else "⏭️"
        logger.info(f"{status_emoji} {result.test_name}: {result.status.value} ({result.duration:.2f}s)")
        if result.error_message:
            logger.warning(f"   Error: {result.error_message}")

    logger.info("=" * 60)

    # Exit with error code if any tests failed
    if failed > 0:
        logger.error(f"SCHEDULED TEST RUN FAILED - {failed} tests failed")
        return 1
    else:
        logger.info("SCHEDULED TEST RUN COMPLETED SUCCESSFULLY")
        return 0


def main():
    """Main entry point."""
    try:
        exit_code = asyncio.run(run_scheduled_tests())
        sys.exit(exit_code)
    except Exception as e:
        logger.error(f"Scheduled test run crashed: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
