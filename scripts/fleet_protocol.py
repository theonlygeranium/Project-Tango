"""
FLEET Protocol — Inter-agent delegation messaging for the Schubert fleet.

Provides tag parsing, chain tracking, and anti-loop protection for bot-to-bot
communication via Discord channels.

Message format:
    [FLEET:chain=<uuid>:turn=1:from=schubert:to=architect]
    Task: Review the memory_store.py schema and recommend changes.
    Context: We're seeing slow entity lookups at scale.

Response format:
    [FLEET:chain=<uuid>:turn=2:from=architect:to=schubert:status=complete]
    I reviewed the schema. Recommendation: add a B-tree index on memory_entities(name).
"""

import re
import uuid
import time
import logging
import asyncio
import os
import sys
import discord

# ---------------------------------------------------------------------------
# Fleet config (non-breaking: missing/corrupt file → hardcoded defaults)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from fleet_config_loader import get_fleet_config
    _fleet = get_fleet_config()
except Exception:
    _fleet = {}

_fleet_protocol = _fleet.get("fleet_protocol", {}) if isinstance(_fleet.get("fleet_protocol", {}), dict) else {}

logger = logging.getLogger("fleet")

MAX_CHAIN_DEPTH = _fleet_protocol.get("max_chain_depth", 3)
DELEGATION_TIMEOUT = _fleet_protocol.get("delegation_timeout", 300)

# Tag regex: [FLEET:chain=<uuid>:turn=<int>:from=<name>:to=<name>[:status=<status>]]
FLEET_TAG_RE = re.compile(
    r"\[FLEET:chain=([a-f0-9-]+):turn=(\d+):from=(\w+):to=(\w+)(?::status=(\w+))?(?::part=(\d+)/(\d+))?\]"
)


def create_delegation_message(
    chain_id: str | None,
    turn: int,
    from_agent: str,
    to_agent: str,
    task: str,
    status: str = "",
) -> str:
    """
    Construct a FLEET-tagged message for delegation.

    Args:
        chain_id: UUID for the delegation chain. If None, a new one is generated.
        turn: The turn number in the chain (1 = first delegation).
        from_agent: Name of the sending agent (e.g., "schubert").
        to_agent: Name of the receiving agent (e.g., "architect").
        task: The task text to send.
        status: Optional status tag (e.g., "complete", "max_depth_reached").

    Returns:
        The full tagged message string.
    """
    if chain_id is None:
        chain_id = str(uuid.uuid4())

    status_part = f":status={status}" if status else ""
    tag = f"[FLEET:chain={chain_id}:turn={turn}:from={from_agent}:to={to_agent}{status_part}]"

    return f"{tag}\n{task}"


def parse_fleet_message(content: str) -> dict | None:
    """
    Parse a FLEET-tagged message.

    Returns a dict with keys: chain_id, turn, from_agent, to_agent, status, task.
    Returns None if the message does not contain a valid FLEET tag.
    """
    match = FLEET_TAG_RE.search(content)
    if not match:
        return None

    chain_id = match.group(1)
    turn = int(match.group(2))
    from_agent = match.group(3)
    to_agent = match.group(4)
    status = match.group(5) or ""
    part = int(match.group(6)) if match.group(6) else 0
    total_parts = int(match.group(7)) if match.group(7) else 0

    # Extract task text (everything after the tag line)
    tag_end = match.end()
    # Skip newline after tag
    remaining = content[tag_end:].lstrip("\n").strip()
    task = remaining

    return {
        "chain_id": chain_id,
        "turn": turn,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "status": status,
        "task": task,
        "part": part,
        "total_parts": total_parts,
    }


def is_fleet_message(content: str) -> bool:
    """Check if a message contains a FLEET tag."""
    return FLEET_TAG_RE.search(content) is not None


def is_delegation_for(content: str, agent_name: str) -> bool:
    """Check if a FLEET message is directed at the given agent."""
    parsed = parse_fleet_message(content)
    if parsed is None:
        return False
    return parsed["to_agent"] == agent_name


def is_response_to(content: str, agent_name: str) -> bool:
    """Check if a FLEET message is a response directed at the given agent."""
    parsed = parse_fleet_message(content)
    if parsed is None:
        return False
    return parsed["to_agent"] == agent_name and parsed["status"] != ""


def check_chain_depth(turn: int) -> bool:
    """
    Check if the chain depth is within limits.
    Returns True if the turn is acceptable, False if it exceeds MAX_CHAIN_DEPTH.
    """
    return turn <= MAX_CHAIN_DEPTH


def generate_chain_id() -> str:
    """Generate a new chain UUID."""
    return str(uuid.uuid4())


# In-process chain tracking for anti-loop (per-bot, not shared across processes)
_seen_chains: dict[str, list[dict]] = {}


def track_chain(chain_id: str, from_agent: str, to_agent: str, turn: int) -> bool:
    """
    Track a chain to detect loops. Returns True if this is a new/valid chain
    interaction, False if it's a detected loop (same chain already seen from
    the same agent at the same or lower turn).

    This is a soft check — the turn counter is the hard limit.
    """
    key = f"{chain_id}:{from_agent}:{to_agent}"
    now = time.time()

    # Clean old chains (older than 5 minutes)
    for k in list(_seen_chains.keys()):
        entries = _seen_chains[k]
        if entries and now - entries[-1]["time"] > 300:
            del _seen_chains[k]

    if key in _seen_chains:
        # Already seen — check if this is a duplicate
        entries = _seen_chains[key]
        is_loop = False
        for entry in entries:
            if entry["turn"] >= turn:
                logger.warning(
                    f"Loop detected: chain {chain_id} from {from_agent} to {to_agent} "
                    f"at turn {turn} (already seen at turn {entry['turn']})"
                )
                is_loop = True
        if is_loop:
            return False
        entries.append({"turn": turn, "time": now})
    else:
        _seen_chains[key] = [{"turn": turn, "time": now}]

    return True


def format_response(
    chain_id: str,
    turn: int,
    from_agent: str,
    to_agent: str,
    response: str,
    status: str = "complete",
    part: int = 0,
    total_parts: int = 0,
) -> str:
    """
    Format a response message from a subagent back to the director.
    Supports multi-part responses via part=N/M fields.
    """
    tag = f"[FLEET:chain={chain_id}:turn={turn}:from={from_agent}:to={to_agent}:status={status}"
    if total_parts > 0:
        tag += f":part={part}/{total_parts}"
    tag += "]"
    return f"{tag}\n{response}"


def _split_on_boundaries(text: str, max_len: int = 1900) -> list[str]:
    """Split text into chunks no longer than max_len, preferring line boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        # Try to split on newline
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at > max_len // 2:
            chunks.append(remaining[:split_at + 1])
            remaining = remaining[split_at + 1:]
        else:
            # Try to split on space
            split_at = remaining.rfind(" ", 0, max_len)
            if split_at > max_len // 2:
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at + 1:]
            else:
                # Hard split
                chunks.append(remaining[:max_len])
                remaining = remaining[max_len:]
    return [c for c in chunks if c.strip()]

# ---------------------------------------------------------------------------
# Streaming Message -- Typewriter-style output via incremental message edits
# ---------------------------------------------------------------------------

class StreamingMessage:
    """Manages incremental message editing for typewriter-style output.

    Sends a placeholder message and edits it as tokens arrive, creating
    a live 'typing' animation. Respects Discord rate limits by throttling
    edits to ~2s intervals. Uses embeds for long responses to avoid
    Discord's 2000-char message content limit.
    """

    EDIT_INTERVAL = 2.0
    FIRST_SEND_THRESHOLD = 30
    MAX_LENGTH = 2000
    EMBED_MAX = 4096

    def __init__(self, message):
        self._message_ref = message
        self._stream_msg = None
        self._buffer = ""
        self._last_edit = 0.0
        self._finalized = False
        self._started = False

    async def append(self, delta):
        """Append text and flush if throttle interval has elapsed."""
        if self._finalized:
            return
        self._buffer += delta

        if self._stream_msg is None:
            if len(self._buffer) < self.FIRST_SEND_THRESHOLD:
                return
            self._stream_msg = await self._message_ref.reply(
                self._buffer[:self.MAX_LENGTH]
            )
            self._last_edit = time.monotonic()
            self._started = True
            return

        now = time.monotonic()
        if now - self._last_edit < self.EDIT_INTERVAL:
            return

        if len(self._buffer) > self.MAX_LENGTH:
            try:
                preview = self._buffer[:self.MAX_LENGTH - 20] + "\n\n⏳ *streaming...*"
                await self._stream_msg.edit(content=preview)
            except Exception:
                pass
            self._last_edit = now
            return

        try:
            await self._stream_msg.edit(content=self._buffer[:self.MAX_LENGTH])
        except Exception:
            pass
        self._last_edit = now

    async def cancel(self):
        """Delete the streaming message if one was created."""
        if self._stream_msg:
            try:
                await self._stream_msg.delete()
            except Exception:
                pass
        self._stream_msg = None
        self._buffer = ""
        self._finalized = True

    async def finalize(self, final_text=None):
        """Send the final edit with the complete response."""
        if self._finalized:
            return
        self._finalized = True
        content = final_text if final_text is not None else self._buffer

        if not content:
            return

        if self._stream_msg:
            if len(content) <= self.MAX_LENGTH:
                try:
                    await self._stream_msg.edit(content=content)
                except Exception:
                    pass
            elif len(content) <= self.EMBED_MAX:
                try:
                    embed = discord.Embed(description=content, color=0x3498db)
                    await self._stream_msg.edit(content=None, embed=embed)
                except Exception:
                    chunks = _split_on_boundaries(content, self.MAX_LENGTH)
                    try:
                        await self._stream_msg.edit(content=chunks[0])
                    except Exception:
                        pass
                    for chunk in chunks[1:]:
                        await self._message_ref.reply(chunk)
            else:
                chunks = _split_on_boundaries(content, self.EMBED_MAX)
                try:
                    embed = discord.Embed(description=chunks[0], color=0x3498db)
                    await self._stream_msg.edit(content=None, embed=embed)
                except Exception:
                    pass
                for chunk in chunks[1:]:
                    try:
                        embed = discord.Embed(description=chunk, color=0x3498db)
                        await self._message_ref.reply(embed=embed)
                    except Exception:
                        await self._message_ref.reply(chunk[:self.MAX_LENGTH])
        else:
            if len(content) <= self.MAX_LENGTH:
                await self._message_ref.reply(content)
            else:
                chunks = _split_on_boundaries(content, self.EMBED_MAX)
                for chunk in chunks:
                    try:
                        embed = discord.Embed(description=chunk, color=0x3498db)
                        await self._message_ref.reply(embed=embed)
                    except Exception:
                        await self._message_ref.reply(chunk[:self.MAX_LENGTH])

    @property
    def text(self):
        return self._buffer

    @property
    def was_started(self):
        return self._started
