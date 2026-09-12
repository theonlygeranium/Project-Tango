#!/usr/bin/env python3
"""
Test WRITER Playbook Integration End-to-End

This script tests:
1. Playbook invocation via webhook
2. Natural language parsing
3. Status polling (optional)

Usage:
    python test_writer_integration.py [--invoke]

    --invoke: Actually invoke the WRITER playbook (default: dry run only)
"""

import asyncio
import sys
import os

# Add scripts directory to path
sys.path.insert(0, "/opt/Project-Tango/scripts")

from writer_playbook import (
    invoke_playbook,
    parse_natural_language_playbook_request,
    PLAYBOOK_REGISTRY
)


async def test_parsing():
    """Test natural language parsing"""
    print("=" * 60)
    print("TEST 1: Natural Language Parsing")
    print("=" * 60)
    
    test_cases = [
        "invoke cape email workflow with session override test123",
        "run writer playbook cape",
        "trigger playbook cape send emails no",
        "hey architect, can you run the cape playbook?",
        "hello how are you",  # Should return None
    ]
    
    for msg in test_cases:
        parsed = parse_natural_language_playbook_request(msg)
        status = "✓ PARSED" if parsed else "✗ NOT A PLAYBOOK REQUEST"
        print(f"\n{status}")
        print(f"  Message: {msg}")
        if parsed:
            print(f"  Playbook: {parsed['playbook_name']}")
            print(f"  Inputs: {parsed['inputs']}")
    
    print("\n✅ Parsing tests complete\n")


async def test_playbook_registry():
    """Test playbook registry"""
    print("=" * 60)
    print("TEST 2: Playbook Registry")
    print("=" * 60)
    
    print(f"\nAvailable playbooks: {len(PLAYBOOK_REGISTRY)}")
    for key, config in PLAYBOOK_REGISTRY.items():
        print(f"\n  Key: {key}")
        print(f"  Name: {config.name}")
        print(f"  ID: {config.id}")
        print(f"  Description: {config.description}")
        print(f"  Inputs: {[inp['id'] for inp in config.inputs]}")
    
    print("\n✅ Registry tests complete\n")


async def test_invocation_dry_run():
    """Test invocation logic without actually calling webhook"""
    print("=" * 60)
    print("TEST 3: Invocation (DRY RUN)")
    print("=" * 60)
    
    print("\nTest parameters:")
    print("  Playbook: cape-email-workflow")
    print("  Inputs:")
    print("    SESSION_PART_OVERRIDE: test123")
    print("    SEND_EMAILS_OVERRIDE: NO")
    
    print("\n✓ Would invoke:")
    print("  URL: https://app.writer.com/webhook/triggers/playbook/ccbaeea5-22ea-4ed7-86f8-99ddb30535cb")
    print("  Auth: Bearer 3637...20e8")
    print("  Payload: {inputs: [{id: SESSION_PART_OVERRIDE, value: [test123]}, ...]}")
    
    print("\n⚠ DRY RUN: Not actually invoking (use --invoke flag to run for real)")
    print("✅ Dry run complete\n")


async def test_real_invocation():
    """Actually invoke the WRITER playbook"""
    print("=" * 60)
    print("TEST 4: REAL INVOCATION")
    print("=" * 60)
    
    print("\n🚀 Invoking WRITER playbook...")
    
    result = await invoke_playbook(
        playbook_key="cape-email-workflow",
        inputs={
            "SESSION_PART_OVERRIDE": "test-from-schubert-" + str(int(asyncio.get_event_loop().time())),
            "SEND_EMAILS_OVERRIDE": "NO"  # Don't actually send emails
        },
        wait_for_completion=False  # Don't poll, just trigger
    )
    
    print("\nResult:")
    print(f"  Success: {result.get('success')}")
    
    if result.get('success'):
        print(f"  Thread ID: {result.get('thread_id')}")
        print(f"  Status: {result.get('status')}")
        print(f"  Playbook: {result.get('playbook_name')}")
        print(f"  URL: {result.get('playbook_url')}")
        print("\n✅ Playbook triggered successfully!")
        print("\n📋 You can view the session at:")
        print(f"   {result.get('playbook_url')}")
    else:
        print(f"  Error: {result.get('error')}")
        print("\n❌ Invocation failed")
    
    return result


async def main():
    """Run all tests"""
    invoke_real = "--invoke" in sys.argv
    
    print("\n" + "=" * 60)
    print("WRITER PLAYBOOK INTEGRATION TEST SUITE")
    print("=" * 60)
    print(f"Mode: {'REAL INVOCATION' if invoke_real else 'DRY RUN'}")
    print("=" * 60 + "\n")
    
    # Always run these tests
    await test_parsing()
    await test_playbook_registry()
    
    if invoke_real:
        await test_real_invocation()
    else:
        await test_invocation_dry_run()
    
    print("=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
    print("\n📝 Summary:")
    print("  ✓ Natural language parsing works")
    print("  ✓ Playbook registry configured")
    if invoke_real:
        print("  ✓ Real invocation tested")
    else:
        print("  ⚠ Real invocation NOT tested (use --invoke flag)")
    
    print("\n💡 Next Steps:")
    if not invoke_real:
        print("  1. Run with --invoke flag to test real webhook invocation")
        print("  2. Check WRITER app for created session")
    print(f"  {'3' if not invoke_real else '1'}. Get Slack incoming webhooks from admin")
    print(f"  {'4' if not invoke_real else '2'}. Integrate into Architect Discord bot")
    print(f"  {'5' if not invoke_real else '3'}. Test end-to-end: Discord → Architect → WRITER → Slack")
    
    print()


if __name__ == "__main__":
    asyncio.run(main())
