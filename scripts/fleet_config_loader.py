"""
Fleet Config Loader
===================
Loads shared Discord-bot fleet configuration from fleet-config.json at startup.

Path defaults to ``/opt/Project-Tango/config/fleet-config.json`` and can be
overridden with the ``FLEET_CONFIG_PATH`` environment variable.

All public helpers catch every exception and return empty/default structures so
bots never crash because of a missing, corrupt, or incomplete config file.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("fleet_config_loader")

DEFAULT_CONFIG_PATH = "/opt/Project-Tango/config/fleet-config.json"

# Fleet-level section keys returned by get_fleet_config()
_FLEET_SECTIONS = (
    "fleet_protocol",
    "conversation",
    "context_builder",
    "scheduler",
)

_config_cache: dict[str, Any] | None = None
_load_attempted: bool = False
_config_source: str = "defaults"


def _config_path() -> str:
    return os.environ.get("FLEET_CONFIG_PATH", DEFAULT_CONFIG_PATH)


def _load_config() -> dict[str, Any]:
    """Load and cache the fleet config. Never raises."""
    global _config_cache, _load_attempted, _config_source

    if _load_attempted:
        return _config_cache if _config_cache is not None else {}

    _load_attempted = True
    path = _config_path()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.warning(
                "fleet-config.json at %s is not a JSON object; using defaults",
                path,
            )
            _config_cache = {}
            _config_source = "defaults"
            logger.info("Using default config (fleet-config.json not found)")
            return {}
        _config_cache = data
        _config_source = path
        logger.info("Loaded fleet config from %s", path)
        return data
    except FileNotFoundError:
        logger.warning("fleet-config.json not found at %s; using defaults", path)
        _config_cache = {}
        _config_source = "defaults"
        logger.info("Using default config (fleet-config.json not found)")
        return {}
    except json.JSONDecodeError as exc:
        logger.warning(
            "Failed to parse fleet-config.json at %s: %s; using defaults",
            path,
            exc,
        )
        _config_cache = {}
        _config_source = "defaults"
        logger.info("Using default config (fleet-config.json not found)")
        return {}
    except Exception as exc:  # noqa: BLE001 — must never crash callers
        logger.warning(
            "Error loading fleet-config.json at %s: %s; using defaults",
            path,
            exc,
        )
        _config_cache = {}
        _config_source = "defaults"
        logger.info("Using default config (fleet-config.json not found)")
        return {}


def reload_config() -> dict[str, Any]:
    """Clear the cache and reload from disk. Useful for tests."""
    global _config_cache, _load_attempted, _config_source
    _config_cache = None
    _load_attempted = False
    _config_source = "defaults"
    return _load_config()


def get_config() -> dict[str, Any]:
    """Return the full fleet config dict, or ``{}`` on any error."""
    try:
        return _load_config()
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_config() failed: %s; returning {}", exc)
        return {}


def get_bot_config(bot_id: str) -> dict[str, Any]:
    """Return config for a specific bot (``bots.<bot_id>``), or ``{}`` on error."""
    try:
        cfg = get_config()
        bots = cfg.get("bots")
        if not isinstance(bots, dict):
            return {}
        bot_cfg = bots.get(bot_id)
        if not isinstance(bot_cfg, dict):
            return {}
        return bot_cfg
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "get_bot_config(%r) failed: %s; returning {}",
            bot_id,
            exc,
        )
        return {}


def get_fleet_config() -> dict[str, Any]:
    """
    Return fleet-level config sections.

    Keys: fleet_protocol, conversation, context_builder, scheduler.
    Missing sections become empty dicts. On any error, all sections are ``{}``.
    """
    defaults = {section: {} for section in _FLEET_SECTIONS}
    try:
        cfg = get_config()
        if not cfg:
            return defaults
        result = {}
        for section in _FLEET_SECTIONS:
            value = cfg.get(section, {})
            result[section] = value if isinstance(value, dict) else {}
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_fleet_config() failed: %s; returning defaults", exc)
        return defaults


def get_config_source() -> str:
    """Return the path used, or ``'defaults'`` if the file was not loaded."""
    try:
        get_config()
        return _config_source
    except Exception:  # noqa: BLE001
        return "defaults"
