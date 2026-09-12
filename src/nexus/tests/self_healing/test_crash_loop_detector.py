"""Tests for CrashLoopDetector — uses mocked subprocess for systemd commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType
from nexus.self_healing.crash_loop_detector import CrashLoopDetector, CrashLoopStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProcess:
    """Fake asyncio subprocess for mocking systemctl commands."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        pass


def _make_subprocess_mock(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Create a mock for asyncio.create_subprocess_exec."""
    proc = _FakeProcess(stdout=stdout, stderr=stderr, returncode=returncode)
    mock = AsyncMock(return_value=proc)
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector():
    return CrashLoopDetector(
        bot_id="test-bot",
        service_name="test-bot.service",
        max_consecutive_failures=5,
        window_seconds=120,
    )


@pytest.fixture
def detector_with_bus():
    bus = NexusBus(redis_url="redis://localhost:6379/0")
    bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    detector = CrashLoopDetector(
        bot_id="test-bot",
        service_name="test-bot.service",
        max_consecutive_failures=5,
        window_seconds=120,
        nexus_bus=bus,
    )
    yield detector, bus
    # cleanup marker if exists
    marker = Path("/tmp/test-bot-crash-loop-marker")
    if marker.exists():
        marker.unlink()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCrashLoopDetector:
    """Tests for CrashLoopDetector."""

    async def test_healthy_when_below_threshold(self, detector) -> None:
        """Should return HEALTHY when restart count is below threshold."""
        mock = _make_subprocess_mock(stdout=b"NRestarts=2\n")
        with patch("asyncio.create_subprocess_exec", mock):
            status = await detector.check_and_remediate()
        assert status == CrashLoopStatus.HEALTHY

    async def test_detects_at_threshold(self, detector) -> None:
        """Should detect crash loop when restart count reaches threshold."""
        mock_show = _make_subprocess_mock(stdout=b"NRestarts=5\n")
        mock_mask = _make_subprocess_mock(stdout=b"", returncode=0)

        call_count = [0]
        async def side_effect(*args, **kwargs):
            call_count[0] += 1
            if "show" in args:
                return _FakeProcess(stdout=b"NRestarts=5\n")
            return _FakeProcess(stdout=b"")

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            status = await detector.check_and_remediate()
        assert status == CrashLoopStatus.CRASH_LOOP_DETECTED

    async def test_masks_service(self, detector) -> None:
        """Should mask the service when crash loop is detected."""
        async def side_effect(*args, **kwargs):
            if "show" in args:
                return _FakeProcess(stdout=b"NRestarts=5\n")
            if "mask" in args:
                return _FakeProcess(stdout=b"")
            return _FakeProcess(stdout=b"")

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            await detector.check_and_remediate()

        # Marker should exist
        assert detector._marker_exists()

    async def test_writes_marker(self, detector) -> None:
        """Should write a marker file when crash loop is detected."""
        async def side_effect(*args, **kwargs):
            if "show" in args:
                return _FakeProcess(stdout=b"NRestarts=5\n")
            return _FakeProcess(stdout=b"")

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            await detector.check_and_remediate()

        assert detector._marker_exists()
        content = detector._marker_path.read_text()
        assert "bot_id=test-bot" in content
        assert "service=test-bot.service" in content

        # Cleanup
        detector._clear_marker()

    async def test_marker_cleared(self, detector) -> None:
        """_clear_marker should remove the marker file."""
        detector._write_marker()
        assert detector._marker_exists()
        detector._clear_marker()
        assert not detector._marker_exists()

    async def test_service_name_validation_rejects_injection(self) -> None:
        """Invalid service names should be rejected (shell injection prevention)."""
        detector = CrashLoopDetector(
            bot_id="test-bot",
            service_name="test; rm -rf /",
            max_consecutive_failures=5,
        )

        # Should return CHECK_FAILED because _get_systemd_restart_count raises ValueError
        status = await detector.check_and_remediate()
        assert status == CrashLoopStatus.CHECK_FAILED

    async def test_parses_systemctl_output(self, detector) -> None:
        """Should correctly parse NRestarts from systemctl show output."""
        mock = _make_subprocess_mock(stdout=b"NRestarts=7\n")
        with patch("asyncio.create_subprocess_exec", mock):
            count = await detector.get_restart_count()
        assert count == 7

    async def test_check_failed_on_error(self, detector) -> None:
        """Should return CHECK_FAILED when systemctl command fails."""
        async def side_effect(*args, **kwargs):
            raise FileNotFoundError("systemctl not found")

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            status = await detector.check_and_remediate()
        assert status == CrashLoopStatus.CHECK_FAILED

    async def test_can_stop_5_restart_cycle(self, detector) -> None:
        """After detection and masking, marker should prevent re-detection (SERVICE_MASKED)."""
        async def side_effect(*args, **kwargs):
            if "show" in args:
                return _FakeProcess(stdout=b"NRestarts=5\n")
            return _FakeProcess(stdout=b"")

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            # First check: detects crash loop
            status1 = await detector.check_and_remediate()
            assert status1 == CrashLoopStatus.CRASH_LOOP_DETECTED

            # Second check: marker exists, should return SERVICE_MASKED
            status2 = await detector.check_and_remediate()
            assert status2 == CrashLoopStatus.SERVICE_MASKED

        # Cleanup
        detector._clear_marker()

    async def test_publishes_alert_and_task(self, detector_with_bus) -> None:
        """Should publish health.alert and task.new events on crash loop detection."""
        detector, bus = detector_with_bus

        received_events: list = []

        async def handler(event):
            received_events.append(event)

        await bus.subscribe(EventType.HEALTH_ALERT, handler)
        await bus.subscribe(EventType.TASK_NEW, handler)
        await bus.start_consumer("voss")

        async def side_effect(*args, **kwargs):
            if "show" in args:
                return _FakeProcess(stdout=b"NRestarts=5\n")
            return _FakeProcess(stdout=b"")

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            await detector.check_and_remediate()

        await asyncio.sleep(0.5)

        event_types = [e.event_type for e in received_events]
        assert EventType.HEALTH_ALERT in event_types
        assert EventType.TASK_NEW in event_types

        # Cleanup
        detector._clear_marker()
        await bus.stop_consumer()
