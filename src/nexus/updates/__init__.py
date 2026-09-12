"""Update propagation and phased rollout.

Re-exports the public API for the updates package.
"""

from nexus.updates.canary import CanaryDeployer, CanaryResult
from nexus.updates.deployer import BotDeployResult, BotDeployer
from nexus.updates.models import (
    ChangeSeverity,
    DeployResult,
    ManifestChange,
)
from nexus.updates.pipeline import UpdatePipeline
from nexus.updates.rollback import RollbackManager, RollbackResult

__all__ = [
    "BotDeployResult",
    "BotDeployer",
    "CanaryDeployer",
    "CanaryResult",
    "ChangeSeverity",
    "DeployResult",
    "ManifestChange",
    "RollbackManager",
    "RollbackResult",
    "UpdatePipeline",
]
