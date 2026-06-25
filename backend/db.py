from __future__ import annotations

import logging
import os
from urllib.parse import unquote, urlparse

import asyncpg

logger = logging.getLogger("project-tango.db")

_pool: asyncpg.Pool | None = None


def _database_url() -> str | None:
    database_url = os.getenv("DATABASE_URL")
    return database_url


def _connection_kwargs() -> dict[str, str]:
    database_url = _database_url()
    if database_url:
        parsed = urlparse(database_url)
        if (
            parsed.scheme in {"postgresql", "postgres"}
            and parsed.hostname in {"localhost", "127.0.0.1"}
            and parsed.password is None
        ):
            database = parsed.path.lstrip("/") or os.getenv("PGDATABASE", "tango")
            username = parsed.username or os.getenv("PGUSER") or os.getenv("USER") or "z121532"
            return {
                "database": database,
                "user": unquote(username),
                "host": os.getenv("TANGO_DB_SOCKET_DIR", "/var/run/postgresql"),
            }
        return {"dsn": database_url}

    return {
        "database": os.getenv("PGDATABASE", "tango"),
        "user": os.getenv("PGUSER") or os.getenv("USER") or "z121532",
        "host": os.getenv("TANGO_DB_SOCKET_DIR", "/var/run/postgresql"),
    }


async def get_pool() -> asyncpg.Pool:
    global _pool

    if _pool is None:
        _pool = await asyncpg.create_pool(
            **_connection_kwargs(),
            min_size=int(os.getenv("TANGO_DB_POOL_MIN", "2")),
            max_size=int(os.getenv("TANGO_DB_POOL_MAX", "10")),
            command_timeout=30,
            server_settings={"search_path": "tango"},
        )
        logger.info("Tango database pool initialized.")

    return _pool


async def close_pool() -> None:
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Tango database pool closed.")
