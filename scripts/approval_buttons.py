#!/usr/bin/env python3
"""Proceed / Cancel / Regenerate buttons for fleet Discord replies."""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

import discord

PROCEED_TEXT = (
    "Yes, proceed with the plan you just outlined. "
    "Do not ask me to confirm again unless the next step is a git push, "
    "a Slack post, or restarting a critical service."
)

_APPROVAL_RE = re.compile(
    r"(?:"
    r"\b(?:shall i|should i|want me to|would you like(?: me)? to|may i)\b"
    r"|\b(?:can i|could i) proceed\b"
    r"|\bready to (?:implement|proceed|apply|patch|fix)\b"
    r"|\bawaiting (?:your )?(?:approval|confirmation|go-ahead)\b"
    r"|\breply (?:`?yes`?|to confirm)\b"
    r"|\bconfirm(?:ation)? (?:required|to proceed)\b"
    r"|\b(?:proceed|implement|apply(?: these| this| the)? (?:change|patch|fix))s?\?"
    r")",
    re.IGNORECASE,
)

_COMPLETE_RE = re.compile(
    r"(?:"
    r"\*\*implementation complete\*\*"
    r"|implementation complete"
    r"|summary of what (?:was|is) accomplished"
    r"|what was (?:delivered|deployed|accomplished)"
    r"|\*\*done\.\*\*"
    r"|\*\*fixed\.\*\*"
    r"|is now live\b"
    r"|already (?:complete|done|applied|deployed|implemented)"
    r"|no further (?:action|changes) (?:needed|required)"
    r")",
    re.IGNORECASE,
)

OnClick = Callable[[discord.Interaction], Awaitable[None]]


def looks_like_approval_request(text: str | None) -> bool:
    """True when the bot is asking the captain to approve an implementation."""
    if not text:
        return False
    return bool(_APPROVAL_RE.search(text))


def looks_like_completion(text: str | None) -> bool:
    """True when the bot is reporting finished work, not asking to start it."""
    if not text:
        return False
    return bool(_COMPLETE_RE.search(text))


def should_attach_proceed(response: str | None) -> bool:
    """Attach Proceed on open plans; skip errors and finished work."""
    if not response:
        return False
    stripped = response.lstrip()
    if stripped.startswith(("⏹️", "❌", "Error:", "⏱️")):
        return False
    if looks_like_completion(stripped):
        return False
    return True


def progress_anchor(source, interaction: discord.Interaction | None = None):
    """Reuse an existing thread so Proceed does not spawn a second one."""
    thread = getattr(source, "thread", None)
    if thread is not None:
        return thread
    return source


class AgentReplyView(discord.ui.View):
    """✅ Proceed, ❌ Cancel, 🔁 Regenerate on a bot follow-up."""

    def __init__(
        self,
        channel_id: int,
        admin_user_id: int,
        *,
        show_proceed: bool = True,
        on_proceed: OnClick | None = None,
        on_regenerate: OnClick | None = None,
        timeout: float = 600,
    ):
        super().__init__(timeout=timeout)
        self.channel_id = channel_id
        self.admin_user_id = admin_user_id
        self._on_proceed = on_proceed
        self._on_regenerate = on_regenerate
        if not show_proceed:
            self.remove_item(self.proceed_button)
            self.remove_item(self.cancel_button)

    async def _require_captain(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.admin_user_id:
            return True
        await interaction.response.send_message(
            "Only the captain can use these buttons.",
            ephemeral=True,
        )
        return False

    async def _disable_action_buttons(self, interaction: discord.Interaction) -> None:
        self.proceed_button.disabled = True
        self.cancel_button.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Proceed", style=discord.ButtonStyle.success, emoji="✅")
    async def proceed_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._require_captain(interaction):
            return
        if self._on_proceed is None:
            await interaction.response.send_message(
                "Proceed is not wired on this bot.", ephemeral=True
            )
            return
        await interaction.response.defer()
        await self._disable_action_buttons(interaction)
        await self._on_proceed(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._require_captain(interaction):
            return
        await self._disable_action_buttons(interaction)
        await interaction.response.send_message(
            "Cancelled. Nothing further will be applied from that plan.",
            ephemeral=True,
        )

    @discord.ui.button(label="Regenerate", style=discord.ButtonStyle.secondary, emoji="🔁")
    async def regenerate_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._require_captain(interaction):
            return
        if self._on_regenerate is None:
            await interaction.response.send_message(
                "No previous input to regenerate.", ephemeral=True
            )
            return
        await interaction.response.defer()
        button.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await self._on_regenerate(interaction)