from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from config_manager import ConfigManager
from models.responses import ApiResponse
from nexus_catalog import nexus_status
from service_manager import ServiceManager

router = APIRouter(prefix="/api/nexus", tags=["nexus"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@router.get("/status")
def get_nexus_status(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    sm: ServiceManager = request.app.state.service_manager
    config = cm.load()
    statuses = {}
    for bot_id, bot in config.get("bots", {}).items():
        service = bot.get("identity", {}).get("service", "")
        statuses[bot_id] = sm.status(service) if service else "unknown"
    statuses.setdefault("sentinel", sm.status("schubert-sentinel.service"))
    return ApiResponse(
        success=True,
        data=nexus_status(config, statuses),
        last_modified=_utcnow(),
    )
