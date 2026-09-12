#!/usr/bin/env python3
"""
Comprehensive patch for fleet UI/UX parity and chunk size fix.

Fixes:
1. Chunk size: 1900 -> 1800 (accounts for ~120-char FLEET tag overhead)
2. Port AgentProgressView (typing + spinner + elapsed time + tool calls) to Quartermaster and Cartographer
3. Import tool_descriptions for live tool call descriptions
4. Wire progress view into both FLEET delegation and direct message paths
"""

import sys

SCRIPTS_DIR = "/opt/Project-Tango/scripts"

# ─── AgentProgressView class template ───

PROGRESS_CLASS_QM = '''

# ---------------------------------------------------------------------------
# Agent Progress View (ported from Architect Bot for UI/UX parity)
# ---------------------------------------------------------------------------

class AgentProgressView:
    """Live processing indicator — typing + spinner + elapsed time + tool calls."""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: discord.Message):
        self.message = message
        self.progress_msg: Optional[discord.Message] = None
        self.tool_calls: list[str] = []
        self.current_status = ""
        self._start_time: Optional[float] = None
        self._spinner_idx = 0
        self._typing_task: Optional[asyncio.Task] = None
        self._spinner_task: Optional[asyncio.Task] = None
        self._last_edit = 0.0

    async def start(self, initial_text: str):
        self._start_time = time.time()
        embed = self._build_embed(initial_text)
        self.progress_msg = await self.message.reply(embed=embed)
        self.current_status = initial_text
        self._typing_task = asyncio.create_task(self._typing_loop())
        self._spinner_task = asyncio.create_task(self._spinner_loop())

    def _build_embed(self, status_text: str) -> discord.Embed:
        elapsed = time.time() - self._start_time if self._start_time else 0
        spinner = self.SPINNER_FRAMES[self._spinner_idx]
        embed = discord.Embed(
            title=f"{spinner} Quartermaster Working",
            description=status_text[:1900],
            color=COLOR_QUARTERMASTER,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Model: {CURRENT_MODEL} | Elapsed: {elapsed:.1f}s")
        if self.tool_calls:
            tools_text = "\\n".join(f"  • {tc}" for tc in self.tool_calls[-5:])
            embed.add_field(name="🛠 Tool Calls", value=tools_text, inline=False)
        return embed

    async def _typing_loop(self):
        try:
            while True:
                async with self.message.channel.typing():
                    await asyncio.sleep(8)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _spinner_loop(self):
        try:
            while True:
                await asyncio.sleep(1.5)
                self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)
                now = time.time()
                if now - self._last_edit >= 1.0 and self.progress_msg:
                    self._last_edit = now
                    embed = self._build_embed(self.current_status)
                    try:
                        await self.progress_msg.edit(embed=embed)
                    except discord.HTTPException:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def update(self, thinking: str | None = None, tool: str | None = None):
        if thinking:
            self.current_status = thinking
        if tool:
            self.tool_calls.append(tool)
        if not self.progress_msg:
            return
        self._last_edit = time.time()
        embed = self._build_embed(self.current_status)
        try:
            await self.progress_msg.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def _stop_background_tasks(self):
        for task in (self._typing_task, self._spinner_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._typing_task = None
        self._spinner_task = None

    async def cleanup(self):
        """Stop tasks and delete progress msg without sending a reply (for FLEET responses)."""
        await self._stop_background_tasks()
        if self.progress_msg:
            try:
                await self.progress_msg.delete()
            except discord.HTTPException:
                pass

    async def finalize(self, response: str):
        await self._stop_background_tasks()
        if self.progress_msg:
            try:
                await self.progress_msg.delete()
            except discord.HTTPException:
                pass
        if len(response) <= 1900:
            await self.message.reply(response)
        elif len(response) <= 4096:
            embed = discord.Embed(
                description=response[:4096],
                color=COLOR_QUARTERMASTER,
                timestamp=datetime.now(timezone.utc),
            )
            await self.message.reply(embed=embed)
        else:
            for chunk in _split_on_boundaries(response, 4096):
                embed = discord.Embed(
                    description=chunk,
                    color=COLOR_QUARTERMASTER,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.message.reply(embed=embed)
'''

PROGRESS_CLASS_CART = PROGRESS_CLASS_QM.replace("Quartermaster", "Cartographer").replace("COLOR_QUARTERMASTER", "COLOR_CARTOGRAPHER")


def patch_quartermaster():
    path = f"{SCRIPTS_DIR}/quartermaster-bot.py"
    with open(path, "r") as f:
        content = f.read()

    if "class AgentProgressView" in content:
        print(f"  {path}: already has AgentProgressView, applying chunk fix only")
        content = content.replace("max_chunk = 1900", "max_chunk = 1800")
        with open(path, "w") as f:
            f.write(content)
        return

    # 1. Add 'from typing import Optional' after datetime import
    content = content.replace(
        "from datetime import datetime, timezone\n",
        "from datetime import datetime, timezone\nfrom typing import Optional\n",
        1,
    )

    # 2. Add tool_descriptions import after fleet_protocol import
    content = content.replace(
        "    _split_on_boundaries,\n)\n",
        "    _split_on_boundaries,\n)\nfrom tool_descriptions import describe_tool_call, describe_tool_thinking\n",
        1,
    )

    # 3. Add COLOR_QUARTERMASTER after COLOR_ERROR
    content = content.replace(
        "COLOR_ERROR = 0xED4245\n",
        "COLOR_ERROR = 0xED4245\nCOLOR_QUARTERMASTER = 0xE67E22  # orange — Quartermaster's brand color\n",
        1,
    )

    # 4. Add AgentProgressView class before run_agent
    content = content.replace(
        "\nasync def run_agent(message: discord.Message, user_input: str,\n",
        PROGRESS_CLASS_QM + "\n\nasync def run_agent(message: discord.Message, user_input: str,\n",
        1,
    )

    # 5. Modify run_agent signature to accept progress parameter
    content = content.replace(
        "                    fleet_chain_id: str | None = None, fleet_turn: int = 0) -> str:",
        "                    fleet_chain_id: str | None = None, fleet_turn: int = 0,\n                    progress: 'AgentProgressView' = None) -> str:",
        1,
    )

    # 6. Add progress.update() call in tool execution loop
    content = content.replace(
        '            log(f"Tool call: {tool_name} with args: {str(tool_args)[:200]}", "INFO")\n\n            # Route tool call',
        '            log(f"Tool call: {tool_name} with args: {str(tool_args)[:200]}", "INFO")\n\n            if progress:\n                await progress.update(\n                    thinking=describe_tool_thinking(tool_name, tool_args),\n                    tool=describe_tool_call(tool_name, tool_args),\n                )\n\n            # Route tool call',
        1,
    )

    # 7. Modify FLEET delegation to use progress view
    content = content.replace(
        '                task = parsed["task"]\n                log(f"FLEET delegation from Schubert: {task[:200]}", "INFO")\n\n                # Process the task\n                response = await run_agent(message, task,\n                                           fleet_chain_id=parsed["chain_id"],\n                                           fleet_turn=parsed["turn"])',
        '                task = parsed["task"]\n                log(f"FLEET delegation from Schubert: {task[:200]}", "INFO")\n\n                # Start progress view\n                progress = AgentProgressView(message)\n                await progress.start(f"Working on: {task[:200]}")\n\n                # Process the task\n                response = await run_agent(message, task,\n                                           fleet_chain_id=parsed["chain_id"],\n                                           fleet_turn=parsed["turn"],\n                                           progress=progress)\n\n                await progress.cleanup()',
        1,
    )

    # 8. Modify direct message handler to use progress view
    content = content.replace(
        '    log(f"Direct request from {message.author.name}: {user_input[:200]}", "INFO")\n    response = await run_agent(message, user_input)\n    await message.reply(response[:2000] if len(response) > 2000 else response)',
        '    log(f"Direct request from {message.author.name}: {user_input[:200]}", "INFO")\n    progress = AgentProgressView(message)\n    await progress.start(f"Working on: {user_input[:200]}")\n    response = await run_agent(message, user_input, progress=progress)\n    await progress.finalize(response)',
        1,
    )

    # 9. Fix chunk size: 1900 -> 1800
    content = content.replace("max_chunk = 1900", "max_chunk = 1800")

    with open(path, "w") as f:
        f.write(content)
    print(f"  {path}: patched with AgentProgressView + chunk fix")


def patch_cartographer():
    path = f"{SCRIPTS_DIR}/cartographer-bot.py"
    with open(path, "r") as f:
        content = f.read()

    if "class AgentProgressView" in content:
        print(f"  {path}: already has AgentProgressView, applying chunk fix only")
        content = content.replace("max_chunk = 1900", "max_chunk = 1800")
        with open(path, "w") as f:
            f.write(content)
        return

    # 1. Add 'from typing import Optional' after datetime import
    content = content.replace(
        "from datetime import datetime, timezone\n",
        "from datetime import datetime, timezone\nfrom typing import Optional\n",
        1,
    )

    # 2. Add tool_descriptions import after fleet_protocol import
    content = content.replace(
        "    _split_on_boundaries,\n)\n",
        "    _split_on_boundaries,\n)\nfrom tool_descriptions import describe_tool_call, describe_tool_thinking\n",
        1,
    )

    # 3. Add COLOR_CARTOGRAPHER after COLOR_ERROR
    content = content.replace(
        "COLOR_ERROR = 0xED4245\n",
        "COLOR_ERROR = 0xED4245\nCOLOR_CARTOGRAPHER = 0x3498DB  # blue — Cartographer's brand color\n",
        1,
    )

    # 4. Add AgentProgressView class before run_agent
    content = content.replace(
        "\nasync def run_agent(message: discord.Message, user_input: str,\n",
        PROGRESS_CLASS_CART + "\n\nasync def run_agent(message: discord.Message, user_input: str,\n",
        1,
    )

    # 5. Modify run_agent signature to accept progress parameter
    content = content.replace(
        "                    fleet_chain_id: str | None = None, fleet_turn: int = 0) -> str:",
        "                    fleet_chain_id: str | None = None, fleet_turn: int = 0,\n                    progress: 'AgentProgressView' = None) -> str:",
        1,
    )

    # 6. Add progress.update() call in tool execution loop
    content = content.replace(
        '            log(f"Tool call: {tool_name} with args: {str(tool_args)[:200]}", "INFO")\n\n            # Route tool call',
        '            log(f"Tool call: {tool_name} with args: {str(tool_args)[:200]}", "INFO")\n\n            if progress:\n                await progress.update(\n                    thinking=describe_tool_thinking(tool_name, tool_args),\n                    tool=describe_tool_call(tool_name, tool_args),\n                )\n\n            # Route tool call',
        1,
    )

    # 7. Modify FLEET delegation to use progress view
    content = content.replace(
        '                task = parsed["task"]\n                log(f"FLEET delegation from Schubert: {task[:200]}", "INFO")\n\n                # Process the task\n                response = await run_agent(message, task,\n                                           fleet_chain_id=parsed["chain_id"],\n                                           fleet_turn=parsed["turn"])',
        '                task = parsed["task"]\n                log(f"FLEET delegation from Schubert: {task[:200]}", "INFO")\n\n                # Start progress view\n                progress = AgentProgressView(message)\n                await progress.start(f"Working on: {task[:200]}")\n\n                # Process the task\n                response = await run_agent(message, task,\n                                           fleet_chain_id=parsed["chain_id"],\n                                           fleet_turn=parsed["turn"],\n                                           progress=progress)\n\n                await progress.cleanup()',
        1,
    )

    # 8. Modify direct message handler to use progress view
    content = content.replace(
        '    log(f"Direct request from {message.author.name}: {user_input[:200]}", "INFO")\n    response = await run_agent(message, user_input)\n    await message.reply(response[:2000] if len(response) > 2000 else response)',
        '    log(f"Direct request from {message.author.name}: {user_input[:200]}", "INFO")\n    progress = AgentProgressView(message)\n    await progress.start(f"Working on: {user_input[:200]}")\n    response = await run_agent(message, user_input, progress=progress)\n    await progress.finalize(response)',
        1,
    )

    # 9. Fix chunk size: 1900 -> 1800
    content = content.replace("max_chunk = 1900", "max_chunk = 1800")

    with open(path, "w") as f:
        f.write(content)
    print(f"  {path}: patched with AgentProgressView + chunk fix")


def patch_architect():
    path = f"{SCRIPTS_DIR}/architect-bot.py"
    with open(path, "r") as f:
        content = f.read()

    # Fix chunk size: 1900 -> 1800 (was 3800, then 1900, still too large)
    if "max_chunk = 1900" in content:
        content = content.replace("max_chunk = 1900", "max_chunk = 1800")
        print(f"  {path}: fixed max_chunk 1900 -> 1800")
    elif "max_chunk = 3800" in content:
        content = content.replace("max_chunk = 3800", "max_chunk = 1800")
        print(f"  {path}: fixed max_chunk 3800 -> 1800")
    else:
        print(f"  {path}: max_chunk already at 1800 or not found")

    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    print("Applying comprehensive fleet UI/UX + chunk fix patch...")
    print()
    print("[1/3] Patching quartermaster-bot.py:")
    patch_quartermaster()
    print()
    print("[2/3] Patching cartographer-bot.py:")
    patch_cartographer()
    print()
    print("[3/3] Patching architect-bot.py:")
    patch_architect()
    print()
    print("All patches applied. Restart fleet services to apply.")
