from __future__ import annotations

import argparse
import asyncio

from email_validator import EmailNotValidError, validate_email

from accounts import create_user
from auth import validate_auth_config
from db import close_pool, get_pool
from personas import TANGO_PERSONAS


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the first Project Tango administrator")
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--adopt-legacy-data",
        action="store_true",
        help="Assign pre-account Tango sessions and memories to this administrator",
    )
    return parser.parse_args()


async def bootstrap(args: argparse.Namespace) -> None:
    validate_auth_config()
    try:
        normalized_email = validate_email(args.email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise SystemExit(f"Invalid email: {exc}") from exc
    pool = await get_pool()
    try:
        existing_admin = await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM tango.users WHERE role = 'admin')"
        )
        if existing_admin:
            raise SystemExit("An administrator already exists; bootstrap refused")
        access = [
            {"persona_id": persona_id, "llm_model_override": None}
            for persona_id in TANGO_PERSONAS
        ]
        user, password = await create_user(
            pool,
            first_name=args.first_name,
            last_name=args.last_name,
            email=normalized_email,
            role="admin",
            persona_access=access,
            created_by=None,
            adopt_legacy_data=args.adopt_legacy_data,
        )
        print("Project Tango administrator created.")
        print(f"Account ID: {user['id']}")
        print(f"Email: {user['email']}")
        print(f"Generated password (shown once): {password}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(bootstrap(arguments()))
