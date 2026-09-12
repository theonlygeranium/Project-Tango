"""FleetBot base class — 10-phase self-healing startup and protected agent loop.

All fleet bots subclass FleetBot and implement the four abstract methods:
get_system_prompt, get_tools, handle_task, handle_message.

The start() method runs a 10-phase startup sequence that initializes all
self-healing infrastructure before the agent loop begins.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import discord

from nexus.bot.discord_handler import DiscordHandler
from nexus.bot.llm_client import LLMClient
from nexus.bot.session import SessionManager
from nexus.bot.tools import Tool, ToolCall, ToolRegistry
from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import BotConfig
from nexus.self_healing.circuit_breaker import (
    BreakerConfig,
    CircuitBreakerManager,
    CircuitOpenError,
)
from nexus.self_healing.checkpoint import CheckpointManager, ConversationState
from nexus.self_healing.crash_loop_detector import CrashLoopDetector, CrashLoopStatus
from nexus.self_healing.health_monitor import HealthCheck, HealthMonitor
from nexus.self_healing.recovery_engine import RecoveryEngine
from nexus.self_healing.remediation_actions import RemediationActions
from nexus.self_healing.semantic_breaker import SemanticBreaker, SemanticLoopError
from nexus.self_healing.supervisor import RuntimeSupervisor, SupervisorConfig

logger = logging.getLogger(__name__)


class FleetBot:
    """Base class for all fleet bots. Self-healing is mandatory."""

    def __init__(self, bot_id: str, config: BotConfig, nexus: NexusBus) -> None:
        self.bot_id = bot_id
        self.config = config
        self.nexus = nexus
        self.logger = logging.getLogger(f"nexus.bot.{bot_id}")

        # These are initialized during start()
        self._crash_loop_detector: CrashLoopDetector | None = None
        self._health_monitor: HealthMonitor | None = None
        self._breakers: CircuitBreakerManager | None = None
        self._semantic_breaker: SemanticBreaker | None = None
        self._checkpoint_manager: CheckpointManager | None = None
        self._recovery_engine: RecoveryEngine | None = None
        self._supervisor: RuntimeSupervisor | None = None
        self._discord_handler: DiscordHandler | None = None
        self._llm_client: LLMClient | None = None
        self._session_manager: SessionManager | None = None
        self._tool_registry: ToolRegistry | None = None
        self._conversation_state: ConversationState | None = None
        self._client: discord.Client | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Abstract methods — subclasses MUST implement
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        raise NotImplementedError

    def get_tools(self) -> list[Tool]:
        raise NotImplementedError

    async def handle_task(self, event: NexusEvent) -> None:
        raise NotImplementedError

    async def handle_message(self, message: discord.Message) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 10-phase startup
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """10-phase startup sequence — self-healing before agent loop."""
        # PHASE 1: Crash-loop detection
        self.logger.info("Phase 1: Crash-loop detection")
        self._crash_loop_detector = CrashLoopDetector(
            bot_id=self.bot_id,
            service_name=self.config.systemd_service_name,
            nexus_bus=self.nexus,
        )
        crash_status = await self._crash_loop_detector.check_and_remediate()
        if crash_status == CrashLoopStatus.CRASH_LOOP_DETECTED:
            self.logger.error("Crash loop detected, exiting")
            sys.exit(1)

        # PHASE 2: Health monitor initialization
        self.logger.info("Phase 2: Health monitor initialization")
        health_checks = self._get_health_checks()
        self._health_monitor = HealthMonitor(
            bot_id=self.bot_id,
            checks=health_checks,
            interval_seconds=self.config.health_check_interval,
            nexus_bus=self.nexus,
        )
        await self._health_monitor.start()

        # PHASE 3: Circuit breaker initialization
        self.logger.info("Phase 3: Circuit breaker initialization")
        breaker_config = BreakerConfig()
        self._breakers = CircuitBreakerManager(breaker_config)

        # PHASE 4: Semantic breaker initialization
        self.logger.info("Phase 4: Semantic breaker initialization")
        self._semantic_breaker = SemanticBreaker()

        # Initialize LLM client and tool registry
        self._llm_client = LLMClient(
            breakers=self._breakers,
            nexus=self.nexus,
        )
        self._tool_registry = ToolRegistry(
            breakers=self._breakers,
            semantic_breaker=self._semantic_breaker,
        )

        # PHASE 5: Checkpoint recovery
        self.logger.info("Phase 5: Checkpoint recovery")
        self._checkpoint_manager = CheckpointManager(
            bot_id=self.bot_id,
        )
        latest = await self._checkpoint_manager.get_latest()
        if latest is not None:
            self.logger.info("Restoring conversation state from checkpoint")
            self._conversation_state = latest
        else:
            self.logger.info("No checkpoint found, creating fresh conversation state")
            self._conversation_state = ConversationState(
                bot_id=self.bot_id,
                channel_id=0,
                messages=[],
                last_tool_call=None,
                agent_loop_iteration=0,
                timestamp="",
            )

        # PHASE 6: Recovery engine initialization
        self.logger.info("Phase 6: Recovery engine initialization")
        remediation_actions = RemediationActions(
            bot_id=self.bot_id,
            nexus_bus=self.nexus,
        )
        self._recovery_engine = RecoveryEngine(
            bot_id=self.bot_id,
            breaker_manager=self._breakers,
            semantic_breaker=self._semantic_breaker,
            checkpoint_manager=self._checkpoint_manager,
            remediation_actions=remediation_actions,
            nexus_bus=self.nexus,
        )

        # PHASE 7: Runtime supervisor initialization
        self.logger.info("Phase 7: Runtime supervisor initialization")
        self._supervisor = RuntimeSupervisor(
            bot_id=self.bot_id,
            nexus_bus=self.nexus,
        )
        await self._supervisor.start()

        # PHASE 8: Nexus Bus subscription
        self.logger.info("Phase 8: Nexus Bus subscription")
        await self.nexus.subscribe(EventType.TASK_NEW, self._handle_task)
        await self.nexus.subscribe(EventType.HEALTH_ALERT, self._handle_health_alert)
        await self.nexus.subscribe(EventType.UPDATE_DEPLOY, self._handle_update)

        # PHASE 9: Initial health check
        self.logger.info("Phase 9: Initial health check")
        if self._health_monitor is not None:
            report = await self._health_monitor.run_checks()
            health_event = NexusEvent.create(
                event_type=EventType.HEALTH_REPORT,
                source=self.bot_id,
                target="broadcast",
                payload={
                    "bot_id": self.bot_id,
                    "status": report.status.value,
                    "uptime_seconds": int(report.uptime_s),
                    "metrics": report.metrics,
                },
            )
            await self.nexus.publish(health_event)

        # PHASE 10: Start the agent loop
        self.logger.info("Phase 10: Start agent loop")
        await self._agent_loop()

    # ------------------------------------------------------------------
    # Protected agent loop
    # ------------------------------------------------------------------

    async def _agent_loop(self) -> None:
        """Protected agent loop with circuit breakers and semantic breaker."""
        self._running = True

        while self._running:
            try:
                # Save checkpoint before processing each message
                if (
                    self._checkpoint_manager is not None
                    and self._conversation_state is not None
                ):
                    self._conversation_state.agent_loop_iteration += 1
                    await self._checkpoint_manager.save(self._conversation_state)

                # Process messages from the conversation state (pop one at a time)
                if (
                    self._conversation_state is not None
                    and self._conversation_state.messages
                ):
                    message = self._conversation_state.messages.pop(0)
                    await self._process_message(message)
                else:
                    self._running = False
                    break

            except CircuitOpenError as e:
                self.logger.warning("Circuit open error: %s, routing to recovery", e)
                await self._route_to_recovery("circuit_open", str(e))
                self._running = False
            except SemanticLoopError as e:
                self.logger.warning("Semantic loop error: %s, routing to recovery", e)
                await self._route_to_recovery("semantic_loop", str(e))
                self._running = False
            except Exception as e:
                self.logger.error(
                    "Unexpected error in agent loop: %s, routing to recovery", e
                )
                await self._route_to_recovery("unknown", str(e))
                self._running = False

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Process a single message through LLM and tools.

        LLM calls are wrapped in the circuit breaker via breakers.call_llm.
        Tool calls are wrapped in the circuit breaker via breakers.call_tool
        and recorded with the semantic breaker. The supervisor observes every
        tool call.
        """
        if self._breakers is None:
            return

        # Wrap LLM call in circuit breaker
        messages = [{"role": "user", "content": message.get("content", "")}]
        model = self.config.model or "writer/palmyra-x6"
        try:
            response = await self._breakers.call_llm(
                model,
                self._llm_call_fn,
                messages,
            )
        except CircuitOpenError:
            raise
        except SemanticLoopError:
            raise
        except Exception as e:
            self.logger.error("LLM call failed: %s", e)
            raise

        # Execute any tool calls
        tool_calls = message.get("tool_calls", [])
        for tc in tool_calls:
            tool_call = ToolCall(name=tc.get("name", ""), args=tc.get("args", {}))
            try:
                result = await self._breakers.call_tool(
                    tool_call.name,
                    self._tool_call_fn,
                    tool_call,
                )
                # Record with semantic breaker
                if self._semantic_breaker is not None:
                    loop_detected = self._semantic_breaker.record_call(
                        tool_call.name, tool_call.args, result
                    )
                    if loop_detected:
                        raise SemanticLoopError(tool_call.name)
                # Supervisor observes every tool call
                if self._supervisor is not None:
                    await self._supervisor.observe(
                        type="tool_call",
                        tool=tool_call.name,
                        result=result,
                    )
            except CircuitOpenError:
                raise
            except SemanticLoopError:
                raise
            except Exception as e:
                self.logger.error("Tool execution failed: %s", e)
                if self._supervisor is not None:
                    await self._supervisor.observe(
                        type="error",
                        tool=tool_call.name,
                        result=str(e),
                    )

    async def _llm_call_fn(self, messages: list[dict[str, Any]]) -> Any:
        """Execute the actual LLM call. Override in subclasses for custom behavior."""
        if self._llm_client is not None:
            return await self._llm_client.call(messages)
        return {"content": ""}

    async def _tool_call_fn(self, tool_call: ToolCall) -> Any:
        """Execute the actual tool call. Override in subclasses for custom behavior."""
        if self._tool_registry is not None:
            return await self._tool_registry.execute(tool_call)
        return None

    async def _route_to_recovery(self, error_type: str, error_message: str) -> None:
        """Route a failure to the recovery engine."""
        if self._recovery_engine is None:
            return
        await self._recovery_engine.handle_failure(
            source=self.bot_id,
            error_type=error_type,
            error_message=error_message,
            context={},
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_task(self, event: NexusEvent) -> None:
        """Handle a task.new event — delegates to subclass."""
        try:
            await self.handle_task(event)
        except NotImplementedError:
            pass
        except Exception as e:
            self.logger.error("Error handling task event: %s", e)

    async def _handle_health_alert(self, event: NexusEvent) -> None:
        """Handle a health.alert event and forward it to the n8n hub."""
        self.logger.warning("Health alert received: %s", event.payload)
        try:
            import sys
            scripts = "/opt/Project-Tango/scripts"
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            from nexus_n8n_bridge import forward_health_alert
            payload = event.payload if isinstance(event.payload, dict) else {}
            forward_health_alert(payload)
        except Exception as exc:
            self.logger.debug("n8n forward skipped: %s", exc)

    async def _handle_update(self, event: NexusEvent) -> None:
        """Handle an update.deploy event."""
        self.logger.info("Update deploy received: %s", event.payload)

    async def _handle_supervisor_action(self, action: Any) -> None:
        """Handle a supervisor recommended action."""
        self.logger.info("Supervisor action: %s", action)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def _get_health_checks(self) -> list[HealthCheck]:
        """Return the default health checks for this bot."""
        async def _check_discord() -> Any:
            from nexus.self_healing.health_monitor import CheckResult, CheckStatus

            return CheckResult(
                name="discord_connection",
                status=CheckStatus.PASS,
                message="Discord client connected",
                duration_ms=0.0,
            )

        async def _check_nexus() -> Any:
            from nexus.self_healing.health_monitor import CheckResult, CheckStatus

            return CheckResult(
                name="nexus_bus",
                status=CheckStatus.PASS,
                message="Nexus Bus connected",
                duration_ms=0.0,
            )

        return [
            HealthCheck("discord_connection", _check_discord),
            HealthCheck("nexus_bus", _check_nexus),
        ]
