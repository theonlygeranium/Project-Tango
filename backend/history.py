from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Sequence
from typing import Any

from db import get_pool

HistoryTurn = dict[str, Any]


def mask_client_ip(raw_ip: str | None) -> str | None:
    if not raw_ip:
        return None

    candidate = raw_ip.split(",", maxsplit=1)[0].strip()
    if not candidate:
        return None

    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None

    if isinstance(parsed, ipaddress.IPv4Address):
        octets = candidate.split(".")
        return ".".join([*octets[:3], "0"])

    network = ipaddress.ip_network(f"{parsed}/64", strict=False)
    return str(network.network_address)


def _session_uuid(session_id: str | uuid.UUID) -> uuid.UUID:
    return session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)


async def create_session(
    user_id: str | uuid.UUID | None,
    persona_id: str,
    persona_name: str,
    livekit_room: str,
    llm_model: str,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> str:
    pool = await get_pool()
    session_id = uuid.uuid4()
    await pool.execute(
        """
        INSERT INTO tango.sessions
            (id, user_id, persona_id, persona_name, livekit_room, llm_model, user_agent, client_ip)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::inet)
        """,
        session_id,
        _session_uuid(user_id) if user_id else None,
        persona_id,
        persona_name,
        livekit_room,
        llm_model,
        user_agent,
        mask_client_ip(client_ip),
    )
    return str(session_id)


def record_turn(
    session_turns: list[HistoryTurn],
    turn_index: int,
    speaker: str,
    text: str,
    tokens_used: int = 0,
    latency_ms: int | None = None,
) -> None:
    clean_text = text.strip()
    if speaker not in {"user", "agent"} or not clean_text:
        return

    session_turns.append(
        {
            "turn_index": turn_index,
            "speaker": speaker,
            "text": clean_text,
            "tokens_used": max(tokens_used, 0),
            "latency_ms": latency_ms,
        }
    )


async def close_session(
    session_id: str | uuid.UUID,
    turns: Sequence[HistoryTurn] | None = None,
    total_tokens: int = 0,
    error_code: str | None = None,
) -> None:
    pool = await get_pool()
    session_uuid = _session_uuid(session_id)

    async with pool.acquire() as connection:
        async with connection.transaction():
            if turns:
                await connection.executemany(
                    """
                    INSERT INTO tango.turns
                        (session_id, turn_index, speaker, text, tokens_used, latency_ms)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (
                            session_uuid,
                            int(turn["turn_index"]),
                            turn["speaker"],
                            turn["text"],
                            int(turn.get("tokens_used") or 0),
                            turn.get("latency_ms"),
                        )
                        for turn in turns
                    ],
                )

            await connection.execute(
                """
                UPDATE tango.sessions
                SET ended_at = NOW(), total_tokens = $2, error_code = $3
                WHERE id = $1
                """,
                session_uuid,
                max(total_tokens, 0),
                error_code,
            )


async def get_sessions(
    user_id: str | uuid.UUID, limit: int = 20, offset: int = 0
) -> list[dict[str, Any]]:
    pool = await get_pool()
    bounded_limit = min(max(limit, 1), 100)
    bounded_offset = max(offset, 0)

    rows = await pool.fetch(
        """
        SELECT id, persona_id, persona_name, started_at, ended_at,
               duration_secs, livekit_room, llm_model, total_tokens, error_code
        FROM tango.sessions
        WHERE user_id = $1 AND ended_at IS NOT NULL ORDER BY started_at DESC
        LIMIT $2 OFFSET $3
        """,
        _session_uuid(user_id),
        bounded_limit,
        bounded_offset,
    )
    return [dict(row) for row in rows]


async def get_session_turns(
    session_id: str | uuid.UUID, user_id: str | uuid.UUID
) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT turn_index, speaker, text, tokens_used, latency_ms, recorded_at
        FROM tango.turns t
        JOIN tango.sessions s ON s.id = t.session_id
        WHERE t.session_id = $1 AND s.user_id = $2
        ORDER BY turn_index ASC
        """,
        _session_uuid(session_id),
        _session_uuid(user_id),
    )
    return [dict(row) for row in rows]
