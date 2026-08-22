from __future__ import annotations

import os
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from config_manager import ConfigManager
from routes import bots, fleet, memory, nexus, scheduler
from service_manager import ServiceManager

API_TOKEN = os.environ.get("FLEET_API_TOKEN", "")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
            return await call_next(request)
        if not API_TOKEN:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_TOKEN}":
            return Response(
                content='{"success":false,"errors":["unauthorized"],"data":null}',
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(title="Fleet Command API", version="1.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://command.schubert.life",
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
        return {"status": "ok", "version": "1.1.0"}

    return app


app = create_app()
