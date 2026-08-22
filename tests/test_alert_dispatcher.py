"""Unit tests for n8n alert dispatch and Nexus health.alert mapping."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import alert_dispatcher as ad  # noqa: E402
import nexus_n8n_bridge as bridge  # noqa: E402


@pytest.fixture
def dispatcher(monkeypatch):
    monkeypatch.setenv("N8N_ALERT_ENABLED", "true")
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_URL", "http://n8n.test/webhook/tango-alert")
    return ad.AlertDispatcher(
        webhook_url="http://n8n.test/webhook/tango-alert", dedup_ttl=1800
    )


def test_normalize_nexus_severity_aliases():
    assert ad.normalize_severity("warning") == "WARN"
    assert ad.normalize_severity("error") == "CRITICAL"
    assert ad.normalize_severity("healthy") == "INFO"
    assert ad.normalize_severity("WARN") == "WARN"
    assert ad.normalize_severity(None) == "WARN"


def test_nexus_payload_maps_to_n8n_schema(dispatcher, monkeypatch):
    posted = {}

    def fake_post(payload):
        posted.update(payload)

    monkeypatch.setattr(dispatcher, "_post", fake_post)
    ok = dispatcher.send_nexus_health_alert(
        {
            "bot_id": "voss",
            "alert_type": "crash_loop",
            "severity": "warning",
            "message": "voss restarted 6 times",
            "details": {"title": "Crash loop", "restarts": 6},
        }
    )
    assert ok is True
    assert posted["source"] == "nexus:voss"
    assert posted["severity"] == "WARN"
    assert posted["alert_type"] == "crash_loop"
    assert posted["title"] == "Crash loop"
    assert posted["bot_name"] == "voss"
    assert posted["metadata"]["nexus_event"] == "health.alert"
    assert posted["metadata"]["restarts"] == 6


def test_disabled_flag_skips_post(monkeypatch):
    monkeypatch.setenv("N8N_ALERT_ENABLED", "false")
    d = ad.AlertDispatcher(webhook_url="http://n8n.test/webhook/tango-alert")
    with patch.object(d, "_post") as post:
        assert d.send_health_alert("nope") is False
        post.assert_not_called()


def test_dedup_suppresses_repeat(dispatcher, monkeypatch):
    monkeypatch.setattr(dispatcher, "_post", MagicMock())
    first = dispatcher.send_generic(
        "scheduler", "WARN", "scheduler_alert", "High CPU", "cpu 95%"
    )
    second = dispatcher.send_generic(
        "scheduler", "WARN", "scheduler_alert", "High CPU", "cpu 95%"
    )
    assert first is True
    assert second is False
    assert dispatcher._post.call_count == 1


def test_bridge_never_raises(monkeypatch):
    monkeypatch.setattr(
        ad, "forward_nexus_health_alert", MagicMock(side_effect=RuntimeError("boom"))
    )
    assert bridge.forward_health_alert({"bot_id": "admiral"}) is False
