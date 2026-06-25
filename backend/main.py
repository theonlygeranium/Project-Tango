from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from db import close_pool, get_pool
from history import (
    close_session,
    create_session,
    get_session_turns,
    get_sessions,
    mask_client_ip,
    record_turn,
)
from personas import DEFAULT_PERSONA_ID, Persona, get_persona, list_personas

dotenv_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("project-tango")

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "dummy")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
TANGO_AGENT_NAME = os.getenv("TANGO_AGENT_NAME", "tango-agent")

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await get_pool()
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(title="Project Tango Backend", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "TANGO_CORS_ORIGINS",
        "http://localhost:3006,http://127.0.0.1:3006",
    ).split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    room_name: str | None = None
    participant_identity: str | None = None
    participant_name: str | None = None
    participant_metadata: str | None = None
    participant_attributes: dict[str, str] = Field(default_factory=dict)
    persona_id: str | None = None
    persona: str | None = None
    room_config: dict[str, Any] | None = None


def _require_livekit_env() -> None:
    missing = [
        name
        for name, value in {
            "LIVEKIT_URL": LIVEKIT_URL,
            "LIVEKIT_API_KEY": LIVEKIT_API_KEY,
            "LIVEKIT_API_SECRET": LIVEKIT_API_SECRET,
        }.items()
        if not value
    ]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing environment variables: {', '.join(missing)}")


def _room_name(persona: Persona, requested_room: str | None = None) -> str:
    if requested_room:
        return requested_room
    return f"tango_{persona.id}_{uuid.uuid4().hex[:10]}"


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"client_metadata": value}

    return parsed if isinstance(parsed, dict) else {"client_metadata": value}


def _request_history_context(request: Request | None) -> dict[str, str]:
    if request is None:
        return {}

    raw_ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For")
        or (request.client.host if request.client else None)
    )
    masked_ip = mask_client_ip(raw_ip)
    user_agent = request.headers.get("user-agent")

    context: dict[str, str] = {}
    if masked_ip:
        context["client_ip"] = masked_ip
    if user_agent:
        context["user_agent"] = user_agent[:512]
    return context


def _token_metadata(
    persona: Persona,
    existing_metadata: str | None = None,
    history_context: dict[str, str] | None = None,
) -> str:
    payload = _json_object(existing_metadata)
    payload.update(
        {
            "persona_id": persona.id,
            "display_name": persona.display_name,
        }
    )
    if history_context:
        payload["history"] = history_context
    return json.dumps(payload)


def _token_attributes(persona: Persona, request: TokenRequest) -> dict[str, str]:
    return {
        **request.participant_attributes,
        "tango.persona": persona.id,
        "tango.display_name": persona.display_name,
    }


def create_participant_token(
    request: TokenRequest,
    persona: Persona,
    room_name: str,
    history_context: dict[str, str] | None = None,
) -> str:
    _require_livekit_env()

    from livekit import api

    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    token = token.with_identity(
        request.participant_identity or f"tango_user_{uuid.uuid4().hex[:8]}"
    ).with_name(request.participant_name or "Project Tango User")
    token = token.with_metadata(_token_metadata(persona, request.participant_metadata, history_context))
    token = token.with_attributes(_token_attributes(persona, request))
    token = token.with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_publish_data=True,
            can_subscribe=True,
        )
    )
    if request.room_config:
        token = token.with_room_config(request.room_config)

    return token.to_jwt()


def connection_details(request: TokenRequest, http_request: Request | None = None) -> dict[str, Any]:
    persona = get_persona(request.persona_id or request.persona)
    room_name = _room_name(persona, request.room_name)
    history_context = _request_history_context(http_request)
    participant_token = create_participant_token(request, persona, room_name, history_context)
    persona_payload = persona.public_dict()

    logger.info(
        "Issued Tango token room=%s persona_id=%s model=%s voice_id=%s llm_base_url=%s",
        room_name,
        persona.id,
        persona.llm_model,
        persona.voice_id,
        LITELLM_BASE_URL,
    )

    return {
        "server_url": LIVEKIT_URL,
        "participant_token": participant_token,
        "serverUrl": LIVEKIT_URL,
        "participantToken": participant_token,
        "room_name": room_name,
        "roomName": room_name,
        "participant_name": request.participant_name or "Project Tango User",
        "participantName": request.participant_name or "Project Tango User",
        "persona": persona_payload,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "project-tango-backend",
        "litellm_base_url": LITELLM_BASE_URL,
        "personas": [persona["id"] for persona in list_personas()],
    }


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


@app.get("/api/personas")
async def personas() -> dict[str, Any]:
    return {"default_persona_id": DEFAULT_PERSONA_ID, "personas": list_personas()}


@app.get("/api/connection-details")
async def get_connection_details(
    request: Request,
    persona: str | None = None,
    persona_id: str | None = None,
    room_name: str | None = None,
) -> dict[str, Any]:
    details = connection_details(
        TokenRequest(persona_id=persona_id or persona, room_name=room_name),
        http_request=request,
    )
    return details


@app.post("/api/connection-details", status_code=201)
@app.post("/getToken", status_code=201)
async def post_connection_details(request: Request) -> dict[str, Any]:
    body = await request.json()
    details = connection_details(TokenRequest(**body), http_request=request)
    return details


def _api_database_error() -> JSONResponse:
    return JSONResponse({"error": "Database error"}, status_code=500)


def _serialize_time(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _serialize_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "id": str(row["id"]),
        "started_at": _serialize_time(row.get("started_at")),
        "ended_at": _serialize_time(row.get("ended_at")),
    }


def _serialize_turn(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "recorded_at": _serialize_time(row.get("recorded_at")),
    }


@app.get("/api/history")
@limiter.limit("30/minute")
async def history_endpoint(request: Request, limit: int = 20, offset: int = 0) -> Any:
    del request
    try:
        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)
        sessions = await get_sessions(limit=bounded_limit, offset=bounded_offset)
        return {
            "sessions": [_serialize_session(session) for session in sessions],
            "limit": bounded_limit,
            "offset": bounded_offset,
        }
    except Exception:
        logger.exception("History sessions query failed.")
        return _api_database_error()


@app.get("/api/history/{session_id}")
@limiter.limit("30/minute")
async def history_detail_endpoint(request: Request, session_id: str) -> Any:
    del request
    try:
        parsed_session_id = str(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id") from None

    try:
        turns = await get_session_turns(parsed_session_id)
        return {
            "session_id": parsed_session_id,
            "turns": [_serialize_turn(turn) for turn in turns],
        }
    except Exception:
        logger.exception("History detail query failed session_id=%s", parsed_session_id)
        return _api_database_error()


def _persona_id_from_job_context(ctx: Any) -> str | None:
    sources = [
        getattr(getattr(ctx, "job", None), "metadata", None),
        getattr(getattr(ctx, "room", None), "metadata", None),
    ]
    for source in sources:
        parsed = _json_object(source)
        persona_id = parsed.get("persona_id") or parsed.get("persona")
        if isinstance(persona_id, str):
            return persona_id

    room_name = getattr(getattr(ctx, "room", None), "name", "")
    if room_name.startswith("tango_"):
        parts = room_name.split("_")
        if len(parts) >= 2:
            return parts[1]
    return None


def _history_context_from_participant(participant: Any | None) -> dict[str, str]:
    if participant is None:
        return {}

    payload = _json_object(getattr(participant, "metadata", None))
    history_payload = payload.get("history")
    history_context = history_payload if isinstance(history_payload, dict) else {}
    attributes = getattr(participant, "attributes", {}) or {}

    context: dict[str, str] = {}
    persona_id = payload.get("persona_id") or attributes.get("tango.persona")
    if isinstance(persona_id, str):
        context["persona_id"] = persona_id

    client_ip = history_context.get("client_ip") or attributes.get("tango.client_ip")
    if isinstance(client_ip, str):
        masked_ip = mask_client_ip(client_ip)
        if masked_ip:
            context["client_ip"] = masked_ip

    user_agent = history_context.get("user_agent") or attributes.get("tango.user_agent")
    if isinstance(user_agent, str):
        context["user_agent"] = user_agent[:512]

    return context


def _chat_message_text(item: Any) -> str:
    text_content = getattr(item, "text_content", None)
    if isinstance(text_content, str):
        return text_content

    content = getattr(item, "content", None)
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif hasattr(part, "text"):
            text = getattr(part, "text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _message_token_count(item: Any) -> int:
    metrics = getattr(item, "metrics", {}) or {}
    if not hasattr(metrics, "get"):
        return 0

    for key in ("total_tokens", "completion_tokens", "prompt_tokens"):
        value = metrics.get(key)
        if isinstance(value, int):
            return max(value, 0)
    return 0


def _message_latency_ms(item: Any) -> int | None:
    metrics = getattr(item, "metrics", {}) or {}
    if not hasattr(metrics, "get"):
        return None

    for key in ("e2e_latency", "tts_node_ttfb", "llm_node_ttft"):
        value = metrics.get(key)
        if isinstance(value, int | float) and value >= 0:
            return int(value * 1000)
    return None


def _usage_total_tokens(usage: Any) -> int:
    total = 0
    for model_usage in getattr(usage, "model_usage", []) or []:
        total_tokens = getattr(model_usage, "total_tokens", None)
        if isinstance(total_tokens, int):
            total += max(total_tokens, 0)
            continue

        for field_name in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            value = getattr(model_usage, field_name, None)
            if isinstance(value, int):
                total += max(value, 0)
    return total



async def _dispatch_agent(room_name: str) -> None:
    """Explicitly dispatch the registered LiveKit worker to this room.

    The worker has an agent_name, so LiveKit will not auto-dispatch it to every
    room. The frontend calls this endpoint after the participant joins.
    """
    try:
        from livekit import api as _lkapi
        async with _lkapi.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET) as _client:
            await _client.agent_dispatch.create_dispatch(
                _lkapi.CreateAgentDispatchRequest(room=room_name, agent_name=TANGO_AGENT_NAME)
            )
        logger.info("Agent dispatched room=%s agent_name=%s", room_name, TANGO_AGENT_NAME)
    except Exception:
        logger.exception("Agent dispatch failed room=%s agent_name=%s", room_name, TANGO_AGENT_NAME)


@app.post("/api/dispatch")
async def dispatch_agent_to_room(request: Request) -> dict:
    body = await request.json()
    rn = body.get("room_name")
    if not rn or not isinstance(rn, str):
        raise HTTPException(status_code=400, detail="room_name required")
    asyncio.create_task(_dispatch_agent(rn))
    return {"dispatched": True, "room_name": rn}

async def entrypoint(ctx: Any) -> None:
    from jarvis_agent import Jarvis
    from livekit.agents import (
        AgentSession,
        AutoSubscribe,
        CloseEvent,
        ConversationItemAddedEvent,
        SessionUsageUpdatedEvent,
    )
    from livekit.agents.llm import ChatMessage
    from livekit.plugins import deepgram, elevenlabs, openai, silero

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    participant_context = _history_context_from_participant(participant)
    persona = get_persona(participant_context.get("persona_id") or _persona_id_from_job_context(ctx))
    room_name = getattr(getattr(ctx, "room", None), "name", "unknown")

    logger.info(
        "Starting Tango agent room=%s persona_id=%s model=%s voice_id=%s llm_base_url=%s",
        room_name,
        persona.id,
        persona.llm_model,
        persona.voice_id,
        LITELLM_BASE_URL,
    )

    history_session_id: str | None = None
    try:
        history_session_id = await create_session(
            persona_id=persona.id,
            persona_name=persona.display_name,
            livekit_room=room_name,
            llm_model=persona.llm_model,
            user_agent=participant_context.get("user_agent"),
            client_ip=participant_context.get("client_ip"),
        )
        logger.info(
            "Tango history session created session_id=%s room=%s persona_id=%s",
            history_session_id,
            room_name,
            persona.id,
        )
    except Exception:
        logger.exception("Could not create Tango history session; voice session will continue.")

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-3",
            language="en-US",
            interim_results=True,
            endpointing_ms=300,
            smart_format=True,
        ),
        llm=openai.LLM(
            base_url=LITELLM_BASE_URL,
            api_key=LITELLM_MASTER_KEY,
            model=persona.llm_model,
        ),
        tts=elevenlabs.TTS(
            model="eleven_flash_v2_5",
            voice_id=persona.voice_id,
            api_key=os.getenv("ELEVENLABS_API_KEY"),
            voice_settings=elevenlabs.VoiceSettings(**persona.voice_settings),
            streaming_latency=3,
            auto_mode=True,
        ),
        use_tts_aligned_transcript=True,
    )

    session_turns: list[dict[str, Any]] = []
    close_error_code: str | None = None
    total_tokens = 0
    history_flushed = False
    history_flush_lock = asyncio.Lock()

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev: ConversationItemAddedEvent) -> None:
        if not isinstance(ev.item, ChatMessage):
            return
        if getattr(ev.item, "interrupted", False):
            return

        role = getattr(ev.item, "role", None)
        speaker = "agent" if role == "assistant" else role
        if speaker not in {"user", "agent"}:
            return

        record_turn(
            session_turns,
            len(session_turns),
            speaker,
            _chat_message_text(ev.item),
            tokens_used=_message_token_count(ev.item),
            latency_ms=_message_latency_ms(ev.item),
        )

    @session.on("session_usage_updated")
    def on_session_usage_updated(ev: SessionUsageUpdatedEvent) -> None:
        nonlocal total_tokens
        total_tokens = _usage_total_tokens(ev.usage)

    async def flush_history() -> None:
        nonlocal history_flushed, total_tokens
        async with history_flush_lock:
            if history_flushed or history_session_id is None:
                return

            total_tokens = total_tokens or _usage_total_tokens(getattr(session, "usage", None))
            try:
                await close_session(
                    history_session_id,
                    turns=session_turns,
                    total_tokens=total_tokens,
                    error_code=close_error_code,
                )
            except Exception:
                logger.exception("Could not flush Tango history session session_id=%s", history_session_id)
                return

            history_flushed = True
            logger.info(
                "Tango history session flushed session_id=%s turns=%d total_tokens=%d",
                history_session_id,
                len(session_turns),
                total_tokens,
            )

    @session.on("close")
    def on_close(ev: CloseEvent) -> None:
        nonlocal close_error_code
        if ev.error is not None:
            close_error_code = str(ev.reason)
        logger.info("Tango agent session closed reason=%s turns=%d", ev.reason, len(session_turns))
        asyncio.create_task(flush_history())

    ctx.add_shutdown_callback(flush_history)

    try:
        await session.start(agent=Jarvis(persona), room=ctx.room)
    except Exception as exc:
        error_text = str(exc).lower()
        if "timeout" in error_text or "504" in error_text:
            logger.warning(
                "LLM timeout on %s; LiteLLM may fall back to cloud. persona=%s",
                persona.llm_model,
                persona.display_name,
            )
        raise
    logger.info("Tango agent session started.")


if __name__ == "__main__":
    from livekit.agents import WorkerOptions, cli

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=TANGO_AGENT_NAME,
            shutdown_process_timeout=15.0,
        )
    )
