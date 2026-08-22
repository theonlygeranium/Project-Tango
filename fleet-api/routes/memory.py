from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from config_manager import ConfigManager, services_requiring_restart
from models.responses import ApiResponse

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@router.get("/stats")
def memory_stats(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    return ApiResponse(
        success=True,
        data=config.get("memory_stats", {}),
        last_modified=config.get("last_modified", _utcnow()),
    )


@router.get("/config")
def get_memory_config(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    admiral = config.get("bots", {}).get("admiral", {})
    return ApiResponse(
        success=True,
        data=admiral.get("memory", {}),
        last_modified=config.get("last_modified", _utcnow()),
    )


@router.put("/config")
def put_memory_config(request: Request, body: dict) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    before = cm.load()
    patch_bots = {bot_id: {"memory": body} for bot_id in before.get("bots", {}).keys()}
    saved = cm.update({"bots": patch_bots})
    restarts = services_requiring_restart(before, saved)
    return ApiResponse(
        success=True,
        data=body,
        requires_restart=restarts,
        last_modified=saved.get("last_modified", _utcnow()),
    )
