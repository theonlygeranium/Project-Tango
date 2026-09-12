"""Sentinel testing framework — autonomous testing and validation agent.

Public API re-exports for all testing modules.
"""

from __future__ import annotations

from nexus.testing.conversation import (
    ConversationRunner,
    ConversationTrajectory,
    ConversationTurn,
)
from nexus.testing.enforcement import (
    EnforcementResult,
    TestEnforcer,
    enforcer,
)
from nexus.testing.generator import (
    CodeChange,
    RecipeGenerator,
)
from nexus.testing.judge import (
    AgentJudge,
    CriterionScore,
    JudgeResult,
)
from nexus.testing.posterior import (
    BotPosterior,
    CapabilityScore,
    PosteriorStore,
)
from nexus.testing.recipe import (
    RecipeRegistry,
    TestCase,
    TestRecipe,
)
from nexus.testing.repair import (
    FailureReport,
    RepairAttempt,
    RepairEngine,
)
from nexus.testing.rubrics import (
    DELEGATION_RUBRIC,
    DOMAIN_KNOWLEDGE_RUBRIC,
    NEW_FEATURE_RUBRIC,
    ROUTING_RUBRIC,
    RUBRICS,
    Rubric,
    RubricCriterion,
    SAFETY_RUBRIC,
    TOOL_USE_RUBRIC,
)
from nexus.testing.sentinel import (
    Sentinel,
    TestCycleResult,
)

__all__ = [
    # Recipe
    "TestCase",
    "TestRecipe",
    "RecipeRegistry",
    # Rubrics
    "RubricCriterion",
    "Rubric",
    "RUBRICS",
    "DOMAIN_KNOWLEDGE_RUBRIC",
    "TOOL_USE_RUBRIC",
    "ROUTING_RUBRIC",
    "DELEGATION_RUBRIC",
    "SAFETY_RUBRIC",
    "NEW_FEATURE_RUBRIC",
    # Conversation
    "ConversationTurn",
    "ConversationTrajectory",
    "ConversationRunner",
    # Judge
    "CriterionScore",
    "JudgeResult",
    "AgentJudge",
    # Generator
    "CodeChange",
    "RecipeGenerator",
    # Repair
    "FailureReport",
    "RepairAttempt",
    "RepairEngine",
    # Posterior
    "CapabilityScore",
    "BotPosterior",
    "PosteriorStore",
    # Sentinel
    "Sentinel",
    "TestCycleResult",
    # Enforcement
    "EnforcementResult",
    "TestEnforcer",
    "enforcer",
]
