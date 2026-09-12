"""Data flywheel — continuous improvement loop.

Re-exports the public API for the flywheel subsystem:
- FailureEventCollector and event dataclasses
- WeeklyAnalysisEngine and AnalysisReport
- LearningLoop and LearningInsight
"""

from nexus.flywheel.collector import (
    FailureEvent,
    FailureEventCollector,
    LLMCallEvent,
    RecoveryEvent,
)
from nexus.flywheel.analyzer import (
    AnalysisReport,
    WeeklyAnalysisEngine,
)
from nexus.flywheel.learning import (
    LearningInsight,
    LearningLoop,
)

__all__ = [
    "FailureEventCollector",
    "FailureEvent",
    "RecoveryEvent",
    "LLMCallEvent",
    "WeeklyAnalysisEngine",
    "AnalysisReport",
    "LearningLoop",
    "LearningInsight",
]
