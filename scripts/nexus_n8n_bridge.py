"""Bridge Nexus Fleet ``health.alert`` events to the n8n Alert Hub.

The Nexus rebuild publishes health alerts on Redis Streams. The n8n workflow
still expects HTTP POSTs to ``/webhook/tango-alert``. Call
``forward_health_alert`` from FleetBot._handle_health_alert (or any bus
subscriber) so the hub keeps working after the architecture change.

Example (src/nexus/bot/base.py)::

    async def _handle_health_alert(self, event):
        self.logger.warning("Health alert received: %s", event.payload)
        from nexus_n8n_bridge import forward_health_alert
        forward_health_alert(event.payload)
"""

from __future__ import annotations

import os
import sys
from typing import Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


def forward_health_alert(payload: dict[str, Any] | None) -> bool:
    """Map a Nexus health.alert payload and POST it to n8n.

    Never raises. Returns True if the dispatcher accepted the alert.
    """
    try:
        from alert_dispatcher import forward_nexus_health_alert

        return bool(forward_nexus_health_alert(payload))
    except Exception:
        return False
