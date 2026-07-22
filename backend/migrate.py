from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import asyncpg

from db import _connection_kwargs

MIGRATION_DIRECTORY = Path(__file__).parent / "migrations"
MIGRATION_NAME = re.compile(r"^(\d+)_.*\.sql$")
LOCK_NAME = "project-tango-schema-migrations"


def discover_migrations() -> list[tuple[int, Path, str]]:
    migrations: list[tuple[int, Path, str]] = []
    for path in MIGRATION_DIRECTORY.glob("*.sql"):
        match = MIGRATION_NAME.match(path.name)
        if match is None:
            continue
        content = path.read_text(encoding="utf-8")
        migrations.append((int(match.group(1)), path, hashlib.sha256(content.encode()).hexdigest()))
    return sorted(migrations, key=lambda migration: migration[0])


async def baseline_existing_schema(
    connection: asyncpg.Connection, migrations: list[tuple[int, Path, str]]
) -> None:
    """Record legacy manual migrations only when their schema evidence exists."""
    evidence = {
        1: bool(
            await connection.fetchval(
                "SELECT to_regclass('tango.sessions') IS NOT NULL AND to_regclass('tango.turns') IS NOT NULL"
            )
        ),
        2: bool(
            await connection.fetchval("SELECT to_regclass('tango.memories') IS NOT NULL")
        ),
        3: bool(
            await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'tango' AND table_name = 'memories'
                      AND column_name = 'resolved_at'
                )
                """
            )
        ),
    }
    for version, path, checksum in migrations:
        if version not in evidence or not evidence[version]:
            continue
        await connection.execute(
            """
            INSERT INTO tango.schema_migrations (version, filename, checksum)
            VALUES ($1, $2, $3)
            ON CONFLICT (version) DO NOTHING
            """,
            version,
            path.name,
            checksum,
        )


async def migrate() -> None:
    connection = await asyncpg.connect(**_connection_kwargs())
    try:
        await connection.execute("SELECT pg_advisory_lock(hashtext($1))", LOCK_NAME)
        await connection.execute("CREATE SCHEMA IF NOT EXISTS tango")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tango.schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        migrations = discover_migrations()
        await baseline_existing_schema(connection, migrations)
        applied_rows = await connection.fetch(
            "SELECT version, filename, checksum FROM tango.schema_migrations ORDER BY version"
        )
        applied = {int(row["version"]): row for row in applied_rows}

        for version, path, checksum in migrations:
            prior = applied.get(version)
            if prior is not None:
                if prior["filename"] != path.name or prior["checksum"] != checksum:
                    raise RuntimeError(
                        f"Applied migration {version} differs from {path.name}; refusing to continue"
                    )
                continue

            content = path.read_text(encoding="utf-8")
            async with connection.transaction():
                await connection.execute(content)
                await connection.execute(
                    """
                    INSERT INTO tango.schema_migrations (version, filename, checksum)
                    VALUES ($1, $2, $3)
                    """,
                    version,
                    path.name,
                    checksum,
                )
            print(f"Applied migration {path.name}", flush=True)
    finally:
        try:
            await connection.execute("SELECT pg_advisory_unlock(hashtext($1))", LOCK_NAME)
        finally:
            await connection.close()


if __name__ == "__main__":
    asyncio.run(migrate())
