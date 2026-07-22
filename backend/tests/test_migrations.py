from __future__ import annotations

import re

import migrate


def test_migration_versions_are_unique_and_ordered() -> None:
    migrations = migrate.discover_migrations()
    versions = [version for version, _, _ in migrations]
    assert versions == sorted(set(versions))
    assert versions[-1] == 4
    assert all(re.fullmatch(r"[0-9a-f]{64}", checksum) for _, _, checksum in migrations)


def test_account_migration_contains_security_and_isolation_tables() -> None:
    migration = (migrate.MIGRATION_DIRECTORY / "004_accounts_auth.sql").read_text()
    for table in (
        "tango.users",
        "tango.user_persona_access",
        "tango.auth_sessions",
        "tango.auth_rate_limits",
        "tango.voice_room_grants",
        "tango.admin_audit_log",
    ):
        assert table in migration
    assert "ADD COLUMN IF NOT EXISTS user_id" in migration
    assert "password_lookup     BYTEA NOT NULL UNIQUE" in migration
    assert "CREATE EXTENSION" not in migration
