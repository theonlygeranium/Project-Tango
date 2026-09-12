"""Shared data models for the update propagation pipeline.

Extracted to avoid circular imports between pipeline.py and canary.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)


class ChangeSeverity:
    """Constants for classifying the severity of a manifest change."""

    CONFIG_TWEAK = "config_tweak"
    SYSTEM_PROMPT = "system_prompt"
    TOOL_CHANGE = "tool_change"
    MODEL_CHANGE = "model_change"
    MAJOR = "major"


# Ordered severity ranks for comparison (lower = less severe)
SEVERITY_RANK: dict[str, int] = {
    ChangeSeverity.CONFIG_TWEAK: 0,
    ChangeSeverity.SYSTEM_PROMPT: 1,
    ChangeSeverity.TOOL_CHANGE: 2,
    ChangeSeverity.MODEL_CHANGE: 3,
    ChangeSeverity.MAJOR: 4,
}


@dataclass
class ManifestChange:
    """Represents a change between two manifest versions."""

    change_id: str
    old_manifest: FleetManifest
    new_manifest: FleetManifest
    old_commit: str
    new_commit: str
    affected_bots: list[str]
    severity: str
    summary: str
    timestamp: str


@dataclass
class DeployResult:
    """Result of a full pipeline deployment."""

    change_id: str
    success: bool
    deployed_bots: list[str]
    failed_bots: list[str]
    canary_passed: bool
    rollback_count: int
    duration_seconds: float
    error: str | None = None
