from __future__ import annotations

import pytest

import main


def test_sync_transcription_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TANGO_SYNC_TRANSCRIPTION", raising=False)
    assert main._sync_transcription() is False


def test_sync_transcription_can_be_reenabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TANGO_SYNC_TRANSCRIPTION", "true")
    assert main._sync_transcription() is True
    monkeypatch.setenv("TANGO_SYNC_TRANSCRIPTION", "0")
    assert main._sync_transcription() is False


def test_max_tool_steps_defaults_above_livekit_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TANGO_MAX_TOOL_STEPS", raising=False)
    assert main._max_tool_steps() == main.DEFAULT_MAX_TOOL_STEPS
    assert main.DEFAULT_MAX_TOOL_STEPS > 3


def test_max_tool_steps_override_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TANGO_MAX_TOOL_STEPS", "12")
    assert main._max_tool_steps() == 12
    monkeypatch.setenv("TANGO_MAX_TOOL_STEPS", "0")
    assert main._max_tool_steps() == main.DEFAULT_MAX_TOOL_STEPS
    monkeypatch.setenv("TANGO_MAX_TOOL_STEPS", "nope")
    assert main._max_tool_steps() == main.DEFAULT_MAX_TOOL_STEPS


def test_preemptive_generation_disabled_when_vision_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TANGO_PREEMPTIVE_GENERATION", raising=False)
    assert main._preemptive_generation_enabled(vision_enabled=True) is False
    assert main._preemptive_generation_enabled(vision_enabled=False) is True
    monkeypatch.setenv("TANGO_PREEMPTIVE_GENERATION", "false")
    assert main._preemptive_generation_enabled(vision_enabled=False) is False


def test_preemptive_generation_never_starts_tts() -> None:
    enabled = main._preemptive_generation_options(enabled=True)
    disabled = main._preemptive_generation_options(enabled=False)
    assert enabled == {"enabled": True, "preemptive_tts": False}
    assert disabled == {"enabled": False, "preemptive_tts": False}
