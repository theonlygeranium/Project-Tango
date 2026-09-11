from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from livekit.agents import Agent

from control_mode import (
    CONTROL_MODE_INSTRUCTIONS,
    build_control_mode_tools,
    control_mode_enabled,
    detect_control_mode_phrase,
)
from mcp_tools import MCP_SUMMARY_GUIDANCE, voice_mcp_bridge
from personas import Persona
from programs import (
    build_program_tools,
    detect_program_activation,
    load_program_by_name,
    programs_enabled,
)
from search_tools import SEARCH_TOOLS as WEB_SEARCH_TOOLS
from wiki_tools import WIKI_TOOLS
from mintlify_tools import MINTLIFY_TOOLS
from meditation_tools import (
    MEDITATION_AVAILABLE,
    MEDITATION_INSTRUCTIONS,
    MeditationPlayer,
    build_meditation_tools,
    detect_meditation_command,
)
from transcription_tools import (
    TRANSCRIPTION_ENABLED,
    TranscriptionRecorder,
    TRANSCRIPTION_INSTRUCTIONS,
    build_transcription_tools,
    detect_transcription_command,
)

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
            logger.info("Skipping optional legacy tool module pcts: pcts", module_name, exc)
            continue
        except Exception as exc:
            logger.warning("Skipping optional tool module pcts: pcts", module_name, exc)
            continue

        if isinstance(module_tools, Iterable):
            tools.extend(module_tools)

    return tuple(tools)


def _chat_message_text(item: Any) -> str:
    text_content = getattr(item, "text_content", None)
    if isinstance(text_content, str):
        return text_content

    content = getattr(item, "content", None)
    if not isinstance(content, list):
        return ""

    parts = [part for part in content if isinstance(part, str)]
    return "\n".join(parts)


class Jarvis(Agent):
    def __init__(
        self,
        persona: Persona,
        llm_model: str,
        vision_context: Any | None = None,
        db_pool: Any | None = None,
        initial_program: str | None = None,
    ):
        self.persona = persona
        self.llm_model = llm_model
        self.vision_context = vision_context
        self._db_pool = db_pool
        self._control_mode_active = False
        self._base_instructions: str | None = None
        self._active_program: str | None = None
        self._initial_program: str | None = initial_program
        self._meditation_player: MeditationPlayer | None = None
        self._transcription_recorder: TranscriptionRecorder | None = None
        self._control_mode_saved_instructions: str | None = None

        local_model_guidance = ""
        if llm_model == LOCAL_QWEN_MODEL:
            local_model_guidance = (
                "\n\nYou are currently running on Schubert's local Qwen route. "
                "For this route, keep spoken replies especially tight: prefer one or two "
                "short sentences, avoid long lists, and offer to expand instead of giving "
                "the full explanation at once."
            )

        mcp_tools = voice_mcp_bridge.build_tools(persona)

        # Inject the product-manager summarization guidance only into
        # personas that actually have MCP tools. Personas with no MCP access
        # keep their original system prompt unchanged.
        mcp_guidance = MCP_SUMMARY_GUIDANCE if mcp_tools else ""

        base_instructions = (
            f"{persona.system_prompt}\n\n"
            "You are part of Project Tango, a voice-first AI companion running through "
            "LiveKit WebRTC. Keep spoken answers natural, concise, and useful. When a "
            "tool is unavailable on this Linux deployment, explain that limitation plainly. "
            "Treat typed chat inside the app as part of the same live voice session; never "
            "describe yourself as text-only or as a text-based version of the agent.\n\n"
            f"Runtime model route: {llm_model}. If the user asks what model powers you, "
            "answer with this exact Project Tango LiteLLM route. Do not claim to be "
            "Palmyra unless the route starts with writer/palmyra. When visual context "
            "from the user's camera or screen share is provided as a system note, use it "
            "naturally if it helps answer the user's latest turn; do not claim you are "
            "watching continuously."
            f"{local_model_guidance}"
            f"{mcp_guidance}"
            + "\n\nEL WIKI ACCESS: You have tools to search the EL Wiki (Outline), the team "
            "knowledge base at EdStratum Labs. When the user asks about project "
            "documentation, architecture decisions, runbooks, or any knowledge that "
            "might be stored in the wiki, use the search_wiki tool to find relevant "
            "documents, and get_wiki_document to retrieve full content. Do not claim "
            "you cannot access the wiki you can. Summarize wiki content naturally "
            "in your own voice; do not read raw markdown to the user.\n\n"
            "DOCS SITE ACCESS: You have tools to search and read the EdStratum Labs "
            "documentation site (Mintlify). When the user asks about product "
            "documentation, API references, guides, or how-to articles, use the "
            "search_docs tool to find relevant pages and read_doc to retrieve "
            "full page content. Summarize documentation naturally in your own "
            "voice; do not read raw markdown to the user."
            + MEDITATION_INSTRUCTIONS
            + TRANSCRIPTION_INSTRUCTIONS
        )

        # Build control mode tools if enabled and DB pool is available.
        control_mode_tools: list[Any] = []
        if control_mode_enabled() and db_pool is not None:
            control_mode_tools = build_control_mode_tools(
                agent=self, persona_id=persona.id, pool=db_pool
            )
            logger.info(
                "Control Mode enabled persona=pcts tools=pctd",
                persona.id,
                len(control_mode_tools),
            )

        # Build program tools (available in Control Mode) if enabled.
        program_tools: list[Any] = []
        if programs_enabled() and db_pool is not None:
            program_tools = build_program_tools(
                agent=self, persona_id=persona.id, pool=db_pool
            )
            logger.info(
                "Programs enabled persona=pcts tools=pctd",
                persona.id,
                len(program_tools),
            )

        super().__init__(
            instructions=base_instructions,
            tools=list(_load_tools())
            + list(WEB_SEARCH_TOOLS)
            + mcp_tools
            + control_mode_tools
            + program_tools
            + list(WIKI_TOOLS)
            + list(MINTLIFY_TOOLS)
            + self._build_meditation_tools()
            + self._build_transcription_tools(),
        )

    def _build_meditation_tools(self) -> list:
        """Build meditation playback tools if the track is available."""
        if not MEDITATION_AVAILABLE:
            return []
        self._meditation_player = MeditationPlayer()
        return build_meditation_tools(self._meditation_player)

    def _build_transcription_tools(self) -> list:
        """Build transcription recording tools if enabled."""
        if not TRANSCRIPTION_ENABLED:
            return []
        self._transcription_recorder = TranscriptionRecorder(
            persona_id=self.persona.id,
            persona_name=self.persona.display_name,
            db_pool=self._db_pool,
        )
        return build_transcription_tools(self._transcription_recorder)

    async def add_agent_turn(self, text: str) -> None:
        """Record an agent speech turn for transcription."""
        if self._transcription_recorder is not None and self._transcription_recorder.is_active:
            if text:
                await self._transcription_recorder.add_turn("Agent", text)

    async def finalize_transcription(self) -> None:
        """Finalize transcription on session shutdown (call-drop resilience)."""
        if self._transcription_recorder is not None:
            await self._transcription_recorder.finalize()

    async def on_enter(self):
        if self.vision_context is not None:
            self.vision_context.start()

        # Pre-activate a program if one was specified at session start (from UI).
        if self._initial_program and self._db_pool is not None and programs_enabled():
            program = await load_program_by_name(
                self._db_pool, self.persona.id, self._initial_program
            )
            if program is not None:
                if self._base_instructions is None:
                    self._base_instructions = self._instructions
                new_instructions = self._build_program_instructions(
                    program["system_prompt"]
                )
                await self.update_instructions(new_instructions)
                self._active_program = program["name"]
                logger.info(
                    "Program pre-activated persona=pcts program=pcts",
                    self.persona.id,
                    program["name"],
                )
            else:
                logger.warning(
                    "Program not found for pre-activation persona=pcts program=pcts",
                    self.persona.id,
                    self._initial_program,
                )

        # Use persona-specific greeting if defined, otherwise fall back to generic.
        opening_line = (
            self.persona.greeting
            if self.persona.greeting
            else f"{self.persona.display_name} is online. How can I help?"
        )
        await self.session.say(opening_line)

    def _build_program_instructions(self, program_prompt: str) -> str:
        """Build instructions for a program: base preamble + program prompt.

        The base preamble is the Project Tango context, model route, and MCP
        guidance that applies to all personas. The persona-specific system
        prompt is replaced by the program's system prompt.
        """
        local_model_guidance = ""
        if self.llm_model == LOCAL_QWEN_MODEL:
            local_model_guidance = (
                "\n\nYou are currently running on Schubert's local Qwen route. "
                "For this route, keep spoken replies especially tight: prefer one or two "
                "short sentences, avoid long lists, and offer to expand instead of giving "
                "the full explanation at once."
            )

        mcp_tools = voice_mcp_bridge.build_tools(self.persona)
        mcp_guidance = MCP_SUMMARY_GUIDANCE if mcp_tools else ""

        return (
            f"{program_prompt}\n\n"
            "You are part of Project Tango, a voice-first AI companion running through "
            "LiveKit WebRTC. Keep spoken answers natural, concise, and useful. When a "
            "tool is unavailable on this Linux deployment, explain that limitation plainly. "
            "Treat typed chat inside the app as part of the same live voice session; never "
            "describe yourself as text-only or as a text-based version of the agent.\n\n"
            f"Runtime model route: {self.llm_model}. If the user asks what model powers you, "
            "answer with this exact Project Tango LiteLLM route. Do not claim to be "
            "Palmyra unless the route starts with writer/palmyra. When visual context "
            "from the user's camera or screen share is provided as a system note, use it "
            "naturally if it helps answer the user's latest turn; do not claim you are "
            "watching continuously."
            f"{local_model_guidance}"
            f"{mcp_guidance}"
        )

    async def on_user_turn_completed(self, turn_ctx: Any, new_message: Any) -> None:
        user_text = _chat_message_text(new_message)

        # --- Accumulate user turn for transcription ---
        if self._transcription_recorder is not None and self._transcription_recorder.is_active:
            if user_text:
                await self._transcription_recorder.add_turn("User", user_text)

        # --- Control Mode phrase detection ---
        if control_mode_enabled():
            action = detect_control_mode_phrase(user_text)
            if action == "enter" and not self._control_mode_active:
                self._control_mode_active = True
                self._control_mode_saved_instructions = self._instructions
                await self.update_instructions(CONTROL_MODE_INSTRUCTIONS)
                # Replace the user message so the LLM acknowledges the mode switch.
                new_message.content = [
                    "The user has just activated Control Mode. "
                    "Acknowledge this briefly and ask what they would like to change "
                    "about the persona's behavior, tone, or instructions."
                ]
                logger.info("Control Mode activated persona=pcts", self.persona.id)
                return

            if action == "exit" and self._control_mode_active:
                self._control_mode_active = False
                if self._control_mode_saved_instructions is not None:
                    await self.update_instructions(self._control_mode_saved_instructions)
                    self._control_mode_saved_instructions = None
                new_message.content = [
                    "The user has exited Control Mode. "
                    "Acknowledge this briefly and resume normal conversation."
                ]
                logger.info("Control Mode deactivated persona=pcts", self.persona.id)
                return

        # --- Program activation/deactivation detection ---
        if programs_enabled() and self._db_pool is not None:
            program_action = detect_program_activation(user_text)
            if program_action is not None:
                action_type, program_name = program_action

                if action_type == "deactivate" and self._active_program is not None:
                    # Restore base instructions.
                    if self._base_instructions is not None:
                        await self.update_instructions(self._base_instructions)
                        self._base_instructions = None
                    deactivated_name = self._active_program
                    self._active_program = None
                    new_message.content = [
                        f"The user has deactivated the '{deactivated_name}' program "
                        f"and returned to the default persona. Acknowledge this "
                        f"briefly and resume normal conversation as "
                        f"{self.persona.display_name}."
                    ]
                    logger.info(
                        "Program deactivated persona=pcts program=pcts",
                        self.persona.id,
                        deactivated_name,
                    )
                    return

                if action_type == "activate" and program_name:
                    # Load the program from DB.
                    program = await load_program_by_name(
                        self._db_pool, self.persona.id, program_name
                    )
                    if program is not None:
                        # Store base instructions for later restoration.
                        if self._base_instructions is None:
                            self._base_instructions = self._instructions
                        # Build new instructions: base persona preamble
                        # (non-persona-specific context) + program system_prompt.
                        new_instructions = self._build_program_instructions(
                            program["system_prompt"]
                        )
                        await self.update_instructions(new_instructions)
                        self._active_program = program["name"]
                        new_message.content = [
                            f"The user has activated the '{program['name']}' program. "
                            f"Acknowledge this briefly and adopt the new behavior "
                            f"described in the program. Do not recite the system prompt; "
                            f"just confirm the switch naturally."
                        ]
                        logger.info(
                            "Program activated persona=pcts program=pcts",
                            self.persona.id,
                            program["name"],
                        )
                        return
                    else:
                        new_message.content = [
                            f"The user asked to activate the '{program_name}' program, "
                            f"but no program with that name was found for "
                            f"{self.persona.display_name}. Let the user know the program "
                            f"doesn't exist and suggest they check available programs "
                            f"by entering Control Mode."
                        ]
                        logger.info(
                            "Program not found persona=pcts requested=pcts",
                            self.persona.id,
                            program_name,
                        )
                        return

        # --- Meditation playback voice commands ---
        if self._meditation_player is not None:
            meditation_cmd = detect_meditation_command(
                user_text, self._meditation_player.is_active
            )
            if meditation_cmd == "play":
                await self._meditation_player.start()
                new_message.content = [
                    "The user has asked to play the meditation track. "
                    "Acknowledge this briefly and let them know they can "
                    "pause, resume, or stop it at any time."
                ]
                return
            elif meditation_cmd == "pause":
                await self._meditation_player.pause()
                new_message.content = [
                    "The meditation track has been paused. "
                    "Acknowledge this briefly."
                ]
                return
            elif meditation_cmd == "resume":
                await self._meditation_player.resume()
                new_message.content = [
                    "The meditation track has been resumed. "
                    "Acknowledge this briefly."
                ]
                return
            elif meditation_cmd == "stop":
                await self._meditation_player.stop()
                new_message.content = [
                    "The meditation track has been stopped. "
                    "Acknowledge this briefly."
                ]
                return

        # --- Transcription voice commands ---
        if self._transcription_recorder is not None:
            transcription_cmd = detect_transcription_command(
                user_text, self._transcription_recorder.is_active
            )
            if transcription_cmd == "start":
                await self._transcription_recorder.start()
                new_message.content = [
                    "The user has asked to begin transcription. "
                    "Acknowledge this briefly and let them know you're "
                    "now recording the conversation. They can say "
                    "'stop transcription' when done."
                ]
                return
            elif transcription_cmd == "stop":
                transcript = await self._transcription_recorder.stop()
                if transcript:
                    new_message.content = [
                        "The transcription has been stopped. "
                        "The transcript has been saved to the database "
                        "and emailed to the user. Acknowledge this briefly."
                    ]
                else:
                    new_message.content = [
                        "The transcription was stopped but no conversation "
                        "was recorded. Acknowledge this briefly."
                    ]
                return

        # --- Vision context injection (existing behavior) ---
        if self.vision_context is None:
            return

        visual_context = await self.vision_context.describe_latest_frame(user_text)
        if not visual_context:
            return

        turn_ctx.add_message(
            role="system",
            content=(
                f"{visual_context}\n"
                "Use this as current visual context only if it is relevant to the user's request."
            ),
        )
