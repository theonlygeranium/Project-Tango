#!/usr/bin/env python3
"""
WRITER Agent Playbook Integration
===================================
Integration module for invoking WRITER Agent Playbooks via webhook from
Discord bot fleet (specifically The Architect).

Supports:
- Natural language playbook invocation
- Input parameter passing
- Status polling
- Deliverables download

Author: Cursor Agent (via EdStratum Labs)
Created: 2026-08-18
"""

import asyncio
import aiohttp
import json
import logging
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum


# WRITER API Configuration
WRITER_PLAYBOOK_BASE_URL = "https://app.writer.com/webhook/triggers/playbook"
WRITER_API_KEY = "36373b4f3ff5182c8c81baf02d45580fc49a218df7bdf5ddb2d2c4f0e67620e8"

# Polling configuration
POLL_INTERVAL_SECONDS = 60
MAX_POLL_ATTEMPTS = 60  # 1 hour max
DEFAULT_TIMEOUT_SECONDS = 30


class PlaybookStatus(Enum):
    """WRITER playbook execution status"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    AWAITING_USER_RESPONSE = "awaiting_user_response"


@dataclass
class PlaybookConfig:
    """Configuration for a WRITER playbook"""
    id: str
    name: str
    description: str
    inputs: List[Dict[str, Any]]


# Registry of available playbooks
PLAYBOOK_REGISTRY = {
    "cape-email-workflow": PlaybookConfig(
        id="ccbaeea5-22ea-4ed7-86f8-99ddb30535cb",
        name="CAPE Email Workflow",
        description="CAPE-related testing workflow with session part override and email sending",
        inputs=[
            {
                "id": "SESSION_PART_OVERRIDE",
                "description": "Session part override value",
                "required": True
            },
            {
                "id": "SEND_EMAILS_OVERRIDE",
                "description": "Whether to send emails (YES/NO)",
                "required": True,
                "default": "YES"
            }
        ]
    ),
    # Add more playbooks here as needed
}


async def invoke_playbook(
    playbook_key: str,
    inputs: Dict[str, str],
    wait_for_completion: bool = False
) -> Dict[str, Any]:
    """
    Invoke a WRITER Agent Playbook via webhook.
    
    Args:
        playbook_key: Key from PLAYBOOK_REGISTRY
        inputs: Dictionary of input_id -> value
        wait_for_completion: If True, polls until completion
    
    Returns:
        Dictionary with thread_id, status, and optional deliverables
    """
    if playbook_key not in PLAYBOOK_REGISTRY:
        return {
            "success": False,
            "error": f"Unknown playbook: {playbook_key}. Available: {list(PLAYBOOK_REGISTRY.keys())}"
        }
    
    playbook = PLAYBOOK_REGISTRY[playbook_key]
    
    # Build payload
    payload = {
        "inputs": [
            {"id": input_id, "value": [value]}
            for input_id, value in inputs.items()
        ]
    }
    
    webhook_url = f"{WRITER_PLAYBOOK_BASE_URL}/{playbook.id}"
    headers = {
        "Authorization": f"Bearer {WRITER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # Trigger playbook
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
            ) as resp:
                if resp.status not in [200, 201]:
                    error_text = await resp.text()
                    return {
                        "success": False,
                        "error": f"Trigger failed ({resp.status}): {error_text}"
                    }
                
                result = await resp.json()
                thread_id = result.get("thread_id")
                status = result.get("status", "running")
                
                if not thread_id:
                    return {
                        "success": False,
                        "error": "No thread_id in response"
                    }
                
                response = {
                    "success": True,
                    "thread_id": thread_id,
                    "status": status,
                    "playbook_name": playbook.name,
                    "playbook_url": f"https://app.writer.com/organization/YOUR_ORG/team/YOUR_TEAM/writer-agent/session/{thread_id}"
                }
                
                # Poll for completion if requested
                if wait_for_completion and status == "running":
                    final_status = await poll_playbook_status(playbook.id, thread_id)
                    response["status"] = final_status
                    response["completed_at"] = time.time()
                
                return response
                
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"Request timeout after {DEFAULT_TIMEOUT_SECONDS}s"
        }
    except Exception as e:
        logging.error(f"Playbook invocation error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def poll_playbook_status(
    playbook_id: str,
    thread_id: str,
    max_attempts: int = MAX_POLL_ATTEMPTS
) -> str:
    """
    Poll playbook execution status until completion.
    
    Args:
        playbook_id: WRITER playbook ID
        thread_id: Session thread ID
        max_attempts: Maximum polling attempts
    
    Returns:
        Final status string
    """
    status_url = f"{WRITER_PLAYBOOK_BASE_URL}/{playbook_id}/threads/{thread_id}/status"
    headers = {"Authorization": f"Bearer {WRITER_API_KEY}"}
    
    for attempt in range(max_attempts):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    status_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        status = result.get("status", "unknown")
                        
                        # Terminal states
                        if status in [
                            PlaybookStatus.COMPLETED.value,
                            PlaybookStatus.FAILED.value,
                            PlaybookStatus.STOPPED.value,
                            PlaybookStatus.AWAITING_USER_RESPONSE.value
                        ]:
                            return status
                        
                        # Still running, wait before next poll
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    else:
                        logging.warning(f"Status poll failed ({resp.status})")
                        return "unknown"
        except Exception as e:
            logging.error(f"Status polling error: {e}")
            return "error"
    
    return "timeout"


def parse_natural_language_playbook_request(user_message: str) -> Optional[Dict[str, Any]]:
    """
    Parse natural language playbook invocation request.
    
    Examples:
        "invoke cape email workflow with session override test123"
        "run cape playbook session=test send=YES"
        "trigger writer playbook cape-email-workflow"
    
    Returns:
        Dict with playbook_key and inputs, or None if not a playbook request
    """
    message_lower = user_message.lower()
    
    # Check if it's a playbook invocation
    triggers = ["invoke", "run", "trigger", "execute", "start"]
    playbook_indicators = ["playbook", "writer playbook", "cape"]
    
    is_playbook_request = (
        any(trigger in message_lower for trigger in triggers) and
        any(indicator in message_lower for indicator in playbook_indicators)
    )
    
    if not is_playbook_request:
        return None
    
    # Try to identify which playbook
    playbook_key = None
    for key, config in PLAYBOOK_REGISTRY.items():
        if key in message_lower or config.name.lower() in message_lower:
            playbook_key = key
            break
    
    if not playbook_key:
        # Default to first playbook if mentioned generically
        if "cape" in message_lower:
            playbook_key = "cape-email-workflow"
    
    if not playbook_key:
        return None
    
    # Extract inputs (simple keyword matching)
    inputs = {}
    playbook = PLAYBOOK_REGISTRY[playbook_key]
    
    # For CAPE playbook specifically
    if playbook_key == "cape-email-workflow":
        # Extract session override
        if "session" in message_lower:
            # Try to find value after "session"
            parts = message_lower.split("session")
            if len(parts) > 1:
                value_part = parts[1].split()[0] if parts[1].split() else ""
                if value_part:
                    inputs["SESSION_PART_OVERRIDE"] = value_part.strip("=:,")
        
        # Extract email sending
        if "send" in message_lower or "email" in message_lower:
            if "no" in message_lower or "false" in message_lower:
                inputs["SEND_EMAILS_OVERRIDE"] = "NO"
            else:
                inputs["SEND_EMAILS_OVERRIDE"] = "YES"
        else:
            inputs["SEND_EMAILS_OVERRIDE"] = "YES"  # Default
    
    return {
        "playbook_key": playbook_key,
        "inputs": inputs,
        "playbook_name": playbook.name
    }


# Convenience functions for Architect bot integration
async def try_invoke_playbook_from_message(user_message: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to parse and invoke playbook from natural language.
    
    Returns None if message is not a playbook request.
    Returns result dict if it is a playbook request.
    """
    parsed = parse_natural_language_playbook_request(user_message)
    if not parsed:
        return None
    
    result = await invoke_playbook(
        playbook_key=parsed["playbook_key"],
        inputs=parsed["inputs"],
        wait_for_completion=False  # Don't block Discord bot
    )
    
    return result


# Testing
async def test_playbook_invocation():
    """Test WRITER playbook integration"""
    print("Testing WRITER playbook integration...")
    
    # Test natural language parsing
    test_messages = [
        "invoke cape email workflow with session override test123",
        "run writer playbook cape send emails no",
        "trigger playbook session=demo123 send=YES",
        "hello how are you",  # Should return None
    ]
    
    for msg in test_messages:
        parsed = parse_natural_language_playbook_request(msg)
        print(f"\nMessage: {msg}")
        print(f"Parsed: {parsed}")
    
    # Test actual invocation (commented out to avoid triggering real playbook)
    # result = await invoke_playbook(
    #     playbook_key="cape-email-workflow",
    #     inputs={
    #         "SESSION_PART_OVERRIDE": "test123",
    #         "SEND_EMAILS_OVERRIDE": "NO"
    #     }
    # )
    # print(f"\nInvocation result: {result}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_playbook_invocation())
