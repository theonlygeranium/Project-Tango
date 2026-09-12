"""QuartermasterBot — Tier 3 logistics and infrastructure bot."""

from __future__ import annotations

import logging

import discord

from nexus.bot.base import FleetBot
from nexus.bot.tools import Tool
from nexus.bus.event import NexusEvent

logger = logging.getLogger(__name__)


class QuartermasterBot(FleetBot):
    """Tier 3 logistics and infrastructure bot."""

    def get_system_prompt(self) -> str:
        with open(self.config.system_prompt_file, "r", encoding="utf-8") as f:
            return f.read()

    def get_tools(self) -> list[Tool]:
        from bots.quartermaster.tools import QUARTERMASTER_TOOLS

        return QUARTERMASTER_TOOLS

    async def handle_task(self, event: NexusEvent) -> None:
        task_id: str = event.payload.get("task_id", "")
        description: str = event.payload.get("description", "")
        try:
            response = await self.llm.call(
                messages=[
                    {"role": "system", "content": self.get_system_prompt()},
                    {"role": "user", "content": description},
                ]
            )
            await self.nexus.publish(
                NexusEvent.create(
                    event_type="task.result",
                    source=self.bot_id,
                    target=event.source,
                    correlation_id=event.correlation_id,
                    payload={
                        "task_id": task_id,
                        "status": "success",
                        "result": {"content": response.content},
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
        response = await self.llm.call(
            messages=[
                {"role": "system", "content": self.get_system_prompt()},
                {"role": "user", "content": message.content},
            ]
        )
        await self.discord.send(message.channel, response.content)

    def _is_addressed(self, message: discord.Message) -> bool:
        return True
