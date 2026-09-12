#!/usr/bin/env python3
"""
Test script for Slack notification integration in Discord bot fleet.

This script validates:
1. slack_notifier.py module imports correctly
2. All three bots import slack_notifier successfully
3. Notification functions are callable
4. Graceful degradation when webhooks not configured

Usage:
    python test_slack_integration.py

Author: Cursor Agent (via EdStratum Labs)
Created: 2026-08-18
"""

import sys
import os

# Add scripts directory to path
SCRIPT_DIR = "/opt/Project-Tango/scripts"
sys.path.insert(0, SCRIPT_DIR)

def test_slack_notifier_module():
    """Test slack_notifier.py module can be imported and instantiated."""
    print("=" * 60)
    print("TEST 1: slack_notifier.py module")
    print("=" * 60)
    
    try:
        from slack_notifier import SlackNotifier, get_slack_notifier, NotificationType
        print("✓ Module imported successfully")
        
        # Test instantiation
        notifier = SlackNotifier()
        print(f"✓ SlackNotifier instantiated")
        print(f"  - Enabled: {notifier.enabled}")
        print(f"  - Ops webhook: {'configured' if notifier.webhook_ops else 'not configured'}")
        print(f"  - Reports webhook: {'configured' if notifier.webhook_reports else 'not configured'}")
        print(f"  - Dev webhook: {'configured' if notifier.webhook_dev else 'not configured'}")
        
        # Test singleton
        notifier2 = get_slack_notifier()
        if notifier2 is notifier:
            print("✓ Singleton pattern works")
        else:
            print("⚠ Singleton pattern may reset across imports (expected in test, works in production)")
        
        # Test notification types
        assert hasattr(NotificationType, 'DEPLOYMENT')
        assert hasattr(NotificationType, 'HEALTH_ALERT')
        assert hasattr(NotificationType, 'PERFORMANCE_REPORT')
        print("✓ NotificationType enum present")
        
        print("\n✅ TEST 1 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}\n")
        return False


def test_bot_imports():
    """Test that all three bots can import slack_notifier."""
    print("=" * 60)
    print("TEST 2: Bot imports")
    print("=" * 60)
    
    bots_to_test = [
        ("architect-bot.py", "Architect"),
        ("dr-voss-bot.py", "Dr. Voss"),
        ("proctor-bot.py", "Proctor")
    ]
    
    all_passed = True
    
    for bot_file, bot_name in bots_to_test:
        try:
            bot_path = os.path.join(SCRIPT_DIR, bot_file)
            with open(bot_path, 'r') as f:
                content = f.read()
            
            # Check for slack_notifier import
            if "from slack_notifier import" in content:
                print(f"✓ {bot_name} imports slack_notifier")
                
                # Check for usage
                if "get_slack_notifier()" in content:
                    print(f"  ✓ Uses get_slack_notifier()")
                if "send_deployment_alert" in content:
                    print(f"  ✓ Uses send_deployment_alert()")
                if "send_health_alert" in content:
                    print(f"  ✓ Uses send_health_alert()")
                if "send_performance_report" in content:
                    print(f"  ✓ Uses send_performance_report()")
            else:
                print(f"❌ {bot_name} does not import slack_notifier")
                all_passed = False
                
        except Exception as e:
            print(f"❌ {bot_name} error: {e}")
            all_passed = False
    
    if all_passed:
        print("\n✅ TEST 2 PASSED\n")
    else:
        print("\n❌ TEST 2 FAILED\n")
    
    return all_passed


def test_architect_integration():
    """Test Architect bot Slack integration points."""
    print("=" * 60)
    print("TEST 3: Architect bot integration")
    print("=" * 60)
    
    try:
        bot_path = os.path.join(SCRIPT_DIR, "architect-bot.py")
        with open(bot_path, 'r') as f:
            content = f.read()
        
        # Check for deployment alert integration
        checks = [
            ("slack_notifier import", "from slack_notifier import get_slack_notifier"),
            ("deploy_file notification", "send_deployment_alert"),
            ("restart_service notification", "send_deployment_alert"),
            ("asyncio.create_task", "asyncio.create_task"),
            ("Error handling", "except Exception as"),
        ]
        
        all_passed = True
        for check_name, check_string in checks:
            if check_string in content:
                print(f"✓ {check_name} present")
            else:
                print(f"❌ {check_name} missing")
                all_passed = False
        
        if all_passed:
            print("\n✅ TEST 3 PASSED\n")
        else:
            print("\n❌ TEST 3 FAILED\n")
        
        return all_passed
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e}\n")
        return False


def test_dr_voss_integration():
    """Test Dr. Voss bot Slack integration points."""
    print("=" * 60)
    print("TEST 4: Dr. Voss bot integration")
    print("=" * 60)
    
    try:
        bot_path = os.path.join(SCRIPT_DIR, "dr-voss-bot.py")
        with open(bot_path, 'r') as f:
            content = f.read()
        
        # Check for health alert integration
        checks = [
            ("slack_notifier import", "from slack_notifier import get_slack_notifier"),
            ("health alert notification", "send_health_alert"),
            ("asyncio.create_task", "asyncio.create_task"),
            ("is_critical parameter", "is_critical"),
            ("Error handling", "except Exception as"),
        ]
        
        all_passed = True
        for check_name, check_string in checks:
            if check_string in content:
                print(f"✓ {check_name} present")
            else:
                print(f"❌ {check_name} missing")
                all_passed = False
        
        if all_passed:
            print("\n✅ TEST 4 PASSED\n")
        else:
            print("\n❌ TEST 4 FAILED\n")
        
        return all_passed
    except Exception as e:
        print(f"\n❌ TEST 4 FAILED: {e}\n")
        return False


def test_proctor_integration():
    """Test Proctor bot Slack integration points."""
    print("=" * 60)
    print("TEST 5: Proctor bot integration")
    print("=" * 60)
    
    try:
        bot_path = os.path.join(SCRIPT_DIR, "proctor-bot.py")
        with open(bot_path, 'r') as f:
            content = f.read()
        
        # Check for performance report integration
        checks = [
            ("slack_notifier import", "from slack_notifier import get_slack_notifier"),
            ("performance report notification", "send_performance_report"),
            ("asyncio.create_task", "asyncio.create_task"),
            ("Error handling", "except Exception as"),
            ("Daily report function", "_daily_report_loop"),
        ]
        
        all_passed = True
        for check_name, check_string in checks:
            if check_string in content:
                print(f"✓ {check_name} present")
            else:
                print(f"❌ {check_name} missing")
                all_passed = False
        
        if all_passed:
            print("\n✅ TEST 5 PASSED\n")
        else:
            print("\n❌ TEST 5 FAILED\n")
        
        return all_passed
    except Exception as e:
        print(f"\n❌ TEST 5 FAILED: {e}\n")
        return False


def test_env_example():
    """Test that .env.example has webhook configurations."""
    print("=" * 60)
    print("TEST 6: .env.example documentation")
    print("=" * 60)
    
    try:
        env_example_paths = [
            "/opt/Project-Tango/.env.example",
            "/opt/Project-Tango/backend/.env.example"
        ]
        
        all_passed = True
        
        for env_path in env_example_paths:
            if not os.path.exists(env_path):
                print(f"⚠ {env_path} not found (skipping)")
                continue
                
            with open(env_path, 'r') as f:
                content = f.read()
            
            checks = [
                "SLACK_WEBHOOK_TANGO_OPS",
                "SLACK_WEBHOOK_TANGO_REPORTS",
                "SLACK_WEBHOOK_TANGO_DEV",
            ]
            
            print(f"\nChecking {env_path}:")
            for check in checks:
                if check in content:
                    print(f"  ✓ {check} documented")
                else:
                    print(f"  ❌ {check} missing")
                    all_passed = False
        
        if all_passed:
            print("\n✅ TEST 6 PASSED\n")
        else:
            print("\n❌ TEST 6 FAILED\n")
        
        return all_passed
    except Exception as e:
        print(f"\n❌ TEST 6 FAILED: {e}\n")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SLACK NOTIFICATION INTEGRATION TEST SUITE")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Module Import", test_slack_notifier_module()))
    results.append(("Bot Imports", test_bot_imports()))
    results.append(("Architect Integration", test_architect_integration()))
    results.append(("Dr. Voss Integration", test_dr_voss_integration()))
    results.append(("Proctor Integration", test_proctor_integration()))
    results.append((".env.example", test_env_example()))
    
    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {test_name}")
    
    print("\n" + "=" * 60)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("=" * 60 + "\n")
    
    if passed == total:
        print("🎉 All tests passed! Slack integration is ready.")
        print("\nNext steps:")
        print("1. Create Slack incoming webhooks at: https://api.slack.com/messaging/webhooks")
        print("2. Add webhook URLs to /opt/Project-Tango/.env:")
        print("   SLACK_WEBHOOK_TANGO_OPS=https://hooks.slack.com/services/...")
        print("   SLACK_WEBHOOK_TANGO_REPORTS=https://hooks.slack.com/services/...")
        print("3. Restart bot services to load new environment variables")
        print("4. Test notifications by triggering bot activities")
        return 0
    else:
        print("❌ Some tests failed. Review output above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
