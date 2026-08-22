from __future__ import annotations

import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(
    os.environ.get(
        "FLEET_CONFIG_PATH",
        str(Path(__file__).resolve().parent.parent / "config" / "fleet-config.json"),
    )
)

REQUIRED_BOTS = {
    "admiral",
    "architect",
    "quartermaster",
    "cartographer",
    "dr_voss",
    "proctor",
    "cortex",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_PATH

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"Config not found: {self.path}")
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, config: dict[str, Any], modified_by: str = "operator") -> dict[str, Any]:
        self.validate(config)
        config = deepcopy(config)
        config["last_modified"] = _utcnow()
        config["modified_by"] = modified_by

        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup = self.path.with_suffix(".json.bak")
        if self.path.exists():
            shutil.copy2(self.path, backup)

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            delete=False,
        ) as tmp:
            json.dump(config, tmp, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)
        return config

    def update(self, patch: dict[str, Any], modified_by: str = "operator") -> dict[str, Any]:
        current = self.load()
        merged = deep_merge(current, patch)
        return self.save(merged, modified_by=modified_by)

    def update_bot(
        self, bot_id: str, bot_config: dict[str, Any], modified_by: str = "operator"
    ) -> dict[str, Any]:
        current = self.load()
        if bot_id not in current.get("bots", {}):
            raise KeyError(f"Unknown bot: {bot_id}")
        current["bots"][bot_id] = deep_merge(current["bots"][bot_id], bot_config)
        return self.save(current, modified_by=modified_by)

    def validate(self, config: dict[str, Any]) -> None:
        if "bots" not in config or not isinstance(config["bots"], dict):
            raise ValueError("fleet config must include bots object")
        if "version" not in config:
            raise ValueError("fleet config must include version")
        missing = REQUIRED_BOTS - set(config["bots"].keys())
        if missing:
            raise ValueError(f"missing bots: {sorted(missing)}")


def services_requiring_restart(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    restarts: set[str] = set()
    if before.get("fleet_protocol") != after.get("fleet_protocol"):
        for bot in after.get("bots", {}).values():
            restarts.add(bot.get("identity", {}).get("service", ""))
    if before.get("scheduler") != after.get("scheduler"):
        for bot_id in ("admiral", "cortex"):
            svc = after.get("bots", {}).get(bot_id, {}).get("identity", {}).get("service")
            if svc:
                restarts.add(svc)
    for bot_id, bot in after.get("bots", {}).items():
        prev = before.get("bots", {}).get(bot_id, {})
        if prev.get("memory") != bot.get("memory"):
            for b in after.get("bots", {}).values():
                restarts.add(b.get("identity", {}).get("service", ""))
            break
        if prev.get("llm") != bot.get("llm") or prev.get("guardrails") != bot.get("guardrails"):
            restarts.add(bot.get("identity", {}).get("service", ""))
    return sorted(s for s in restarts if s)
