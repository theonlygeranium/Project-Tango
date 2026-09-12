"""SentinelBot — Tier 3 autonomous testing & validation bot.

Wraps the Sentinel testing agent and exposes it as a FleetBot.
"""

from __future__ import annotations

import logging

import discord

from nexus.bot.base import FleetBot
from nexus.bot.tools import Tool
from nexus.bus.event import NexusEvent

logger = logging.getLogger(__name__)


class SentinelBot(FleetBot):
    """Tier 3 autonomous testing & validation bot."""

    def get_system_prompt(self) -> str:
        with open(self.config.system_prompt_file, "r", encoding="utf-8") as f:
            return f.read()

    def get_tools(self) -> list[Tool]:
        return []

    async def handle_task(self, event: NexusEvent) -> None:
        task_id: str = event.payload.get("task_id", "")
        description: str = event.payload.get("description", "")
        try:
            response = await self._llm_client.call(
                messages=[
                    {"role": "system", "content": self.get_system_prompt()},
                    {"role": "user", "content": description},
                ]
            )
            content = ""
            if isinstance(response, dict):
                content = response.get("content", "")
            await self.nexus.publish(
                NexusEvent.create(
                    event_type="task.result",
                    source=self.bot_id,
                    target=event.source,
                    correlation_id=event.correlation_id,
                    payload={
                        "task_id": task_id,
                        "status": "success",
                        "result": {"content": content},
                        "error": None,
                        "duration_s": 0.0,
                    },
                )
            )
        except Exception as exc:
            self.logger.exception("Task failed: %s", task_id)
            await self.nexus.publish(
                NexusEvent.create(
                    event_type="task.result",
                    source=self.bot_id,
                    target=event.source,
                    correlation_id=event.correlation_id,
                    payload={
                        "task_id": task_id,
                        "status": "failure",
                        "result": {},
                        "error": str(exc),
                        "duration_s": 0.0,
                    },
                )
            )

    async def handle_message(self, message: discord.Message) -> None:
        if not self._is_addressed(message):
            return
        response = await self._llm_client.call(
            messages=[
                {"role": "system", "content": self.get_system_prompt()},
                {"role": "user", "content": message.content},
            ]
        )
        content = ""
        if isinstance(response, dict):
            content = response.get("content", "")
        await self._discord_handler.send(message.channel, content)

    def _is_addressed(self, message: discord.Message) -> bool:
        return True
