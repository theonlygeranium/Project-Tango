from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from config_manager import ConfigManager, services_requiring_restart
from models.responses import ApiResponse

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@router.get("/config")
def get_scheduler(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    return ApiResponse(
        success=True,
        data=config.get("scheduler", {}),
        last_modified=config.get("last_modified", _utcnow()),
    )


@router.put("/config")
def put_scheduler(request: Request, body: dict) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    before = cm.load()
    saved = cm.update({"scheduler": body})
    restarts = services_requiring_restart(before, saved)
    return ApiResponse(
        success=True,
        data=saved.get("scheduler", {}),
        requires_restart=restarts,
        last_modified=saved.get("last_modified", _utcnow()),
    )


@router.get("/monitored-services")
def monitored_services(request: Request) -> ApiResponse:
    cm: ConfigManager = request.app.state.config_manager
    config = cm.load()
    services = config.get("scheduler", {}).get("monitored_services", [])
    return ApiResponse(success=True, data=services, last_modified=_utcnow())
