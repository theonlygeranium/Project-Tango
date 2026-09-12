#!/usr/bin/env python3
"""
Patch script to fix fleet delegation response chunking.

Root cause: Discord's 2000-char message limit. Fleet agents process tasks
successfully but their FLEET responses exceed the limit, causing 400 errors
and 300s timeouts on the Admiral's side.

Fix:
1. Add _split_on_boundaries() to fleet_protocol.py (shared module)
2. Import it in quartermaster and cartographer bots
3. Add multi-part chunking to quartermaster and cartographer response sending
4. Fix architect's max_chunk from 3800 to 1900
"""

import re
import sys

SCRIPTS_DIR = "/opt/Project-Tango/scripts"

def patch_fleet_protocol():
    """Add _split_on_boundaries to fleet_protocol.py."""
    path = f"{SCRIPTS_DIR}/fleet_protocol.py"
    with open(path, "r") as f:
        content = f.read()

    # Check if already patched
    if "_split_on_boundaries" in content:
        print(f"  {path}: already has _split_on_boundaries, skipping")
        return

    # Add the function at the end of the file
    split_func = '''

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
        split_at = remaining.rfind("\\n", 0, max_len)
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
'''

    content += split_func
    with open(path, "w") as f:
        f.write(content)
    print(f"  {path}: added _split_on_boundaries function")


def patch_quartermaster():
    """Fix quartermaster-bot.py: add import and chunking logic."""
    path = f"{SCRIPTS_DIR}/quartermaster-bot.py"
    with open(path, "r") as f:
        content = f.read()

    # 1. Update import to include _split_on_boundaries
    old_import = "    format_response, track_chain, MAX_CHAIN_DEPTH,\n)"
    new_import = "    format_response, track_chain, MAX_CHAIN_DEPTH,\n    _split_on_boundaries,\n)"
    if old_import in content and "_split_on_boundaries" not in content:
        content = content.replace(old_import, new_import, 1)
        print(f"  {path}: updated import")
    elif "_split_on_boundaries" in content:
        print(f"  {path}: already patched, skipping")
        return
    else:
        print(f"  {path}: WARNING - import pattern not found")
        return

    # 2. Replace single send with chunked send
    old_send = '''                # Send response back to Schubert
                try:
                    schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                    if schubert_channel:
                        await schubert_channel.send(
                            format_response(
                                chain_id=parsed["chain_id"],
                                turn=parsed["turn"] + 1,
                                from_agent="quartermaster",
                                to_agent="schubert",
                                response=response,
                                status="complete",
                            )
                        )
                        log(f"Sent FLEET response to Schubert (chain={parsed['chain_id']})", "INFO")
                except Exception as e:
                    log(f"Error sending FLEET response: {e}", "WARN")'''

    new_send = '''                # Send response back to Schubert (chunked for Discord 2000-char limit)
                try:
                    schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                    if schubert_channel:
                        max_chunk = 1900
                        if len(response) <= max_chunk:
                            await schubert_channel.send(
                                format_response(
                                    chain_id=parsed["chain_id"],
                                    turn=parsed["turn"] + 1,
                                    from_agent="quartermaster",
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
                                        from_agent="quartermaster",
                                        to_agent="schubert",
                                        response=chunk,
                                        status="complete",
                                        part=i,
                                        total_parts=total,
                                    )
                                )
                        log(f"Sent FLEET response to Schubert (chain={parsed['chain_id']})", "INFO")
                except Exception as e:
                    log(f"Error sending FLEET response: {e}", "WARN")'''

    if old_send in content:
        content = content.replace(old_send, new_send, 1)
        print(f"  {path}: updated response sending with chunking")
    else:
        print(f"  {path}: WARNING - send pattern not found, trying alternate")

    with open(path, "w") as f:
        f.write(content)


def patch_cartographer():
    """Fix cartographer-bot.py: add import and chunking logic."""
    path = f"{SCRIPTS_DIR}/cartographer-bot.py"
    with open(path, "r") as f:
        content = f.read()

    # 1. Update import
    old_import = "    format_response, track_chain, MAX_CHAIN_DEPTH,\n)"
    new_import = "    format_response, track_chain, MAX_CHAIN_DEPTH,\n    _split_on_boundaries,\n)"
    if old_import in content and "_split_on_boundaries" not in content:
        content = content.replace(old_import, new_import, 1)
        print(f"  {path}: updated import")
    elif "_split_on_boundaries" in content:
        print(f"  {path}: already patched, skipping")
        return
    else:
        print(f"  {path}: WARNING - import pattern not found")
        return

    # 2. Replace single send with chunked send
    old_send = '''                # Send response back to Schubert
                try:
                    schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                    if schubert_channel:
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
                        log(f"Sent FLEET response to Schubert (chain={parsed['chain_id']})", "INFO")
                except Exception as e:
                    log(f"Error sending FLEET response: {e}", "WARN")'''

    new_send = '''                # Send response back to Schubert (chunked for Discord 2000-char limit)
                try:
                    schubert_channel = bot.get_channel(int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")))
                    if schubert_channel:
                        max_chunk = 1900
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
                    log(f"Error sending FLEET response: {e}", "WARN")'''

    if old_send in content:
        content = content.replace(old_send, new_send, 1)
        print(f"  {path}: updated response sending with chunking")
    else:
        print(f"  {path}: WARNING - send pattern not found, trying alternate")

    with open(path, "w") as f:
        f.write(content)


def patch_architect():
    """Fix architect-bot.py: change max_chunk from 3800 to 1900."""
    path = f"{SCRIPTS_DIR}/architect-bot.py"
    with open(path, "r") as f:
        content = f.read()

    # Fix the max_chunk value (3800 -> 1900)
    old_chunk = "max_chunk = 3800"
    new_chunk = "max_chunk = 1900"
    if old_chunk in content:
        content = content.replace(old_chunk, new_chunk, 1)
        print(f"  {path}: fixed max_chunk 3800 -> 1900")
    else:
        print(f"  {path}: WARNING - max_chunk=3800 not found (may already be fixed)")

    # Also update the comment
    old_comment = "Chunk the response if it exceeds Discord's 3800-char content limit"
    new_comment = "Chunk the response if it exceeds Discord's 2000-char content limit"
    if old_comment in content:
        content = content.replace(old_comment, new_comment, 1)

    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    print("Patching fleet delegation response chunking...")
    print()
    print("[1/4] Patching fleet_protocol.py:")
    patch_fleet_protocol()
    print()
    print("[2/4] Patching quartermaster-bot.py:")
    patch_quartermaster()
    print()
    print("[3/4] Patching cartographer-bot.py:")
    patch_cartographer()
    print()
    print("[4/4] Patching architect-bot.py:")
    patch_architect()
    print()
    print("All patches applied. Restart the fleet bot services to apply changes.")
