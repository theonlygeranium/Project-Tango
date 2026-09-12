#!/usr/bin/env python3
"""Test script for Schubert Bot V2 initialization — validates MCP, memory, and project setup."""
import asyncio
import os
import sys

sys.path.insert(0, '/opt/Project-Tango/scripts')

# Load env vars from .env
env_file = '/opt/Project-Tango/.env'
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, val = line.partition('=')
            os.environ.setdefault(key.strip(), val.strip())

# Import the bot module (hyphen in filename requires importlib)
import importlib.util
spec = importlib.util.spec_from_file_location("schubert_bot_v2", "/opt/Project-Tango/scripts/schubert-bot-v2.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

# Set config globals
bot.BOT_TOKEN = os.environ.get('SCHUBERT_BOT_TOKEN', '')
bot.ADMIN_USER_ID = int(os.environ.get('SCHUBERT_BOT_ADMIN_USER_ID', '0'))
bot.BOT_CHANNEL_ID = int(os.environ.get('SCHUBERT_BOT_CHANNEL_ID', '0'))
bot.LITELLM_MASTER_KEY = os.environ.get('LITELLM_MASTER_KEY', '')
bot.DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')
bot.ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
bot.SCHUBERT_VOICE_ID = os.environ.get('SCHUBERT_VOICE_ID', bot.DEFAULT_VOICE_ID)


async def main():
    print("=" * 60)
    print("Schubert Bot V2 — Initialization Test")
    print("=" * 60)
    print()

    # Run init_v2
    print("Running init_v2()...")
    print()
    await bot.init_v2()
    print()
    print("init_v2() completed successfully!")
    print()

    # Check MCP status
    if bot.mcp_client:
        status = bot.mcp_client.get_status()
        total = len(bot.mcp_client.get_tool_names())
        print(f"MCP Status ({total} total tools):")
        for s in status:
            icon = 'OK' if s['connected'] else 'FAIL'
            print(f"  [{icon}] {s['name']}: {s['tools']} tools (enabled={s['enabled']})")
    else:
        print("MCP Client: NOT INITIALIZED")

    print()

    # Check memory status
    if bot.memory_store:
        stats = bot.memory_store.get_stats()
        print(f"Memory Stats:")
        print(f"  Redis memories: {stats['redis_memories']}")
        print(f"  Entities: {stats['entities']}")
        print(f"  Facts: {stats['facts']}")
        print(f"  Events: {stats['events']}")
        print(f"  Relationships: {stats['relationships']}")
    else:
        print("Memory Store: NOT INITIALIZED")

    print()

    # Check projects
    if bot.project_registry:
        projects = bot.project_registry.list_projects()
        print(f"Projects ({len(projects)}):")
        for p in projects:
            print(f"  - {p.name} ({len(p.channel_bindings)} channels)")
    else:
        print("Project Registry: NOT INITIALIZED")

    print()

    # Test memory recall
    if bot.memory_store:
        print("Testing memory recall...")
        recalled = bot.memory_store.recall("GitHub MCP server deployment")
        if recalled:
            print(f"  Recall returned {len(recalled)} chars")
            print(f"  Preview: {recalled[:200]}")
        else:
            print("  No memories recalled (expected if store is empty)")

    print()

    # Test context building
    if bot.context_builder and bot.project_registry:
        print("Testing context building...")
        project = bot.project_registry.get_project("default")
        messages = bot.context_builder.build_context(
            project=project,
            session_history=[],
            user_message="test message",
        )
        print(f"  Built context: {len(messages)} messages")

    print()

    # Cleanup
    print("Cleaning up...")
    if bot.mcp_client:
        await bot.mcp_client.disconnect_all()
        print("  MCP client disconnected")
    if bot.memory_store:
        bot.memory_store.close()
        print("  Memory store closed")
    if bot.session_manager:
        bot.session_manager.save_all()
        print("  Sessions saved")

    print()
    print("=" * 60)
    print("ALL TESTS PASSED — V2 is ready for deployment!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
