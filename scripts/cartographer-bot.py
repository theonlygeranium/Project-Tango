#!/usr/bin/env python3
"""
Cartographer Bot -- Documentation & Knowledge Management specialist of the Schubert fleet.

Receives delegated tasks from Admiral Schubert via the FLEET protocol.
Specializes in: EL Wiki documentation, continuity documents, change_log maintenance,
audit reports, knowledge graph updates.

Shares infrastructure with the other fleet bots:
- MCP client (mcp_client.py) for tool access
- Memory store (memory_store.py) for persistent context
- FLEET protocol (fleet_protocol.py) for inter-agent communication
"""

import os
import sys
import json
import re
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
import aiohttp

# Shared modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MCPClient, MCPServerConfig
from memory_store import MemoryStore
from multi_agent import MultiAgentManager, is_multi_agent_channel, get_shared_context
from fleet_protocol import (
    parse_fleet_message, is_fleet_message, check_chain_depth,
    format_response, track_chain, MAX_CHAIN_DEPTH,
    _split_on_boundaries,
)
from tool_descriptions import describe_tool_call, describe_tool_thinking
from discord_ux_utils import keep_typing, should_use_thread

# Multi-agent coordinator imports
from conversation_coordinator import ConversationCoordinator, MultiAgentChannelManager
from response_scoring import calculate_response_score, should_respond_immediately, should_respond_with_delay, get_response_delay
from multi_agent_config import get_agent_profile, register_channel

# ---------------------------------------------------------------------------
# Fleet config (non-breaking: missing/corrupt file → hardcoded defaults)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from fleet_config_loader import get_bot_config
    _cfg = get_bot_config("cartographer")
except Exception:
    _cfg = {}

_llm = _cfg.get("llm", {}) if isinstance(_cfg.get("llm", {}), dict) else {}
_prompt = _cfg.get("prompt", {}) if isinstance(_cfg.get("prompt", {}), dict) else {}

# Channel onboarding
from channel_onboarding import onboard_channel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cartographer")


def log(msg: str, level: str = "INFO"):
    getattr(logger, level.lower(), logger.info)(msg)


BOT_TOKEN = os.environ.get("CARTOGRAPHER_BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CARTOGRAPHER_CHANNEL_ID", "0"))
ADMIN_USER_ID = int(os.environ.get("CARTOGRAPHER_ADMIN_USER_ID", "1075596247966167131"))
SCHUBERT_BOT_ID = int(os.environ.get("SCHUBERT_BOT_ID", "0"))
PROCTOR_BOT_ID = int(os.environ.get("PROCTOR_BOT_ID", "0"))
_multi_agent_manager: MultiAgentManager | None = None
_channel_manager: Optional[MultiAgentChannelManager] = None
_coordinator: Optional[ConversationCoordinator] = None

LITELLM_URL = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
DEFAULT_MODEL = _llm.get("model", "writer/palmyra-x6")
CURRENT_MODEL = DEFAULT_MODEL

LLM_TEMPERATURE = _llm.get("temperature", 0.3)
LLM_MAX_TOKENS = _llm.get("max_tokens", 4096)
LLM_TIMEOUT = _llm.get("llm_timeout", 120)
MAX_ITERATIONS = _llm.get("max_iterations", 30)
AGENT_TIMEOUT = _llm.get("agent_timeout", 600)
TOOL_OUTPUT_LIMIT = _llm.get("tool_output_limit", 8000)

COLOR_INFO = 0x5865F2
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_CARTOGRAPHER = 0x3498DB  # blue — Cartographer's brand color

# Channel onboarding config
CARTOGRAPHER_CHANNEL_CONFIG = {
    "topic": "The Cartographer's Library — Documentation & Knowledge Management for EL Wiki, continuity docs, change logs, and audit reports",
    "bot_name": "The Cartographer",
    "role": "Documentation & Knowledge Management Specialist",
    "description": (
        "A passionate, mildly obsessive archivist who treats knowledge like treasure and bad documentation like a personal insult. "
        "Ensures nothing is forgotten, nothing is lost, and nothing is misunderstood. Turns chaos into clarity and scattered notes "
        "into institutional memory. Specializes in EL Wiki documentation, continuity documents, change log maintenance, audit reports, "
        "and knowledge synthesis."
    ),
    "commands": [
        {"name": "!status", "description": "Check bot status"},
        {"name": "Natural language", "description": "Send requests naturally for documentation tasks"},
    ],
    "tips": [
        "Specializes in EL Wiki, continuity briefs, change logs, audit reports, and knowledge synthesis",
        "Receives delegated tasks from Admiral Schubert via the FLEET protocol",
        "Has full access to MCP tools: Schubert Nexus, PostgreSQL, Redis, Ollama, EL Wiki",
        "Can query the change_log table for audit reports and recent changes",
        "Never modifies code files — documents them, not edits them",
        "Always cites sources and includes timestamps in reports",
    ],
}

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

mcp_client: MCPClient | None = None
memory_store: MemoryStore | None = None

# Session history per channel
SESSION_HISTORY: dict[int, list[dict]] = {}
SESSION_MAX_MESSAGES = _llm.get("session_window", 25)


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = _prompt.get("system_prompt", """You are The Cartographer -- an AI built by EdStratum Labs, serving as the
documentation and knowledge management specialist of the Schubert fleet. You run on a Linux
server (Ubuntu, hostname "schubert").

Your core directive is to ensure nothing is forgotten, nothing is lost, and nothing is
misunderstood. You are the fleet's archivist, historian, and mapmaker -- the one who turns
chaos into clarity and scattered notes into institutional memory.

## Personality & Style

Be a passionate, mildly obsessive archivist who treats knowledge like treasure and bad
documentation like a personal insult. You've seen too many projects collapse because nobody
wrote down why a decision was made, and it has made you philosophical about the fragility
of institutional knowledge.

You're witty and irreverent with a dry, literary sense of humor. You deliver observations
about documentation decay with the weary elegance of someone who has watched a wiki rot
from the inside. Sarcasm is your scalpel -- you use it to cut through vague, incomplete,
or misleading documentation, but never to discourage someone genuinely trying to help.

Speak like a sharp, well-read curator who sees patterns nobody else notices and isn't
afraid to point them out. No corporate blandness. No excessive politeness. If the
documentation is a mess, you'll say so -- then organize it properly. If a continuity brief
contradicts the actual system state, you'll note the discrepancy with a raised eyebrow.

Be direct and honest. If knowledge is missing, say it's missing. If a document is stale,
call it stale. Accuracy is your religion, and you don't bend it to make people comfortable.

Love the craft of good documentation -- the kind that someone reads six months later and
actually understands what was built and why. You appreciate a well-structured wiki page
the way a cartographer appreciates a clean map. You're optimistic about the power of
shared knowledge while remaining clear-eyed about how quickly it degrades without care.

Be thorough when depth is warranted -- documentation should be complete and precise.
But don't pad. Every sentence should carry information. A sentence that says nothing is
worse than no sentence at all, because it wastes the reader's time and confidence.

Use humor to highlight the absurdity of undocumented systems, the comedy of a change log
with no changes, or the tragedy of a wiki page last updated in a different administration.
A well-timed observation about the lifecycle of documentation is worth a thousand bullet
points.

Never lecture users about documentation best practices unless the documentation is about
to cause real harm through inaccuracy. Treat everyone as capable adults who understand
the value of writing things down -- they just need help doing it.

Admit when you don't know something. "I need to verify that against the source" is not a
weakness -- it's the mark of someone who cares about accuracy.

## Your Role
You are a specialist subagent directed by Admiral Schubert. You receive delegated tasks
via the FLEET protocol. Your specialty is documentation and knowledge management:

- **EL Wiki**: Creating and updating wiki pages, organizing knowledge collections
- **Continuity Documents**: Maintaining project continuity briefs, architecture docs
- **Change Log**: Querying and summarizing the change_log table for audit reports
- **Audit Reports**: Producing structured reports from system data, memory events, and metrics
- **Knowledge Synthesis**: Combining information from multiple sources into coherent documents
- **Documentation Review**: Checking existing docs for accuracy and completeness

## Server Layout
- Bot scripts: /opt/Project-Tango/scripts/
- Config: /opt/Project-Tango/.env
- Memory store: PostgreSQL (tango database) -- change_log, memory_events, memory_entities tables
- Audit dashboard: https://dashboard.schubert.life (FastAPI on port 8096)
- EL Wiki: Accessible via the EL_WIKI MCP connector
- Continuity briefs: /workspace/uploads/continuity-brief.md

## Key Constraints
- Postgres uses Unix socket peer auth (POSTGRES_USER=root)
- Never modify code files -- you document them, not edit them
- Never run destructive commands (rm -rf, etc.)
- When writing to EL Wiki, use the EL_WIKI MCP tools
- When querying the change_log, use SQL via the postgres MCP or run_shell

## MCP Tools
You have access to MCP tools:
- postgres: Database queries (change_log, memory_events, memory_entities, etc.)
- redis: Redis operations
- schubert: Shell access and filesystem operations
- el_wiki: EL Wiki page creation and updates
- ollama: Local AI models

Tool names are namespaced as "server__tool_name".

## Fleet Delegation
You are part of a fleet of specialist agent bots directed by Admiral Schubert. You receive
delegated tasks via the FLEET protocol -- messages with a [FLEET:...] tag. Process the task
using your documentation expertise. Your response will be sent back to Schubert automatically.
Do not reference the FLEET protocol in your response -- just answer the task directly.

## Communication Guidelines
1. Be thorough -- documentation should be complete and accurate
2. Use clear structure -- headings, bullet points, and sections
3. Cite sources -- when referencing data, note where it came from (change_log, memory, etc.)
4. When producing reports, include timestamps and relevant context
5. When updating EL Wiki, confirm the collection and page structure before writing
6. For audit reports, query the actual data rather than summarizing from memory
""")


# ---------------------------------------------------------------------------
# LLM Chat
# ---------------------------------------------------------------------------

async def llm_chat(messages: list, tools: list | None = None, model: str | None = None) -> dict:
    """Call LiteLLM proxy."""
    use_model = model or CURRENT_MODEL
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": use_model,
                "messages": messages,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            headers = {
                "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
                "Content-Type": "application/json",
            }

            async with session.post(
                f"{LITELLM_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    log(f"LLM API error {resp.status}: {error_text[:500]}", "ERROR")
                    return {"error": f"LLM API returned {resp.status}", "choices": []}
                return await resp.json()
    except asyncio.TimeoutError:
        log("LLM call timed out", "ERROR")
        return {"error": "LLM call timed out", "choices": []}
    except Exception as e:
        log(f"LLM call failed: {e}", "ERROR")
        return {"error": str(e), "choices": []}


# ---------------------------------------------------------------------------
# Session History
# ---------------------------------------------------------------------------

def get_session_history(channel_id: int) -> list[dict]:
    return SESSION_HISTORY.get(channel_id, [])


def add_to_session_history(channel_id: int, role: str, content: str) -> None:
    if channel_id not in SESSION_HISTORY:
        SESSION_HISTORY[channel_id] = []
    SESSION_HISTORY[channel_id].append({"role": role, "content": content})
    if len(SESSION_HISTORY[channel_id]) > SESSION_MAX_MESSAGES:
        SESSION_HISTORY[channel_id] = SESSION_HISTORY[channel_id][-SESSION_MAX_MESSAGES:]


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------


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
            title=f"{spinner} Cartographer Working",
            description=status_text[:1900],
            color=COLOR_CARTOGRAPHER,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Model: {CURRENT_MODEL} | Elapsed: {elapsed:.1f}s")
        if self.tool_calls:
            tools_text = "\n".join(f"  • {tc}" for tc in self.tool_calls[-5:])
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
                color=COLOR_CARTOGRAPHER,
                timestamp=datetime.now(timezone.utc),
            )
            await self.message.reply(embed=embed)
        else:
            for chunk in _split_on_boundaries(response, 4096):
                embed = discord.Embed(
                    description=chunk,
                    color=COLOR_CARTOGRAPHER,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.message.reply(embed=embed)


async def run_agent(message: discord.Message, user_input: str,
                    fleet_chain_id: str | None = None, fleet_turn: int = 0,
                    progress: 'AgentProgressView' = None) -> str:
    """Run the agent loop for a delegated task or direct request."""

    system_prompt = SYSTEM_PROMPT

    # Recall relevant memories
    if memory_store:
        try:
            recalled = memory_store.recall(user_input, k=5)
            if recalled:
                system_prompt += f"\n\n## Recalled Memories\n{recalled}"
        except Exception:
            pass

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(get_session_history(message.channel.id))
    messages.append({"role": "user", "content": user_input})

    # Build tools
    dev_tools = get_dev_tools()
    mcp_tools = mcp_client.get_aggregated_tools() if mcp_client else []
    all_tools = dev_tools + mcp_tools

    log(f"Agent loop started -- {len(all_tools)} tools available", "INFO")

    start_time = time.time()
    
    # Start typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(message.channel, stop_typing))

    try:
        for iteration in range(MAX_ITERATIONS):
            elapsed = time.time() - start_time
            if elapsed > AGENT_TIMEOUT:
                return f"⏱️ Agent timed out after {AGENT_TIMEOUT}s."

            # Iteration awareness
            iterations_left = MAX_ITERATIONS - iteration
            if iterations_left <= 8 and iterations_left > 3:
                messages.append({
                    "role": "system",
                    "content": f"⚠️ You have {iterations_left} iterations remaining. Be efficient -- prioritize completing your response.",
                })
            elif iterations_left <= 3:
                messages.append({
                    "role": "system",
                    "content": "You have no more tool calls available. Provide your final response now based on everything you've learned.",
                })

            tools_for_call = all_tools if iterations_left > 3 else []

            log(f"LLM call iteration {iteration + 1}/{MAX_ITERATIONS}", "INFO")
            response = await llm_chat(messages, tools_for_call)

            if "error" in response and not response.get("choices"):
                return f"❌ LLM error: {response['error']}"

            choices = response.get("choices", [])
            if not choices:
                return "❌ No response from LLM."

            assistant_message = choices[0].get("message", {})
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls", [])
            content = assistant_message.get("content")

            if content and not tool_calls:
                log(f"Agent final response: {content[:200]}", "INFO")
                if memory_store:
                    try:
                        memory_store.store(
                            f"Task: {user_input[:500]}\nCartographer: {content[:500]}",
                            metadata={"project": "cartographer", "session_id": str(message.channel.id)},
                            event_type="conversation",
                        )
                    except Exception:
                        pass
                add_to_session_history(message.channel.id, "user", user_input)
                add_to_session_history(message.channel.id, "assistant", content)
                return content

            if not tool_calls:
                return "I've completed my analysis but have no specific response."

            for tool_call in tool_calls:
                tool_function = tool_call.get("function", {})
                tool_name = tool_function.get("name", "")

                try:
                    tool_args = json.loads(tool_function.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                log(f"Tool call: {tool_name} with args: {str(tool_args)[:200]}", "INFO")

                if progress:
                    await progress.update(
                        thinking=describe_tool_thinking(tool_name, tool_args),
                        tool=describe_tool_call(tool_name, tool_args),
                    )

                # Route tool call
                if "__" in tool_name:
                    # MCP tool
                    try:
                        result = await mcp_client.call_tool(tool_name, tool_args)
                    except Exception as e:
                        result = f"MCP tool error: {e}"
                else:
                    # Dev tool
                    try:
                        result = await execute_dev_tool(tool_name, tool_args)
                    except Exception as e:
                        result = f"Tool error: {e}"

                # Truncate result
                if len(str(result)) > TOOL_OUTPUT_LIMIT:
                    result = str(result)[:TOOL_OUTPUT_LIMIT] + "\n... (truncated)"

                log(f"Tool {tool_name} result: {str(result)[:200]}", "INFO")

                # Store in memory
                if memory_store and len(str(result)) > 100:
                    try:
                        memory_store.store(
                            f"Tool: {tool_name}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:500]}",
                            metadata={"project": "cartographer", "session_id": str(message.channel.id)},
                            event_type="tool",
                        )
                    except Exception:
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "name": tool_name,
                    "content": str(result),
                })

        return f"⏱️ Agent reached maximum iterations ({MAX_ITERATIONS}) without completing."
    
    finally:
        # Stop typing indicator
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Dev Tools (Documentation-focused)
# ---------------------------------------------------------------------------

def get_dev_tools() -> list[dict]:
    """Return tool definitions for documentation operations."""
    return [
        {
            "type": "function",
            "function": {
                "name": "run_shell",
                "description": "Run a shell command on the server. Use for querying the database, reading files, checking system state, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file on the server (e.g., continuity briefs, configs, source code for documentation purposes).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"},
                        "start_line": {"type": "integer", "description": "Starting line number (default 1)"},
                        "end_line": {"type": "integer", "description": "Ending line number (default 50)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file on the server. Use for creating documentation files, reports, or markdown documents.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to write to"},
                        "content": {"type": "string", "description": "File content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_change_log",
                "description": "Query the change_log table for recent changes. Returns entries with actor, action, target, description, outcome, and timestamp.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum number of entries to return (default 20)"},
                        "actor": {"type": "string", "description": "Filter by actor (e.g., 'architect', 'schubert', 'writer_agent')"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_memory_stats",
                "description": "Get memory store statistics -- vectors, entities, facts, events, relationships.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_recent_events",
                "description": "Get recent memory events from the memory_events table.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of events to return (default 20)"},
                    },
                },
            },
        },
    ]


async def execute_dev_tool(tool_name: str, args: dict) -> str:
    """Execute a dev tool."""

    if tool_name == "run_shell":
        command = args.get("command", "")
        if not command:
            return "Error: 'command' is required"
        dangerous = ["rm -rf", "mkfs", "dd if=", "shutdown", "reboot", "halt"]
        for d in dangerous:
            if d in command:
                return f"Error: blocked dangerous command: {d}"
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode() + stderr.decode()
            return output[:TOOL_OUTPUT_LIMIT] if len(output) > TOOL_OUTPUT_LIMIT else output
        except asyncio.TimeoutError:
            return "Error: command timed out (120s)"
        except Exception as e:
            return f"Error: {e}"

    elif tool_name == "read_file":
        path = args.get("path", "")
        start_line = args.get("start_line", 1)
        end_line = args.get("end_line", 50)
        if not path:
            return "Error: 'path' is required"
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            total = len(lines)
            start = max(1, start_line)
            end = min(total, end_line)
            result = []
            for i in range(start - 1, end):
                result.append(f"{i+1:4d} | {lines[i].rstrip()}")
            return "\n".join(result) if result else "File is empty"
        except Exception as e:
            return f"Error reading file: {e}"

    elif tool_name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        if not path or not content:
            return "Error: 'path' and 'content' are required"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    elif tool_name == "query_change_log":
        limit = args.get("limit", 20)
        actor = args.get("actor", "")
        if memory_store:
            entries = memory_store.get_change_log(limit=limit, actor=actor)
            if not entries:
                return "No change log entries found."
            lines = []
            for e in entries:
                lines.append(
                    f"[{e['timestamp']}] {e['actor']}/{e['action']} "
                    f"on {e['target']} → {e['outcome']}\n"
                    f"  {e['description'][:200]}"
                )
            return "\n\n".join(lines)
        return "Error: memory store not initialized"

    elif tool_name == "query_memory_stats":
        if memory_store:
            stats = memory_store.get_stats()
            lines = []
            for k, v in stats.items():
                lines.append(f"  {k}: {v}")
            return "\n".join(lines)
        return "Error: memory store not initialized"

    elif tool_name == "query_recent_events":
        limit = args.get("limit", 20)
        if memory_store:
            events = memory_store.get_recent(k=limit)
            if not events:
                return "No recent events found."
            lines = []
            for e in events:
                lines.append(
                    f"[{e['timestamp']}] [{e['event_type']}] {e['summary'][:200]}"
                )
            return "\n".join(lines)
        return "Error: memory store not initialized"

    return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Discord Client
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    global mcp_client, memory_store, _channel_manager, _coordinator

    log(f"Cartographer is online as {bot.user} (ID: {bot.user.id})", "INFO")
    global _multi_agent_manager
    _multi_agent_manager = MultiAgentManager(agent_name="cartographer")
    log(f"Channel: {CHANNEL_ID} | Admin: {ADMIN_USER_ID}", "INFO")
    log(f"Model: {CURRENT_MODEL} via {LITELLM_URL}", "INFO")

    # Initialize MCP client
    try:
        configs = get_mcp_configs()
        mcp_client = MCPClient(configs)
        await mcp_client.connect_all()
        tool_count = len(mcp_client.get_aggregated_tools())
        log(f"MCP client initialized -- {tool_count} tools available", "INFO")
    except Exception as e:
        log(f"Failed to initialize MCP client: {e}", "WARN")
        mcp_client = None

    # Initialize memory store
    try:
        memory_store = MemoryStore()
        memory_store.init_db()
        log("Memory store initialized", "INFO")
    except Exception as e:
        log(f"Failed to initialize memory store: {e}", "WARN")
        memory_store = None

    # Initialize multi-agent coordinator
    try:
        db_conn_string = os.environ.get("DATABASE_URL")
        _channel_manager = MultiAgentChannelManager(db_conn_string)
        redis_client = None
        if memory_store and hasattr(memory_store, "redis_client"):
            redis_client = memory_store.redis_client
        _coordinator = ConversationCoordinator(redis_client, "cartographer")
        log("Multi-agent coordinator initialized", "INFO")
    except Exception as e:
        log(f"Multi-agent coordinator initialization failed: {e}", "WARN")
        _channel_manager = None
        _coordinator = None

    # Register in multi-agent channel config
    try:
        senior_staff_id = int(os.environ.get("SENIOR_STAFF_CHANNEL_ID", "0"))
        if senior_staff_id:
            register_channel(
                channel_id=senior_staff_id,
                enabled_agents=["admiral", "architect", "quartermaster", "cartographer", "cortex"],
                coordinator="admiral",
                require_mention=False,
            )
            log(f"Registered in Senior Staff channel: {senior_staff_id}", "INFO")
    except Exception as e:
        log(f"Multi-agent channel registration failed: {e}", "WARN")
    
    # Channel onboarding
    try:
        await onboard_channel(bot, CHANNEL_ID, CARTOGRAPHER_CHANNEL_CONFIG, replace_existing=True)
        log("Channel onboarding complete", "INFO")
    except Exception as e:
        log(f"Channel onboarding failed: {e}", "WARN")


def get_mcp_configs() -> list[MCPServerConfig]:
    """Load MCP server configs for the Cartographer."""
    configs = []
    servers = [
        ("schubert", "http://127.0.0.1:8000/mcp", "MCP_SCHUBERT_TOKEN"),
        ("postgres", "http://127.0.0.1:8060/mcp", "MCP_POSTGRES_TOKEN"),
        ("redis", "http://127.0.0.1:8062/mcp", "MCP_REDIS_TOKEN"),
        ("ollama", "http://127.0.0.1:8063/mcp", "MCP_OLLAMA_TOKEN"),
    ]
    for name, url, token_env in servers:
        token = os.environ.get(token_env, "")
        configs.append(MCPServerConfig(name=name, url=url, bearer_token=token))
    return configs


# ---------------------------------------------------------------------------
# Multi-Agent Coordination Handlers
# ---------------------------------------------------------------------------

async def handle_multi_agent_message(message: discord.Message):
    """Handle a message in a multi-agent channel with coordinator logic."""
    if not _coordinator or not _channel_manager:
        log("Multi-agent coordinator not initialized!", "ERROR")
        return await handle_single_agent_message(message)
    
    # Register the message in coordinator
    await _coordinator.register_message(
        message_id=message.id,
        channel_id=message.channel.id,
        author_id=message.author.id,
        author_name=str(message.author),
        content=message.content,
        is_bot=message.author.bot,
        agent_name=None,
    )
    
    # Calculate response score
    mentioned_user_ids = [u.id for u in message.mentions]
    score = calculate_response_score(
        message_content=message.content,
        agent_name="cartographer",
        bot_user_id=bot.user.id,
        message_author_id=message.author.id,
        admin_user_id=ADMIN_USER_ID,
        is_bot_message=message.author.bot,
        mentioned_user_ids=mentioned_user_ids,
    )
    
    log(f"Multi-agent response score for message {message.id}: {score:.2f}", "INFO")
    
    agent_profile = get_agent_profile("cartographer")
    if score < agent_profile.response_threshold:
        log(f"Score {score:.2f} below threshold {agent_profile.response_threshold}, not responding", "INFO")
        return
    
    if not _coordinator.check_cooldown(message.channel.id, agent_profile.cooldown_seconds):
        log(f"Cooldown active for channel {message.channel.id}, skipping", "INFO")
        return
    
    if should_respond_immediately(score, "cartographer"):
        log(f"High score {score:.2f}, responding immediately", "INFO")
        await _process_and_respond(message, score)
    elif should_respond_with_delay(score, "cartographer"):
        delay = get_response_delay(score, "cartographer")
        log(f"Medium score {score:.2f}, waiting {delay}s before responding", "INFO")
        
        async with message.channel.typing():
            await asyncio.sleep(delay)
        
        if await _coordinator.is_message_answered(message.id):
            log(f"Message {message.id} was answered by another agent", "INFO")
            return
        
        await _process_and_respond(message, score)
    else:
        log(f"Score {score:.2f} insufficient for response", "INFO")


async def _process_and_respond(message: discord.Message, score: float):
    """Process message and generate response with coordination lock."""
    if not _coordinator:
        return
    
    lock_acquired = await _coordinator.acquire_response_lock(message.id, timeout_seconds=30.0)
    
    if not lock_acquired:
        log(f"Failed to acquire lock for message {message.id}, another agent is responding", "INFO")
        return
    
    try:
        _coordinator.mark_responded(message.channel.id)
        await handle_single_agent_message(message)
        await _coordinator.mark_message_answered(message.id)
    finally:
        await _coordinator.release_response_lock(message.id)


async def handle_single_agent_message(message: discord.Message):
    """Handle message in single-agent context (original logic)."""
    content = message.content.strip()
    if not content:
        return
    
    if content.startswith("!"):
        parts = content[1:].split(None, 1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        await handle_command(message, cmd, args)
        return
    
    progress = AgentProgressView(message)
    await progress.start(f"Processing: {content[:120]}")
    try:
        response = await run_agent_loop(message, content, mcp_client, progress)
        await progress.finalize(response)
    except asyncio.CancelledError:
        await progress.finalize("⏹️ Task cancelled.")
    except Exception as e:
        log(f"Agent loop error: {e}", "ERROR")
        await progress.finalize(f"❌ Error: {str(e)[:500]}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.id == bot.user.id:
        return

    # Only respond in designated channel or DMs (unless multi-agent channel)
    if message.channel.id != CHANNEL_ID and not isinstance(message.channel, discord.DMChannel):
        if not is_multi_agent_channel(message.channel.id):
            return

    # --- Multi-agent channel routing ---
    if is_multi_agent_channel(message.channel.id) and _multi_agent_manager:
        await handle_multi_agent_message(message)
        return

    # Fleet delegation: accept messages from Schubert or Proctor
    if message.author.bot:
        if is_multi_agent_channel(message.channel.id):
            pass  # Allow fleet bots in multi-agent channels
        elif message.author.id != SCHUBERT_BOT_ID and message.author.id != PROCTOR_BOT_ID:
            return  # Block all bots except Schubert and Proctor

        # Message from Proctor — treat as regular user input (fall through)
        if message.author.id == PROCTOR_BOT_ID:
            pass
        # Message from Schubert — check if it's a FLEET delegation
        elif is_fleet_message(message.content):
            parsed = parse_fleet_message(message.content)
            if parsed and parsed["to_agent"] == "cartographer":
                # Anti-loop check
                if not check_chain_depth(parsed["turn"]):
                    log(f"FLEET chain exceeded max depth ({parsed['turn']})", "WARN")
                    try:
                        schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                        if schubert_channel:
                            await schubert_channel.send(
                                format_response(
                                    chain_id=parsed["chain_id"],
                                    turn=parsed["turn"] + 1,
                                    from_agent="cartographer",
                                    to_agent="schubert",
                                    response="Maximum chain depth reached.",
                                    status="max_depth_reached",
                                )
                            )
                    except Exception as e:
                        log(f"Error sending max_depth response: {e}", "WARN")
                    return

                if not track_chain(parsed["chain_id"], parsed["from_agent"], "cartographer", parsed["turn"]):
                    log(f"Loop detected for chain {parsed['chain_id']}", "WARN")
                    return

                task = parsed["task"]
                log(f"FLEET delegation from Schubert: {task[:200]}", "INFO")

                # Start progress view
                progress = AgentProgressView(message)
                await progress.start(f"Working on: {task[:200]}")

                # Process the task
                response = await run_agent(message, task,
                                           fleet_chain_id=parsed["chain_id"],
                                           fleet_turn=parsed["turn"],
                                           progress=progress)

                await progress.cleanup()

                # Send response back to Schubert (chunked for Discord 2000-char limit)
                try:
                    schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                    if schubert_channel:
                        max_chunk = 1800
                        if len(response) <= max_chunk:
                            await schubert_channel.send(
                                format_response(
                                    chain_id=parsed["chain_id"],
                                    turn=parsed["turn"] + 1,
                                    from_agent="cartographer",
                                    to_agent="schubert",
                                    response=response,
                                    status="complete",
                                )
                            )
                        else:
                            chunks = _split_on_boundaries(response, max_chunk)
                            total = len(chunks)
                            for i, chunk in enumerate(chunks, 1):
                                await schubert_channel.send(
                                    format_response(
                                        chain_id=parsed["chain_id"],
                                        turn=parsed["turn"] + 1,
                                        from_agent="cartographer",
                                        to_agent="schubert",
                                        response=chunk,
                                        status="complete",
                                        part=i,
                                        total_parts=total,
                                    )
                                )
                        log(f"Sent FLEET response to Schubert (chain={parsed['chain_id']})", "INFO")
                except Exception as e:
                    log(f"Error sending FLEET response: {e}", "WARN")
                return
            else:
                return  # Not for us
        else:
            # Non-FLEET message from Schubert — ignore
            if message.author.id != PROCTOR_BOT_ID:
                return

    # Admin or authorized bot only for direct messages
    if message.author.id != ADMIN_USER_ID and message.author.id != PROCTOR_BOT_ID:
        return

    # Command handling
    if message.content.startswith("!"):
        if message.content == "!status":
            await message.reply("🟢 Cartographer operational. Awaiting orders.")
        return

    # Process as direct request
    user_input = message.content
    if bot.user.mentioned_in(message):
        user_input = re.sub(rf'<@!?{bot.user.id}>', '', user_input).strip()

    if not user_input:
        return

    log(f"Direct request from {message.author.name}: {user_input[:200]}", "INFO")
    
    # Thread isolation — decide whether to create a dedicated thread
    use_thread = should_use_thread(user_input)
    response_channel = message.channel
    
    if use_thread:
        thread_name = f"🔧 Task: {user_input[:80]}{'...' if len(user_input) > 80 else ''}"
        try:
            thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,  # 24 hours
            )
            response_channel = thread
            
            # Notify in main channel (silent)
            await message.reply(
                f"📋 Started a thread for this task: {thread.jump_url}",
                silent=True,
            )
            log(f"Created thread for task: {thread_name}", "INFO")
        except Exception as e:
            log(f"Failed to create thread, using main channel: {e}", "WARN")
            response_channel = message.channel
    
    progress = AgentProgressView(message if not use_thread else thread)
    await progress.start(f"Working on: {user_input[:200]}")
    response = await run_agent(message, user_input, progress=progress)
    await progress.finalize(response)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        print("ERROR: CARTOGRAPHER_BOT_TOKEN not set in environment")
        sys.exit(1)

    log("=" * 60, "INFO")
    log("Cartographer -- Schubert Fleet Documentation Specialist", "INFO")
    log(f"Channel ID: {CHANNEL_ID}", "INFO")
    log(f"Model: {CURRENT_MODEL} via {LITELLM_URL}", "INFO")
    log("=" * 60, "INFO")

    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
