from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from config_manager import ConfigManager, services_requiring_restart
from models.responses import ApiResponse
from nexus_catalog import enrich_bot, merge_tools, present_config, resolve_bot_id
from service_manager import ServiceManager

router = APIRouter(prefix="/api/bots", tags=["bots"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lookup_presented(config: dict, bot_id: str) -> tuple[str | None, dict]:
    presented = present_config(config)["bots"]
    for key in (bot_id, resolve_bot_id(bot_id, config)):
        if key and key in presented:
            return key, presented[key]
    raise HTTPException(status_code=404, detail=f"Bot not found: {bot_id}")


def _bot_or_404(config: dict, bot_id: str) -> tuple[str, dict]:
    file_id = resolve_bot_id(bot_id, config)
    if file_id:
        return file_id, config["bots"][file_id]
    _key, bot = _lookup_presented(config, bot_id)
    return bot_id, bot


@router.get("/{bot_id}")
def get_bot(bot_id: str, request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    _key, bot = _lookup_presented(config, bot_id)
    return ApiResponse(
        success=True,
        data=bot,
        last_modified=config.get("last_modified", _utcnow()),
    )


@router.put("/{bot_id}")
def put_bot(bot_id: str, request: Request, body: dict) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    before = cm.load()
    canonical, _bot = _bot_or_404(before, bot_id)
    try:
        saved = cm.update_bot(canonical, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    restarts = services_requiring_restart(before, saved)
    return ApiResponse(
        success=True,
        data=enrich_bot(saved["bots"][canonical], canonical),
        requires_restart=restarts,
        last_modified=saved.get("last_modified", _utcnow()),
    )


@router.get("/{bot_id}/status")
def bot_status(bot_id: str, request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    sm: ServiceManager = request.app.state.service_manager
    config = cm.load()
    canonical, bot = _bot_or_404(config, bot_id)
    service = bot.get("identity", {}).get("service", "")
    return ApiResponse(
        success=True,
        data={"bot_id": canonical, "requested_id": bot_id, "service": service, "status": sm.status(service)},
        last_modified=_utcnow(),
    )


@router.post("/{bot_id}/restart")
def bot_restart(bot_id: str, request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    sm: ServiceManager = request.app.state.service_manager
    config = cm.load()
    _canonical, bot = _bot_or_404(config, bot_id)
    service = bot.get("identity", {}).get("service", "")
    result = sm.restart(service)
    ok = result.get("status") == "restarted"
    return ApiResponse(
        success=ok,
        data=result,
        errors=[] if ok else [result.get("error", "restart failed")],
        requires_restart=[service] if ok else [],
        last_modified=_utcnow(),
    )


@router.get("/{bot_id}/logs")
def bot_logs(bot_id: str, request: Request, lines: int = 100) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    sm: ServiceManager = request.app.state.service_manager
    config = cm.load()
    _canonical, bot = _bot_or_404(config, bot_id)
    service = bot.get("identity", {}).get("service", "")
    return ApiResponse(
        success=True,
        data={"service": service, "logs": sm.logs(service, lines=lines)},
        last_modified=_utcnow(),
    )


@router.get("/{bot_id}/tools")
def bot_tools(bot_id: str, request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    key, bot = _lookup_presented(config, bot_id)
    tools = bot.get("tools") or merge_tools([], key or bot_id)
    nexus_ids = {t["id"] for t in tools if t.get("source") == "nexus"}
    return ApiResponse(
        success=True,
        data={
            "tools": tools,
            "note": (
                "Merged fleet-config tools with the Nexus catalog "
                f"({len(nexus_ids)} Nexus-only ids)."
            ),
        },
        last_modified=config.get("last_modified", _utcnow()),
    )
