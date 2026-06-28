from __future__ import annotations

import logging

logger = logging.getLogger("project-tango.sip")

_PREFIX_TO_PERSONA: tuple[tuple[str, str], ...] = (
    ("tango-general-info-jeremiah-", "jeremiah"),
    ("tango-general-info-jacob-", "jacob"),
    ("tango-general-info-mama-lulu-", "mama-lulu"),
    ("tango-mama-lulu-", "mama-lulu"),
    ("tango-therapy-", "therapy"),
    ("tango-general-info-", "general-info"),
    ("tango-meditation-", "meditation"),
    ("tango-pinoy-pride-", "pinoy-pride"),
)

SIP_GREETING_ADDENDUM = (
    "\n\nThis is a phone call (SIP session). Begin your greeting by introducing yourself "
    "by name and role before anything else. Keep the introduction warm and brief, one "
    "sentence maximum."
)


def persona_key_from_room_name(room_name: str) -> str | None:
    for prefix, persona_key in _PREFIX_TO_PERSONA:
        if room_name.startswith(prefix):
            logger.info("Resolved SIP persona=%s room=%s prefix=%s", persona_key, room_name, prefix)
            return persona_key

    logger.warning("Could not resolve SIP persona from room=%s", room_name)
    return None
