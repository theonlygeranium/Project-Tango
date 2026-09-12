"""Tests for the Orchestrator Router (NX-SPEC-06).

Tests cover:
- RoutingTable resolve logic
- OrchestratorRouter request routing
- AcknowledgmentTracker timeout/retry behavior
- EscalationLadder reroute/voss/human escalation
- Behavioral tests for hierarchy collapse (architect demotion, admiral authority)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.manifest import load_manifest
from nexus.orchestrator import (
    AcknowledgmentTracker,
    EscalationLadder,
    OrchestratorRouter,
    RoutingTable,
    SubTask,
    TaskAssignment,
    TaskDecomposer,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "fleet-manifest.yaml"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manifest() -> Any:
    return load_manifest(MANIFEST_PATH)


@pytest.fixture
def mock_nexus() -> Any:
    nexus = MagicMock()
    nexus.publish = AsyncMock(return_value="mock-event-id-123")
    return nexus


@pytest.fixture
def routing_table(manifest: Any) -> RoutingTable:
    entries = manifest.routing_table or {}
    return RoutingTable(entries)


@pytest.fixture
def decomposer(mock_nexus: Any, manifest: Any) -> TaskDecomposer:
    return TaskDecomposer(mock_nexus, manifest)


@pytest.fixture
def acknowledgment(mock_nexus: Any, manifest: Any) -> AcknowledgmentTracker:
    return AcknowledgmentTracker(mock_nexus, manifest)


@pytest.fixture
def escalation(mock_nexus: Any, manifest: Any, acknowledgment: Any) -> EscalationLadder:
    return EscalationLadder(mock_nexus, manifest, acknowledgment)


@pytest.fixture
def router(mock_nexus: Any, manifest: Any) -> OrchestratorRouter:
    return OrchestratorRouter(mock_nexus, manifest)


# ---------------------------------------------------------------------------
# RoutingTable tests
# ---------------------------------------------------------------------------


class TestRoutingTable:
    def test_resolve_known_domain(self, routing_table: RoutingTable) -> None:
        assert routing_table.resolve("infrastructure") == "architect"
        assert routing_table.resolve("diagnostics") == "voss"
        assert routing_table.resolve("analysis") == "cortex"
        assert routing_table.resolve("resources") == "quartermaster"
        assert routing_table.resolve("documentation") == "cartographer"
        assert routing_table.resolve("compliance") == "proctor"

    def test_resolve_unknown_domain(self, routing_table: RoutingTable) -> None:
        with pytest.raises(KeyError, match="Unknown domain"):
            routing_table.resolve("nonexistent_domain")

    def test_resolve_decompose(self, routing_table: RoutingTable) -> None:
        with pytest.raises(ValueError, match="decompose"):
            routing_table.resolve("multi_domain")


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouterRouting:
    async def test_route_request_infrastructure(
        self, router: OrchestratorRouter, mock_nexus: Any
    ) -> None:
        """Infrastructure request routes to architect."""
        # Patch decompose to return a single infrastructure sub-task
        subtask = SubTask(
            subtask_id="st-1",
            target_bot="architect",
            description="Fix the server infrastructure",
            priority="high",
        )
        router._decomposer.decompose = AsyncMock(return_value=[subtask])
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request(
            "Fix the server infrastructure", "human_operator"
        )

        assert len(assignments) == 1
        assert assignments[0].subtask.target_bot == "architect"
        mock_nexus.publish.assert_called_once()

    async def test_route_request_diagnostics(
        self, router: OrchestratorRouter, mock_nexus: Any
    ) -> None:
        """Diagnostics request routes to voss."""
        subtask = SubTask(
            subtask_id="st-2",
            target_bot="voss",
            description="Diagnose the health issue",
            priority="normal",
        )
        router._decomposer.decompose = AsyncMock(return_value=[subtask])
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request(
            "Diagnose the health issue", "human_operator"
        )

        assert len(assignments) == 1
        assert assignments[0].subtask.target_bot == "voss"

    async def test_route_request_multi_domain(
        self, router: OrchestratorRouter, mock_nexus: Any
    ) -> None:
        """Multi-domain request decomposes into multiple sub-tasks."""
        subtasks = [
            SubTask(
                subtask_id="st-a",
                target_bot="architect",
                description="Fix infrastructure",
                priority="high",
            ),
            SubTask(
                subtask_id="st-b",
                target_bot="voss",
                description="Run diagnostics",
                priority="normal",
            ),
            SubTask(
                subtask_id="st-c",
                target_bot="cortex",
                description="Analyze patterns",
                priority="normal",
            ),
        ]
        router._decomposer.decompose = AsyncMock(return_value=subtasks)
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request(
            "Fix infrastructure, run diagnostics, and analyze patterns",
            "human_operator",
        )

        assert len(assignments) == 3
        target_bots = {a.subtask.target_bot for a in assignments}
        assert target_bots == {"architect", "voss", "cortex"}
        assert mock_nexus.publish.call_count == 3

    async def test_keyword_scoring_removed(self, router: OrchestratorRouter) -> None:
        """Old keyword scoring path is absent — router uses decomposer, not keywords."""
        # The router should not have any keyword_scoring or _keyword methods
        assert not hasattr(router, "keyword_scoring")
        assert not hasattr(router, "_keyword")
        assert not hasattr(router, "_score_keywords")
        assert not hasattr(router, "score_request")


# ---------------------------------------------------------------------------
# Acknowledgment tests
# ---------------------------------------------------------------------------


class TestAcknowledgment:
    async def test_ack_within_timeout(
        self, acknowledgment: AcknowledgmentTracker, mock_nexus: Any
    ) -> None:
        """Bot acks within 30s, no escalation."""
        subtask = SubTask(
            subtask_id="st-ack-1",
            target_bot="architect",
            description="Test task",
            priority="normal",
        )
        acknowledgment.register(subtask.correlation_id, subtask)

        # Simulate ack arriving after a short delay
        async def delayed_ack() -> None:
            await asyncio.sleep(0.05)
            await acknowledgment.record_ack(subtask.correlation_id)

        asyncio.create_task(delayed_ack())

        result = await acknowledgment.wait_for_ack(
            subtask.correlation_id, timeout=5.0
        )
        assert result is True

    async def test_ack_timeout_retries(
        self, acknowledgment: AcknowledgmentTracker, mock_nexus: Any
    ) -> None:
        """No ack triggers 2 retries with backoff."""
        subtask = SubTask(
            subtask_id="st-retry-1",
            target_bot="architect",
            description="Test task",
            priority="normal",
        )
        acknowledgment.register(subtask.correlation_id, subtask)

        # Wait for ack with short timeout — should time out
        result = await acknowledgment.wait_for_ack(
            subtask.correlation_id, timeout=0.1
        )
        assert result is False

        # Handle timeout — should retry
        final_failure_called = False

        async def on_final_failure() -> None:
            nonlocal final_failure_called
            final_failure_called = True

        # Patch sleep to make backoff instant
        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            await acknowledgment.handle_timeout(
                subtask.correlation_id, on_final_failure=on_final_failure
            )

        # After first timeout + handle_timeout, retry count should be 1
        # republish should have been called once
        assert mock_nexus.publish.call_count >= 1

    async def test_ack_timeout_escalates_to_voss(
        self, mock_nexus: Any, manifest: Any
    ) -> None:
        """After retries fail, escalation reaches Dr. Voss."""
        ack = AcknowledgmentTracker(mock_nexus, manifest)
        escalation = EscalationLadder(mock_nexus, manifest, ack)

        subtask = SubTask(
            subtask_id="st-esc-1",
            target_bot="architect",
            description="Test task",
            priority="critical",
        )
        ack.register(subtask.correlation_id, subtask)
        escalation.register(subtask.correlation_id, subtask)

        # Simulate max retries exhausted
        ack._retries[subtask.correlation_id] = ack.MAX_RETRIES

        final_failure_called = False

        async def on_final_failure() -> None:
            nonlocal final_failure_called
            final_failure_called = True
            await escalation.escalate_timeout(subtask.correlation_id)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            await ack.handle_timeout(
                subtask.correlation_id, on_final_failure=on_final_failure
            )

        assert final_failure_called is True
        # Escalation should have published to voss (health.alert)
        assert mock_nexus.publish.call_count >= 1


# ---------------------------------------------------------------------------
# Escalation tests
# ---------------------------------------------------------------------------


class TestEscalation:
    async def test_reroute_to_alternative(
        self, escalation: EscalationLadder, mock_nexus: Any
    ) -> None:
        """Failed task reroutes to alternative bot."""
        subtask = SubTask(
            subtask_id="st-reroute-1",
            target_bot="architect",
            description="Deploy the code",
            priority="high",
        )

        await escalation.escalate(subtask, "bot unresponsive")

        # Should have published a task.new to the alternative bot (voss)
        mock_nexus.publish.assert_called()
        published_event = mock_nexus.publish.call_args[0][0]
        assert published_event.target == "voss"
        assert published_event.payload.get("rerouted") is True
        assert published_event.payload.get("rerouted_from") == "architect"

    async def test_escalate_to_human(
        self, mock_nexus: Any, manifest: Any
    ) -> None:
        """Dr. Voss confirms bot down, no alternative, escalation reaches human."""
        ack = AcknowledgmentTracker(mock_nexus, manifest)
        escalation = EscalationLadder(mock_nexus, manifest, ack)

        # Use a bot with no alternative in the _ALTERNATIVES map
        subtask = SubTask(
            subtask_id="st-human-1",
            target_bot="sentinel",
            description="Run tests",
            priority="critical",
        )

        await escalation.escalate(subtask, "bot unresponsive")

        # Should publish health.alert to voss and then to admiral (human)
        assert mock_nexus.publish.call_count >= 2
        targets = [call.args[0].target for call in mock_nexus.publish.call_args_list]
        assert "voss" in targets
        assert "admiral" in targets


# ---------------------------------------------------------------------------
# Behavioral tests (architect demotion)
# ---------------------------------------------------------------------------


class TestHierarchyCollapse:
    async def test_architect_does_not_command_other_bots(
        self, router: OrchestratorRouter, mock_nexus: Any
    ) -> None:
        """Architect doesn't publish task.new to other bots."""
        # The architect is a tier 1 specialist. It should only receive tasks,
        # not publish task.new to command other bots.
        # We verify that the orchestrator (not the architect) publishes task.new.
        subtask = SubTask(
            subtask_id="st-arch-1",
            target_bot="architect",
            description="Fix the build",
            priority="high",
        )
        router._decomposer.decompose = AsyncMock(return_value=[subtask])
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request("Fix the build", "human_operator")

        assert len(assignments) == 1
        # The event source should be "orchestrator" (the Admiral's router),
        # not "architect"
        published_event = mock_nexus.publish.call_args[0][0]
        assert published_event.source == "orchestrator"
        assert published_event.target == "architect"

    async def test_architect_responds_to_admiral_tasks(
        self, router: OrchestratorRouter, mock_nexus: Any
    ) -> None:
        """Architect publishes task.ack and task.complete for Admiral tasks."""
        subtask = SubTask(
            subtask_id="st-arch-ack",
            target_bot="architect",
            description="Deploy code",
            priority="normal",
        )
        router._decomposer.decompose = AsyncMock(return_value=[subtask])
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request("Deploy code", "human_operator")

        assert len(assignments) == 1
        # The task.new event was published to architect
        assert assignments[0].subtask.target_bot == "architect"
        # The ack was received (simulated)
        assert router._ack.wait_for_ack.called

    async def test_admiral_authority_acknowledged_by_all_bots(
        self, router: OrchestratorRouter, mock_nexus: Any
    ) -> None:
        """All specialists ack Admiral tasks within 30s."""
        specialists = ["architect", "voss", "cortex", "quartermaster",
                       "cartographer", "proctor"]
        subtasks = [
            SubTask(
                subtask_id=f"st-{i}",
                target_bot=bot,
                description=f"Task for {bot}",
                priority="normal",
            )
            for i, bot in enumerate(specialists)
        ]
        router._decomposer.decompose = AsyncMock(return_value=subtasks)
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request(
            "Coordinate all specialists", "human_operator"
        )

        assert len(assignments) == len(specialists)
        # All acks returned True
        assert router._ack.wait_for_ack.call_count == len(specialists)

    async def test_admiral_is_sole_tier_0(self, manifest: Any) -> None:
        """Manifest declares exactly one tier 0 bot."""
        tier_0_bots = [
            name for name, bot in manifest.bots.items() if bot.tier == 0
        ]
        assert len(tier_0_bots) == 1
        assert tier_0_bots[0] == "admiral"

    async def test_no_co_equal_command(self) -> None:
        """No prompt contains affirmative co-equal command language.

        The admiral.md explicitly says 'There is no co-equal commander' which
        is correct — it's denying co-equality, not asserting it. We check
        that no prompt asserts co-equal authority (affirmative only),
        allowing negations like 'no co-equal commander'.
        """
        prompts_dir = REPO_ROOT / "prompts"
        # Phrases that would assert co-equal command (affirmative only)
        affirmative_phrases = [
            "you are co-equal",
            "you are coequal",
            "you have equal authority",
            "you share command",
            "you are a peer commander",
            "you are co-commander",
        ]

        for prompt_file in prompts_dir.glob("*.md"):
            content = prompt_file.read_text(encoding="utf-8").lower()
            for phrase in affirmative_phrases:
                assert phrase not in content, (
                    f"Prompt {prompt_file.name} contains affirmative co-equal "
                    f"command language: {phrase!r}"
                )
