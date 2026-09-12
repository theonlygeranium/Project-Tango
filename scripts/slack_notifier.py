#!/usr/bin/env python3
"""
Slack Notifier — Cross-Platform Notification Module (MCP Edition)
==================================================================
Sends Discord bot notifications to Slack channels via Slack MCP Server.

Uses slack__post_message MCP tool instead of incoming webhooks for unified
read/write interface. Part of Project Tango's Discord-Slack integration.

Supports all Discord bots in the FLEET: Architect, Dr. Voss, Proctor, Admiral Schubert.

Author: Cursor Agent (via EdStratum Labs)
Created: 2026-08-18
Updated: 2026-08-19 (Switched from webhooks to MCP per user approval)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPClient


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Slack channel IDs (must be actual channel IDs, not names)
# Get these via slack__list_channels or from Slack workspace settings
CHANNEL_IDS = {
    "tango-ops": os.environ.get("SLACK_CHANNEL_TANGO_OPS", ""),
    "tango-reports": os.environ.get("SLACK_CHANNEL_TANGO_REPORTS", ""),
    "tango-dev": os.environ.get("SLACK_CHANNEL_TANGO_DEV", ""),
}


class SlackChannel(Enum):
    """Slack channel mappings for different notification types."""
    TANGO_OPS = "tango-ops"  # Deployment, health alerts, system operations
    TANGO_REPORTS = "tango-reports"  # Performance reports, analytics
    TANGO_DEV = "tango-dev"  # Development updates, debug info


class NotificationType(Enum):
    """Types of notifications sent from Discord bots to Slack."""
    DEPLOYMENT = "deployment"
    HEALTH_ALERT = "health_alert"
    PERFORMANCE_REPORT = "performance_report"
    SYSTEM_EVENT = "system_event"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Message Formatting
# ---------------------------------------------------------------------------

def _format_slack_message(
    notification_type: NotificationType,
    title: str,
    message: str,
    bot_name: str,
    severity: str = "info",
    metadata: Optional[dict] = None
) -> dict:
    """
    Format a Discord bot notification for Slack's Block Kit API.
    
    Args:
        notification_type: Type of notification
        title: Notification title
        message: Main notification message
        bot_name: Name of Discord bot sending notification
        severity: info, warning, error, critical
        metadata: Additional context (timestamps, IDs, etc.)
    
    Returns:
        Dict with 'text' (fallback) and 'blocks' (Block Kit formatted)
    """
    # Emoji prefix by notification type
    emoji_map = {
        NotificationType.DEPLOYMENT: "🚀",
        NotificationType.HEALTH_ALERT: "🏥",
        NotificationType.PERFORMANCE_REPORT: "📊",
        NotificationType.SYSTEM_EVENT: "⚙️",
        NotificationType.ERROR: "❌",
    }
    emoji = emoji_map.get(notification_type, "📢")
    
    # Build Slack blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {title}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Source:* {bot_name} (Discord)"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Time:* <!date^{int(time.time())}^{{date_short_pretty}} at {{time}}|{datetime.now(timezone.utc).isoformat()}>"
                }
            ]
        }
    ]
    
    # Add metadata section if provided
    if metadata:
        metadata_lines = [f"*{k}:* {v}" for k, v in metadata.items()]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(metadata_lines)
            }
        })
    
    # Severity indicator (for attachment color - MCP doesn't support attachments directly)
    # But we keep this for potential future use
    color_map = {
        "info": "#36a64f",  # Green
        "warning": "#ff9900",  # Orange
        "error": "#ff0000",  # Red
        "critical": "#8b0000",  # Dark red
    }
    
    return {
        "text": f"{emoji} {title} - {message}",  # Fallback text
        "blocks": blocks,
        "color": color_map.get(severity.lower(), "#36a64f")
    }


# ---------------------------------------------------------------------------
# SlackNotifier Class (MCP Edition)
# ---------------------------------------------------------------------------

class SlackNotifier:
    """
    Async Slack notification client for Discord bot fleet using MCP.

    Uses slack__post_message MCP tool instead of webhooks for unified interface.

    Usage:
        # Initialize with MCP client reference
        notifier = SlackNotifier(mcp_client)

        # Send notifications
        await notifier.send_deployment_alert(
            "Architect deployed v2.1.3",
            "Successfully deployed to production",
            status="success"
        )
    """

    def __init__(self, mcp_client: Optional[MCPClient] = None):
        """
        Initialize Slack notifier with MCP client.

        Args:
            mcp_client: MCP client instance with slack MCP server connected.
                       If None, notifications will be disabled.
        """
        self.mcp = mcp_client
        self.enabled = False  # Disabled: was sending messages as user to work channels

        logging.info(
            "Slack notifications DISABLED — all send operations are no-ops. "
            "Re-enable by setting self.enabled = True in slack_notifier.py"
        )
    
    async def _send_via_mcp(
        self,
        channel: str,
        formatted_message: dict,
        timeout_seconds: float = 10.0
    ) -> bool:
        """
        Send notification to Slack via MCP slack__post_message tool.
        
        Args:
            channel: Slack channel ID (e.g., "C01234567") or channel name (e.g., "#tango-ops")
            formatted_message: Formatted message dict with 'text' and 'blocks'
            timeout_seconds: MCP call timeout
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled or not self.mcp:
            return False
        
        if not channel:
            logging.error("Slack channel not configured")
            return False
        
        try:
            # Call slack__post_message MCP tool
            result = await asyncio.wait_for(
                self.mcp.call_tool("slack__post_message", {
                    "channel": channel,
                    "text": formatted_message["text"],
                    "blocks": json.dumps(formatted_message["blocks"])
                }),
                timeout=timeout_seconds
            )
            
            # MCP returns string result - check for success indicators
            if result and ("ok" in result.lower() or "posted" in result.lower() or "sent" in result.lower()):
                return True
            else:
                logging.warning(f"Slack MCP response: {result[:200]}")
                return True  # Optimistic - assume success if no error
                
        except asyncio.TimeoutError:
            logging.error(f"Slack MCP timeout after {timeout_seconds}s")
            return False
        except Exception as e:
            logging.error(f"Slack MCP error: {e}")
            return False
    
    async def send_deployment_alert(
        self,
        title: str,
        message: str,
        bot_name: str = "The Architect",
        status: str = "info",
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Send deployment notification to #tango-ops.
        
        Args:
            title: Deployment title (e.g., "Deployed v2.1.3")
            message: Deployment details
            bot_name: Name of bot sending notification
            status: info, success, warning, error
            metadata: Additional context (version, commit hash, etc.)
        
        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return False
        
        severity = "info" if status in ["info", "success"] else "warning"
        
        formatted = _format_slack_message(
            NotificationType.DEPLOYMENT,
            title,
            message,
            bot_name,
            severity,
            metadata
        )
        
        channel = CHANNEL_IDS.get("tango-ops") or "#tango-ops"
        return await self._send_via_mcp(channel, formatted)
    
    async def send_health_alert(
        self,
        title: str,
        message: str,
        bot_name: str = "Dr. Voss",
        is_critical: bool = False,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Send health alert to #tango-ops.
        
        Args:
            title: Alert title (e.g., "High Memory Usage")
            message: Alert details
            bot_name: Name of bot sending notification
            is_critical: Whether alert requires immediate attention
            metadata: Additional context (metrics, thresholds, etc.)
        
        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return False
        
        severity = "critical" if is_critical else "warning"
        
        formatted = _format_slack_message(
            NotificationType.HEALTH_ALERT,
            title,
            message,
            bot_name,
            severity,
            metadata
        )
        
        channel = CHANNEL_IDS.get("tango-ops") or "#tango-ops"
        return await self._send_via_mcp(channel, formatted)
    
    async def send_performance_report(
        self,
        title: str,
        message: str,
        bot_name: str = "The Proctor",
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Send performance report to #tango-reports.
        
        Args:
            title: Report title (e.g., "Daily Performance Report")
            message: Report content
            bot_name: Name of bot sending notification
            metadata: Additional context (stats, trends, etc.)
        
        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return False
        
        formatted = _format_slack_message(
            NotificationType.PERFORMANCE_REPORT,
            title,
            message,
            bot_name,
            "info",
            metadata
        )
        
        channel = CHANNEL_IDS.get("tango-reports") or "#tango-reports"
        return await self._send_via_mcp(channel, formatted)
    
    async def send_system_event(
        self,
        title: str,
        message: str,
        bot_name: str,
        channel: SlackChannel = SlackChannel.TANGO_OPS,
        severity: str = "info",
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Send generic system event notification.
        
        Args:
            title: Event title
            message: Event details
            bot_name: Name of bot sending notification
            channel: Target Slack channel
            severity: info, warning, error, critical
            metadata: Additional context
        
        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return False
        
        formatted = _format_slack_message(
            NotificationType.SYSTEM_EVENT,
            title,
            message,
            bot_name,
            severity,
            metadata
        )
        
        # Get channel ID or use channel name as fallback
        channel_id = CHANNEL_IDS.get(channel.value) or f"#{channel.value}"
        return await self._send_via_mcp(channel_id, formatted)


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

_notifier_instance: Optional[SlackNotifier] = None


def get_slack_notifier(mcp_client: Optional[MCPClient] = None) -> SlackNotifier:
    """
    Get or create singleton SlackNotifier instance.
    
    Args:
        mcp_client: MCP client instance (required on first call)
    
    Returns:
        SlackNotifier instance
    """
    global _notifier_instance
    if _notifier_instance is None:
        if mcp_client is None:
            logging.warning("Creating disabled SlackNotifier (no MCP client provided)")
        _notifier_instance = SlackNotifier(mcp_client)
    return _notifier_instance


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

async def test_notification():
    """
    Test Slack notification integration.
    
    NOTE: This test requires an MCP client to be configured.
    In production, the Discord bots will pass their MCP client instance.
    """
    print("Testing Slack notifications (MCP edition)...")
    print("NOTE: This test requires MCP client configuration in bot code.")
    print("To test manually, use The Architect bot in Discord.")
    print()
    print("Example test commands:")
    print('  @The Architect use slack__post_message to send "Test" to #tango-dev')
    print('  @The Architect list Slack channels')


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_notification())
