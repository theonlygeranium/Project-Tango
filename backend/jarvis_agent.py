from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from livekit.agents import Agent

from personas import Persona

logger = logging.getLogger("project-tango.agent")
LOCAL_QWEN_MODEL = "local/qwen3-fast"


TOOL_SOURCES: tuple[tuple[str, str], ...] = (
    ("tools.system_tools", "SYSTEM_TOOLS"),
    ("tools.media_tools", "MEDIA_TOOLS"),
    ("tools.web_tools", "WEB_TOOLS"),
    ("tools.information_tools", "INFORMATION_TOOLS"),
    ("tools.communication_tools", "COMMUNICATION_TOOLS"),
)


def _legacy_tools_enabled() -> bool:
    return os.getenv("TANGO_ENABLE_LEGACY_TOOLS", "").lower() in {"1", "true", "yes"}


@lru_cache(maxsize=1)
def _load_tools() -> tuple[Any, ...]:
    if not _legacy_tools_enabled():
        logger.info("Legacy AURA tool modules disabled; set TANGO_ENABLE_LEGACY_TOOLS=true to load them.")
        return ()

    tools: list[Any] = []
    for module_name, variable_name in TOOL_SOURCES:
        try:
            module = importlib.import_module(module_name)
            module_tools = getattr(module, variable_name)
        except ModuleNotFoundError as exc:
            logger.info("Skipping optional legacy tool module %s: %s", module_name, exc)
            continue
        except Exception as exc:
            logger.warning("Skipping optional tool module %s: %s", module_name, exc)
            continue

        if isinstance(module_tools, Iterable):
            tools.extend(module_tools)

    return tuple(tools)


class Jarvis(Agent):
    def __init__(self, persona: Persona, llm_model: str):
        self.persona = persona
        self.llm_model = llm_model
        local_model_guidance = ""
        if llm_model == LOCAL_QWEN_MODEL:
            local_model_guidance = (
                "\n\nYou are currently running on Schubert's local Qwen route. "
                "For this route, keep spoken replies especially tight: prefer one or two "
                "short sentences, avoid long lists, and offer to expand instead of giving "
                "the full explanation at once."
            )
        super().__init__(
            instructions=(
                f"{persona.system_prompt}\n\n"
                "You are part of Project Tango, a voice-first AI companion running through "
                "LiveKit WebRTC. Keep spoken answers natural, concise, and useful. When a "
                "tool is unavailable on this Linux deployment, explain that limitation plainly.\n\n"
                f"Runtime model route: {llm_model}. If the user asks what model powers you, "
                "answer with this exact Project Tango LiteLLM route. Do not claim to be "
                "Palmyra unless the route is writer/palmyra-x5-voice."
                f"{local_model_guidance}"
            ),
            tools=list(_load_tools()),
        )

    async def on_enter(self):
        await self.session.say(f"{self.persona.display_name} is online. How can I help?")
