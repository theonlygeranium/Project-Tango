"""Self-healing modules — circuit breakers, health monitors, recovery, supervisor.

Re-exports all public classes from the 9 self-healing foundation modules.
"""

from .circuit_breaker import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitOpenError,
)
from .checkpoint import (
    CheckpointManager,
    CheckpointStorage,
    ConversationState,
    RedisCheckpointStorage,
)
from .crash_loop_detector import CrashLoopDetector, CrashLoopStatus
from .health_monitor import (
    CheckResult,
    CheckStatus,
    HealthCheck,
    HealthMonitor,
    HealthReport,
    HealthStatus,
)
from .health_registry import BotHealthState, FleetHealthSummary, HealthRegistry
from .recovery_engine import (
    Failure,
    FailureType,
    RecoveryEngine,
    RecoveryOutcome,
    RecoveryResult,
)
from .remediation_actions import RemediationActions, RemediationResult
from .semantic_breaker import SemanticBreaker, SemanticLoopError
from .supervisor import (
    AgentEvent,
    BehaviorReport,
    RuntimeSupervisor,
    SupervisorAction,
    SupervisorConfig,
)

__all__ = [
    # Crash loop detector
    "CrashLoopDetector",
    "CrashLoopStatus",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitBreakerManager",
    "BreakerState",
    "CircuitOpenError",
    "BreakerConfig",
    # Health monitor
    "HealthMonitor",
    "HealthCheck",
    "CheckResult",
    "CheckStatus",
    "HealthReport",
    "HealthStatus",
    # Recovery engine
    "RecoveryEngine",
    "Failure",
    "FailureType",
    "RecoveryResult",
    "RecoveryOutcome",
    # Checkpoint
    "CheckpointManager",
    "CheckpointStorage",
    "ConversationState",
    "RedisCheckpointStorage",
    # Semantic breaker
    "SemanticBreaker",
    "SemanticLoopError",
    # Health registry
    "HealthRegistry",
    "BotHealthState",
    "FleetHealthSummary",
    # Remediation actions
    "RemediationActions",
    "RemediationResult",
    # Supervisor
    "RuntimeSupervisor",
    "SupervisorConfig",
    "SupervisorAction",
    "AgentEvent",
    "BehaviorReport",
]
