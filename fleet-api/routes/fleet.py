from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from config_manager import ConfigManager, services_requiring_restart
from models.responses import ApiResponse
from nexus_catalog import enrich_config, present_config
from service_manager import ServiceManager

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@router.get("/status")
def fleet_status(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    sm: ServiceManager = request.app.state.service_manager
    config = cm.load()
    statuses = {}
    for bot_id, bot in config.get("bots", {}).items():
        service = bot.get("identity", {}).get("service", "")
        statuses[bot_id] = sm.status(service) if service else "unknown"
    if "dr_voss" in statuses and "voss" not in statuses:
        statuses["voss"] = statuses["dr_voss"]
    statuses.setdefault("sentinel", sm.status("schubert-sentinel.service"))
    return ApiResponse(success=True, data=statuses, last_modified=_utcnow())


@router.get("/config")
def get_fleet_config(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    return ApiResponse(
        success=True,
        data=present_config(config),
        last_modified=config.get("last_modified", _utcnow()),
    )


@router.put("/config")
def put_fleet_config(request: Request, body: dict) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    before = cm.load()
    saved = cm.save(body)
    restarts = services_requiring_restart(before, saved)
    return ApiResponse(
        success=True,
        data=enrich_config(saved),
        requires_restart=restarts,
        last_modified=saved.get("last_modified", _utcnow()),
    )


@router.get("/stats")
def fleet_stats(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    sm: ServiceManager = request.app.state.service_manager
    config = enrich_config(cm.load())
    bots = config.get("bots", {})
    models = set()
    mcp_tools = 0
    active = 0
    nexus_tools = 0
    for bot in bots.values():
        llm = bot.get("llm", {})
        models.add(llm.get("model"))
        if llm.get("coding_model"):
            models.add(llm["coding_model"])
        mcp_tools += sum(1 for s in bot.get("mcp", {}).get("servers", []) if s.get("enabled")) * 4
        nexus_tools += sum(1 for t in bot.get("tools", []) if t.get("source") == "nexus")
        service = bot.get("identity", {}).get("service", "")
        if sm.status(service) == "online":
            active += 1
    mem = config.get("memory_stats", {})
    return ApiResponse(
        success=True,
        data={
            "active_bots": active,
            "llm_models": len({m for m in models if m}),
            "mcp_tools": mcp_tools,
            "nexus_tools": nexus_tools,
            "memories": mem.get("memories", 0),
            "entities": mem.get("entities", 0),
            "facts": mem.get("facts", 0),
        },
        last_modified=_utcnow(),
    )


@router.get("/protocol")
def get_protocol(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    return ApiResponse(
        success=True,
        data=config.get("fleet_protocol", {}),
        last_modified=config.get("last_modified", _utcnow()),
    )


@router.put("/protocol")
def put_protocol(request: Request, body: dict) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    before = cm.load()
    saved = cm.update({"fleet_protocol": body})
    restarts = services_requiring_restart(before, saved)
    return ApiResponse(
        success=True,
        data=saved.get("fleet_protocol", {}),
        requires_restart=restarts,
        last_modified=saved.get("last_modified", _utcnow()),
    )
