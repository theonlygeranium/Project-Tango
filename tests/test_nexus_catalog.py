"""Fleet Command Nexus catalog merge — keeps command.schubert.life connected."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLEET_API = ROOT / "fleet-api"
if str(FLEET_API) not in sys.path:
    sys.path.insert(0, str(FLEET_API))

from nexus_catalog import (  # noqa: E402
    canonicalize_bot_id,
    enrich_config,
    merge_tools,
    nexus_status,
    resolve_bot_id,
)


MINIMAL_BOTS = {
    "admiral",
    "architect",
    "quartermaster",
    "cartographer",
    "dr_voss",
    "proctor",
    "cortex",
}


def _bot(bot_id: str, tools: list[dict] | None = None) -> dict:
    return {
        "identity": {"service": f"{bot_id}.service", "name": bot_id},
        "meta": {"id": bot_id, "featureTags": []},
        "llm": {"model": "writer/palmyra-x6"},
        "mcp": {"servers": []},
        "tools": tools or [],
    }


def _config() -> dict:
    return {
        "version": 1,
        "last_modified": "2026-08-20T00:00:00Z",
        "bots": {bot_id: _bot(bot_id) for bot_id in MINIMAL_BOTS},
    }


def test_voss_alias_maps_to_dr_voss() -> None:
    assert canonicalize_bot_id("voss") == "dr_voss"
    assert canonicalize_bot_id("dr_voss") == "dr_voss"
    config = _config()
    assert resolve_bot_id("voss", config) == "dr_voss"
    assert resolve_bot_id("dr_voss", config) == "dr_voss"
    assert resolve_bot_id("sentinel", config) is None


def test_merge_keeps_legacy_and_adds_nexus() -> None:
    existing = [
        {"id": "run_shell", "name": "run_shell", "source": "legacy", "enabled": True},
        {"id": "delegate_to_agent", "name": "delegate_to_agent", "source": "fleet", "enabled": True},
    ]
    merged = merge_tools(existing, "admiral")
    ids = [t["id"] for t in merged]
    assert ids[0] == "run_shell"
    assert "delegate_to_agent" in ids
    assert "fleet_delegate" in ids
    assert "health_check" in ids
    assert "restart_service" in ids
    assert merged[0]["source"] == "legacy"
    assert any(t["id"] == "fleet_delegate" and t["source"] == "nexus" for t in merged)


def test_enrich_config_does_not_mutate_and_tags_nexus() -> None:
    config = _config()
    config["bots"]["admiral"]["tools"] = [
        {"id": "run_shell", "name": "run_shell", "source": "legacy", "enabled": True}
    ]
    enriched = enrich_config(config)
    assert config["bots"]["admiral"]["tools"] == [
        {"id": "run_shell", "name": "run_shell", "source": "legacy", "enabled": True}
    ]
    adm = enriched["bots"]["admiral"]
    assert "nexus" in adm["meta"]["featureTags"]
    assert "health_check" in {t["id"] for t in adm["tools"]}
    assert "wiki_publish" in {t["id"] for t in enriched["bots"]["cartographer"]["tools"]}
    assert "scan_ai_trends" in {t["id"] for t in enriched["bots"]["cortex"]["tools"]}
    assert "view_logs" in {t["id"] for t in enriched["bots"]["dr_voss"]["tools"]}


def test_nexus_status_marks_sentinel_undeployed() -> None:
    payload = nexus_status(_config(), {bot: "online" for bot in MINIMAL_BOTS})
    assert payload["architecture"] == "nexus-v2"
    assert payload["ui_compatible"] is True
    by_nexus = {row["nexus_id"]: row for row in payload["roster"]}
    assert by_nexus["voss"]["config_id"] == "dr_voss"
    assert by_nexus["voss"]["deployed_in_config"] is True
    assert by_nexus["sentinel"]["deployed_in_config"] is False


def test_fleet_api_get_config_and_voss_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "fleet-config.json"
    cfg_path.write_text(json.dumps(_config()), encoding="utf-8")
    monkeypatch.setenv("FLEET_CONFIG_PATH", str(cfg_path))
    monkeypatch.delenv("FLEET_API_TOKEN", raising=False)
    monkeypatch.syspath_prepend(str(FLEET_API))

    from fastapi.testclient import TestClient

    import main as fleet_main

    fleet_main.app.state.config_manager.path = cfg_path
    fleet_main.app.state.service_manager.dry_run = True

    client = TestClient(fleet_main.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    cfg = client.get("/api/fleet/config").json()
    assert cfg["success"] is True
    admiral_tools = {t["id"] for t in cfg["data"]["bots"]["admiral"]["tools"]}
    assert "fleet_delegate" in admiral_tools

    voss = client.get("/api/bots/voss").json()
    assert voss["success"] is True
    assert "view_logs" in {t["id"] for t in voss["data"]["tools"]}

    tools = client.get("/api/bots/dr_voss/tools").json()
    assert "Nexus" in tools["data"]["note"]
    assert any(t["id"] == "health_check" for t in tools["data"]["tools"])

    nexus = client.get("/api/nexus/status").json()
    assert nexus["data"]["architecture"] == "nexus-v2"
    assert any(row["nexus_id"] == "sentinel" for row in nexus["data"]["roster"])
