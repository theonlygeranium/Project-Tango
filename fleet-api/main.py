from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from config_manager import ConfigManager
from routes import bots, fleet, memory, nexus, scheduler
from service_manager import ServiceManager

API_TOKEN = os.environ.get("FLEET_API_TOKEN", "")
APP_VERSION = "1.2.1"
UI_DIST = Path(os.environ.get("FLEET_UI_DIST", Path(__file__).resolve().parent.parent / "command-ui" / "dist"))


def _same_origin(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":")[0]
    origin = request.headers.get("origin") or ""
    referer = request.headers.get("referer") or ""
    if not host:
        return False
    return host in origin or host in referer


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in {"/health", "/docs", "/openapi.json", "/redoc", "/ui/config.js"}:
            return await call_next(request)
        if request.method == "GET" and not path.startswith("/api"):
            return await call_next(request)
        if not API_TOKEN:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {API_TOKEN}" or _same_origin(request):
            return await call_next(request)
        return Response(
            content='{"success":false,"errors":["unauthorized"],"data":null}',
            status_code=401,
            media_type="application/json",
        )


def create_app() -> FastAPI:
    app = FastAPI(title="Fleet Command API", version=APP_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://command.schubert.life",
            "https://api-command.schubert.life",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BearerAuthMiddleware)

    app.state.config_manager = ConfigManager()
    app.state.service_manager = ServiceManager()

    app.include_router(fleet.router)
    app.include_router(bots.router)
    app.include_router(scheduler.router)
    app.include_router(memory.router)
    app.include_router(nexus.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/ui/config.js")
    def ui_config() -> PlainTextResponse:
        payload = {
            "apiBase": "",
            "token": "",
            "version": APP_VERSION,
        }
        body = "window.__FLEET_UI__ = " + json.dumps(payload) + ";\n"
        return PlainTextResponse(body, media_type="application/javascript")

    if UI_DIST.is_dir():
        assets = UI_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")

        @app.get("/")
        def ui_index() -> FileResponse:
            return FileResponse(UI_DIST / "index.html")

        @app.get("/{path:path}")
        def ui_spa(path: str) -> FileResponse:
            candidate = (UI_DIST / path).resolve()
            if str(candidate).startswith(str(UI_DIST.resolve())) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")

    return app


app = create_app()
