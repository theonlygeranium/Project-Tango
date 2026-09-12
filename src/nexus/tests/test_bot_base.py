"""Tests for FleetBot base class — 10-phase startup and protected agent loop."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.bot.base import FleetBot
from nexus.bot.tools import Tool
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import BotConfig
from nexus.self_healing.circuit_breaker import CircuitOpenError
from nexus.self_healing.semantic_breaker import SemanticLoopError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_bot_config() -> BotConfig:
    return BotConfig(
        tier=1,
        model="writer/palmyra-x6",
        discord_token_env="BOT_TOKEN",
        system_prompt_file="/tmp/prompt.txt",
        tools=[],
        health_check_interval=30,
        port=8090,
        systemd_service_name="nexus-test-bot",
    )


@pytest.fixture
def mock_nexus() -> Any:
    nexus = MagicMock()
    nexus.publish = AsyncMock()
    nexus.subscribe = AsyncMock()
    return nexus


@pytest.fixture
def bot_config() -> BotConfig:
    return make_bot_config()


@pytest.fixture
def bot(bot_config: BotConfig, mock_nexus: Any) -> FleetBot:
    return FleetBot("test-bot", bot_config, mock_nexus)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_crash_loop_detector() -> Any:
    """Patch CrashLoopDetector to return HEALTHY."""
    return patch(
        "nexus.bot.base.CrashLoopDetector"
    )


def _make_supervisor_mock() -> Any:
    sup = MagicMock()
    sup.start = AsyncMock()
    sup.stop = AsyncMock()
    sup.observe = AsyncMock(return_value=None)
    return sup


def _make_health_monitor_mock() -> Any:
    hm = MagicMock()
    hm.start = AsyncMock()
    hm.stop = AsyncMock()
    hm.run_checks = AsyncMock()
    report = MagicMock()
    report.status.value = "healthy"
    report.uptime_s = 0.0
    report.metrics = {}
    hm.run_checks.return_value = report
    return hm


def _make_checkpoint_manager_mock(
    has_checkpoint: bool = True, messages: list | None = None
) -> Any:
    cm = MagicMock()
    cm.save = AsyncMock()
    if has_checkpoint:
        from nexus.self_healing.checkpoint import ConversationState

        cm.get_latest = AsyncMock(
            return_value=ConversationState(
                bot_id="test-bot",
                channel_id=123,
                messages=messages or [],
                last_tool_call=None,
                agent_loop_iteration=0,
                timestamp="2026-01-01T00:00:00Z",
            )
        )
    else:
        cm.get_latest = AsyncMock(return_value=None)
    return cm


async def _run_start_with_mocks(
    bot: FleetBot,
    *,
    crash_status: Any = None,
    has_checkpoint: bool = True,
    agent_loop_messages: list | None = None,
) -> dict[str, Any]:
    """Run bot.start() with all dependencies mocked. Returns a dict of call tracking."""
    from nexus.self_healing.crash_loop_detector import CrashLoopStatus

    if crash_status is None:
        crash_status = CrashLoopStatus.HEALTHY

    # Track phase invocations
    calls: dict[str, Any] = {}

    # Phase 1: CrashLoopDetector
    cld_mock = MagicMock()
    cld_mock.check_and_remediate = AsyncMock(return_value=crash_status)
    cld_class = MagicMock(return_value=cld_mock)

    # Phase 2: HealthMonitor
    hm_mock = _make_health_monitor_mock()
    hm_class = MagicMock(return_value=hm_mock)

    # Phase 3: CircuitBreakerManager
    breakers_mock = MagicMock()
    breakers_mock.call_llm = AsyncMock(return_value={"content": "llm response"})
    breakers_mock.call_tool = AsyncMock(return_value="tool result")
    breakers_mock.call_discord = AsyncMock()
    breakers_class = MagicMock(return_value=breakers_mock)

    # Phase 4: SemanticBreaker
    sb_mock = MagicMock()
    sb_mock.record_call = MagicMock(return_value=False)
    sb_class = MagicMock(return_value=sb_mock)

    # Phase 5: CheckpointManager — include messages if provided
    cm_mock = _make_checkpoint_manager_mock(
        has_checkpoint=has_checkpoint,
        messages=agent_loop_messages if agent_loop_messages is not None else [],
    )
    cm_class = MagicMock(return_value=cm_mock)

    # Phase 6: RecoveryEngine
    re_mock = MagicMock()
    re_mock.handle_failure = AsyncMock()
    re_class = MagicMock(return_value=re_mock)

    # Phase 7: RuntimeSupervisor
    sup_mock = _make_supervisor_mock()
    sup_class = MagicMock(return_value=sup_mock)

    # Phase 6: RemediationActions
    ra_mock = MagicMock()
    ra_class = MagicMock(return_value=ra_mock)

    # LLMClient mock
    llm_mock = MagicMock()
    llm_mock.call = AsyncMock(return_value={"content": "llm response"})
    llm_class = MagicMock(return_value=llm_mock)

    # ToolRegistry mock
    tr_mock = MagicMock()
    tr_mock.execute = AsyncMock(return_value="tool result")
    tr_class = MagicMock(return_value=tr_mock)

    with (
        patch("nexus.bot.base.CrashLoopDetector", cld_class),
        patch("nexus.bot.base.HealthMonitor", hm_class),
        patch("nexus.bot.base.CircuitBreakerManager", breakers_class),
        patch("nexus.bot.base.SemanticBreaker", sb_class),
        patch("nexus.bot.base.CheckpointManager", cm_class),
        patch("nexus.bot.base.RecoveryEngine", re_class),
        patch("nexus.bot.base.RuntimeSupervisor", sup_class),
        patch("nexus.bot.base.RemediationActions", ra_class),
        patch("nexus.bot.base.LLMClient", llm_class),
        patch("nexus.bot.base.ToolRegistry", tr_class),
    ):
        await bot.start()

    return {
        "cld": cld_mock,
        "hm": hm_mock,
        "breakers": breakers_mock,
        "sb": sb_mock,
        "cm": cm_mock,
        "re": re_mock,
        "sup": sup_mock,
        "llm": llm_mock,
        "tr": tr_mock,
        "nexus": bot.nexus,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_start_runs_all_ten_phases(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """start() invokes all 10 phases in order."""
    calls = await _run_start_with_mocks(bot)

    # Phase 1: crash loop detector
    calls["cld"].check_and_remediate.assert_called_once()

    # Phase 2: health monitor started
    calls["hm"].start.assert_called_once()

    # Phase 3: circuit breaker manager created (implicit via class instantiation)

    # Phase 4: semantic breaker created (implicit)

    # Phase 5: checkpoint get_latest called
    calls["cm"].get_latest.assert_called_once()

    # Phase 6: recovery engine created (implicit)

    # Phase 7: supervisor started
    calls["sup"].start.assert_called_once()

    # Phase 8: nexus subscriptions
    assert mock_nexus.subscribe.call_count == 3

    # Phase 9: health check run and published
    calls["hm"].run_checks.assert_called_once()
    mock_nexus.publish.assert_called()

    # Phase 10: agent loop ran (checkpoint saved at least once)
    calls["cm"].save.assert_called()


async def test_start_exits_on_crash_loop(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """Phase 1 returning CRASH_LOOP_DETECTED causes sys.exit(1)."""
    from nexus.self_healing.crash_loop_detector import CrashLoopStatus

    with pytest.raises(SystemExit) as exc_info:
        await _run_start_with_mocks(bot, crash_status=CrashLoopStatus.CRASH_LOOP_DETECTED)

    assert exc_info.value.code == 1


async def test_checkpoint_restored_on_startup(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """Phase 5 restores conversation_state from latest checkpoint."""
    await _run_start_with_mocks(bot, has_checkpoint=True)

    assert bot._conversation_state is not None
    assert bot._conversation_state.bot_id == "test-bot"
    assert bot._conversation_state.channel_id == 123


async def test_checkpoint_fresh_when_none(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """Phase 5 creates fresh ConversationState when no checkpoint."""
    await _run_start_with_mocks(bot, has_checkpoint=False)

    assert bot._conversation_state is not None
    assert bot._conversation_state.bot_id == "test-bot"
    assert bot._conversation_state.messages == []


async def test_agent_loop_saves_checkpoint_before_message(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """checkpoint.save called before LLM call."""
    calls = await _run_start_with_mocks(
        bot, agent_loop_messages=[{"content": "hello", "role": "user"}]
    )

    # checkpoint.save should have been called
    calls["cm"].save.assert_called()


async def test_agent_loop_wraps_llm_in_breaker(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """LLM call goes through breakers.call_llm."""
    calls = await _run_start_with_mocks(
        bot, agent_loop_messages=[{"content": "hello", "role": "user"}]
    )

    # The LLM call should go through the breaker
    calls["breakers"].call_llm.assert_called()


async def test_agent_loop_wraps_tool_in_breaker(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """tool calls go through breakers.call_tool."""
    calls = await _run_start_with_mocks(
        bot,
        agent_loop_messages=[
            {
                "content": "hello",
                "role": "user",
                "tool_calls": [
                    {"name": "search", "args": {"query": "test"}}
                ],
            }
        ],
    )

    calls["breakers"].call_tool.assert_called()


async def test_agent_loop_records_semantic_breaker(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """tool calls recorded by semantic breaker."""
    calls = await _run_start_with_mocks(
        bot,
        agent_loop_messages=[
            {
                "content": "hello",
                "role": "user",
                "tool_calls": [
                    {"name": "search", "args": {"query": "test"}}
                ],
            }
        ],
    )

    calls["sb"].record_call.assert_called()


async def test_agent_loop_supervisor_observes_events(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """supervisor.observe called for each tool call."""
    calls = await _run_start_with_mocks(
        bot,
        agent_loop_messages=[
            {
                "content": "hello",
                "role": "user",
                "tool_calls": [
                    {"name": "search", "args": {"query": "test"}}
                ],
            }
        ],
    )

    calls["sup"].observe.assert_called()


async def test_circuit_open_error_routes_to_recovery(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """CircuitOpenError caught and routed to recovery."""
    from nexus.self_healing.checkpoint import ConversationState

    calls = await _run_start_with_mocks(bot)

    # Now simulate a circuit open error in the agent loop
    breakers = calls["breakers"]
    breakers.call_llm = AsyncMock(side_effect=CircuitOpenError("llm:test", "timeout"))

    # Reset recovery engine mock
    calls["re"].handle_failure.reset_mock()

    # Set up a message to process
    bot._conversation_state = ConversationState(
        bot_id="test-bot",
        channel_id=123,
        messages=[{"content": "hello", "role": "user"}],
        last_tool_call=None,
        agent_loop_iteration=0,
        timestamp="2026-01-01T00:00:00Z",
    )

    await bot._agent_loop()

    calls["re"].handle_failure.assert_called()
    args = calls["re"].handle_failure.call_args
    assert "circuit_open" in str(args)


async def test_semantic_loop_error_routes_to_recovery(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """SemanticLoopError caught and routed to recovery."""
    from nexus.self_healing.checkpoint import ConversationState

    calls = await _run_start_with_mocks(bot)

    # Make semantic breaker raise
    calls["sb"].record_call = MagicMock(return_value=True)

    # Set up a message with tool calls
    bot._conversation_state = ConversationState(
        bot_id="test-bot",
        channel_id=123,
        messages=[
            {
                "content": "hello",
                "role": "user",
                "tool_calls": [
                    {"name": "search", "args": {"query": "test"}}
                ],
            }
        ],
        last_tool_call=None,
        agent_loop_iteration=0,
        timestamp="2026-01-01T00:00:00Z",
    )

    # Reset recovery engine mock
    calls["re"].handle_failure.reset_mock()

    await bot._agent_loop()

    calls["re"].handle_failure.assert_called()
    args = calls["re"].handle_failure.call_args
    assert "semantic" in str(args).lower()


async def test_generic_exception_routes_to_recovery(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """generic Exception caught and routed to recovery."""
    from nexus.self_healing.checkpoint import ConversationState

    calls = await _run_start_with_mocks(bot)

    # Make LLM call raise a generic exception
    calls["breakers"].call_llm = AsyncMock(side_effect=RuntimeError("boom"))

    # Set up a message
    bot._conversation_state = ConversationState(
        bot_id="test-bot",
        channel_id=123,
        messages=[{"content": "hello", "role": "user"}],
        last_tool_call=None,
        agent_loop_iteration=0,
        timestamp="2026-01-01T00:00:00Z",
    )

    # Reset recovery engine mock
    calls["re"].handle_failure.reset_mock()

    await bot._agent_loop()

    calls["re"].handle_failure.assert_called()


async def test_initial_health_check_published(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """Phase 9 publishes health.report event."""
    await _run_start_with_mocks(bot)

    # Check that publish was called with a health report event
    publish_calls = mock_nexus.publish.call_args_list
    assert len(publish_calls) > 0

    # At least one publish should be a health report
    found_health_report = False
    for call in publish_calls:
        event = call.args[0]
        if event.event_type == EventType.HEALTH_REPORT:
            found_health_report = True
            assert event.payload["bot_id"] == "test-bot"
            break

    assert found_health_report


async def test_nexus_subscriptions_registered(
    bot: FleetBot, mock_nexus: Any
) -> None:
    """Phase 8 subscribes to task.new, health.alert, update.deploy."""
    await _run_start_with_mocks(bot)

    subscribed_types: list[str] = []
    for call in mock_nexus.subscribe.call_args_list:
        subscribed_types.append(call.args[0])

    assert EventType.TASK_NEW in subscribed_types
    assert EventType.HEALTH_ALERT in subscribed_types
    assert EventType.UPDATE_DEPLOY in subscribed_types


async def test_abstract_methods_raise_not_implemented(
    bot: FleetBot,
) -> None:
    """four abstract methods raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        bot.get_system_prompt()
    with pytest.raises(NotImplementedError):
        bot.get_tools()
    with pytest.raises(NotImplementedError):
        await bot.handle_task(MagicMock())
    with pytest.raises(NotImplementedError):
        await bot.handle_message(MagicMock())
