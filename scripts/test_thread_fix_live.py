#!/usr/bin/env python3
"""
Live integration test for the Architect bot thread/channel fix.

Sends a multi-step message to the Architect's Discord channel that will
trigger auto-thread creation, then sends a follow-up message inside that
thread to verify the AttributeError crash is fixed.

Usage: python3 scripts/test_thread_fix_live.py
"""
import os
import sys
import time
import json
import requests

# Load env vars from .env
_ENV_PATH = "/opt/Project-Tango/.env"
with open(_ENV_PATH) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Use Proctor bot token for sending (allowed by Architect's filter)
# Use Architect token for reading responses
SEND_TOKEN = os.environ.get("PROCTOR_BOT_TOKEN", "")
READ_TOKEN = os.environ.get("ARCHITECT_BOT_TOKEN", "")
DISCORD_API = "https://discord.com/api/v10"
ARCHITECT_CHANNEL_ID = "1538767137080877056"  # From .env (ARCHITECT_CHANNEL_ID)
ARCHITECT_USER_ID = "1538766501035642890"

SEND_HEADERS = {
    "Authorization": f"Bot {SEND_TOKEN}",
    "Content-Type": "application/json",
}
READ_HEADERS = {
    "Authorization": f"Bot {READ_TOKEN}",
    "Content-Type": "application/json",
}

def send_message(channel_id, content):
    """Send a message to a channel, return the message object."""
    resp = requests.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers=SEND_HEADERS,
        json={"content": content},
    )
    resp.raise_for_status()
    return resp.json()

def get_channel_messages(channel_id, limit=10):
    """Get recent messages from a channel."""
    resp = requests.get(
        f"{DISCORD_API}/channels/{channel_id}/messages?limit={limit}",
        headers=READ_HEADERS,
    )
    resp.raise_for_status()
    return resp.json()

def get_thread_id_from_message(message_id):
    """Check if a message has a thread attached."""
    resp = requests.get(
        f"{DISCORD_API}/channels/{ARCHITECT_CHANNEL_ID}/messages",
        headers=READ_HEADERS,
        params={"limit": 20},
    )
    resp.raise_for_status()
    messages = resp.json()

    # Look for thread metadata in recent messages
    for msg in messages:
        if msg.get("thread"):
            return msg["thread"]["id"]
    return None

def wait_for_response(channel_id, bot_user_id, timeout=120, since_timestamp=None):
    """Wait for a response from the bot in the channel."""
    start = time.time()
    while time.time() - start < timeout:
        messages = get_channel_messages(channel_id, limit=10)
        for msg in reversed(messages):
            if since_timestamp and msg.get("timestamp"):
                msg_time = time.mktime(time.strptime(msg["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
                if msg_time <= since_timestamp:
                    continue
            if msg.get("author", {}).get("id") == str(bot_user_id):
                return msg
        time.sleep(3)
    return None

def wait_for_thread_creation(channel_id, timeout=30, since_timestamp=None, message_id=None):
    """Wait for the bot to create a thread on a message."""
    start = time.time()
    while time.time() - start < timeout:
        messages = get_channel_messages(channel_id, limit=20)
        for msg in messages:
            # If looking for a specific message's thread
            if message_id and msg.get("id") == message_id:
                if msg.get("thread"):
                    return msg["thread"]
                continue
            # Otherwise look at any recent message
            if since_timestamp and msg.get("timestamp"):
                msg_time = time.mktime(time.strptime(msg["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
                if msg_time <= since_timestamp:
                    continue
            if msg.get("thread"):
                return msg["thread"]
        time.sleep(2)
    return None

def get_thread_messages(thread_id, limit=10):
    """Get messages from a thread."""
    resp = requests.get(
        f"{DISCORD_API}/channels/{thread_id}/messages?limit={limit}",
        headers=READ_HEADERS,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print("=" * 70)
    print("Live Integration Test: Architect Thread/Channel Fix")
    print("=" * 70)

    # Step 0: Verify bot token works
    print("\n[0] Verifying bot token...")
    resp = requests.get(f"{DISCORD_API}/users/@me", headers=READ_HEADERS)
    if resp.status_code != 200:
        print(f"  FAIL: Bot token invalid ({resp.status_code})")
        sys.exit(1)
    bot_info = resp.json()
    print(f"  OK: Token valid — bot is {bot_info['username']}#{bot_info['discriminator']} (ID: {bot_info['id']})")

    # Step 1: Send a multi-step message that triggers thread creation
    # Using "then" to trigger should_use_thread()
    test_message = f"<@{ARCHITECT_USER_ID}> this is a test. Please list the files in /opt/Project-Tango then tell me how many Python files are there. This is a multi-step task test."
    print(f"\n[1] Sending multi-step test message to Architect channel...")
    print(f"    Message: {test_message[:80]}...")
    sent_msg = send_message(ARCHITECT_CHANNEL_ID, test_message)
    sent_msg_id = sent_msg["id"]
    sent_timestamp = time.time()
    print(f"  OK: Message sent (ID: {sent_msg_id})")

    # Step 2: Wait for the Architect to respond
    print(f"\n[2] Waiting for Architect response (timeout: 120s)...")
    response = wait_for_response(ARCHITECT_CHANNEL_ID, ARCHITECT_USER_ID, timeout=120, since_timestamp=sent_timestamp)
    if not response:
        print("  FAIL: No response from Architect within 120s")
        sys.exit(1)
    print(f"  OK: Architect responded (ID: {response['id']})")
    print(f"    Response preview: {response.get('content', '')[:100]}...")

    # Step 3: Wait for thread creation
    print(f"\n[3] Waiting for auto-thread creation (timeout: 30s)...")
    thread = wait_for_thread_creation(ARCHITECT_CHANNEL_ID, timeout=30, since_timestamp=sent_timestamp, message_id=sent_msg_id)
    if not thread:
        print("  WARN: No thread was created. The response may not have triggered thread thresholds.")
        print("  Continuing with manual thread creation for the test...")

        # Create a thread manually to test the fix
        resp = requests.post(
            f"{DISCORD_API}/channels/{ARCHITECT_CHANNEL_ID}/messages/{sent_msg_id}/threads",
        headers=SEND_HEADERS,
        json={"name": "Test Thread for Fix Verification", "auto_archive_duration": 60},
        )
        if resp.status_code not in (200, 201):
            print(f"  FAIL: Could not create thread manually ({resp.status_code}): {resp.text}")
            sys.exit(1)
        thread = resp.json()
        print(f"  OK: Manually created thread (ID: {thread['id']})")
    else:
        print(f"  OK: Auto-thread created (ID: {thread['id']}, name: {thread.get('name', 'N/A')})")

    thread_id = thread["id"]

    # Step 4: Send a follow-up message INSIDE the thread
    # This is the message that would have crashed the bot before the fix
    # It contains "then" to trigger should_use_thread(), but since we're in a thread,
    # the isinstance check should prevent nested thread creation
    followup_message = f"<@{ARCHITECT_USER_ID}> yes, now also check the scripts directory then count those Python files too."
    print(f"\n[4] Sending follow-up message inside the thread (the crash scenario)...")
    print(f"    Thread ID: {thread_id}")
    print(f"    Message: {followup_message}")
    followup_msg = send_message(thread_id, followup_message)
    followup_timestamp = time.time()
    print(f"  OK: Follow-up sent (ID: {followup_msg['id']})")

    # Step 5: Wait for the Architect to respond in the thread
    print(f"\n[5] Waiting for Architect response in thread (timeout: 120s)...")
    print(f"    This is the critical test — before the fix, the bot would crash here")

    thread_response = None
    start = time.time()
    while time.time() - start < 120:
        try:
            thread_msgs = get_thread_messages(thread_id, limit=10)
            for msg in reversed(thread_msgs):
                msg_time_str = msg.get("timestamp", "")[:19]
                if msg_time_str:
                    try:
                        msg_time = time.mktime(time.strptime(msg_time_str, "%Y-%m-%dT%H:%M:%S"))
                    except ValueError:
                        continue
                    if msg_time <= followup_timestamp:
                        continue
                if msg.get("author", {}).get("id") == ARCHITECT_USER_ID:
                    thread_response = msg
                    break
            if thread_response:
                break
        except Exception as e:
            print(f"    (polling error: {e})")
        time.sleep(3)

    if thread_response:
        print(f"  PASS: Architect responded in thread! (ID: {thread_response['id']})")
        print(f"    Response preview: {thread_response.get('content', '')[:150]}...")
        print(f"\n{'=' * 70}")
        print("RESULT: ALL TESTS PASSED — The fix is working correctly!")
        print(f"{'=' * 70}")
    else:
        print(f"  FAIL: No response from Architect in thread within 120s")
        print(f"\n{'=' * 70}")
        print("RESULT: FAILED — The bot may still be crashing. Check logs:")
        print(f"  sudo journalctl -u schubert-architect.service --since '2 minutes ago'")
        print(f"{'=' * 70}")
        sys.exit(1)


if __name__ == "__main__":
    main()
