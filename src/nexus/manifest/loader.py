"""Typed manifest loader for the Nexus Fleet Manifest."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)


def load_manifest(path: Path | str = "fleet-manifest.yaml") -> FleetManifest:
    """Load and validate a fleet manifest from a YAML file.

    Args:
        path: Path to the YAML manifest file.

    Returns:
        A validated FleetManifest instance.

    Raises:
        FileNotFoundError: If the manifest file does not exist.
        ValueError: If the YAML is malformed or fails pydantic validation.
    """
    manifest_path = Path(path)
    logger.info("Loading fleet manifest from %s", manifest_path)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read manifest file {manifest_path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in manifest {manifest_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Manifest must be a YAML mapping at top level, got {type(data).__name__}"
        )

    try:
        manifest = FleetManifest.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Manifest validation failed for {manifest_path}:\n{exc}") from exc

    logger.info(
        "Loaded fleet manifest v%s with %d bots", manifest.version, len(manifest.bots)
    )
    return manifest
