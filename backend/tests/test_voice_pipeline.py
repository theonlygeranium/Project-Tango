from __future__ import annotations

import inspect
import sys
import types

import pytest

# These modules exist on Schubert but are not always present in this checkout.
# Stub only what is missing so the voice-pipeline helpers in main.py can import.
if "mcp_tools" not in sys.modules:
    try:
        import mcp_tools  # noqa: F401
    except ModuleNotFoundError:
        _mcp = types.ModuleType("mcp_tools")

        class _Bridge:
            _connected = False

            async def connect(self) -> None:
                return None

            async def disconnect(self) -> None:
                return None

        _mcp.voice_mcp_bridge = _Bridge()
        sys.modules["mcp_tools"] = _mcp

if "programs" not in sys.modules:
    try:
        import programs  # noqa: F401
    except ModuleNotFoundError:
        _programs = types.ModuleType("programs")

        async def _load_programs(*_a: object, **_k: object) -> list:
            return []

        _programs.load_programs = _load_programs
        _programs.programs_enabled = lambda: False
        sys.modules["programs"] = _programs

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


def test_room_options_disable_playback_paced_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TANGO_SYNC_TRANSCRIPTION", raising=False)
    options = main._room_options_for_session()
    text_output = options.text_output
    assert text_output.sync_transcription is False


def test_livekit_roomio_skips_synchronizer_when_sync_is_false() -> None:
    """Installed livekit-agents must treat sync_transcription=False as 'do not sync'."""
    from livekit.agents.voice.room_io import room_io as room_io_mod

    source = inspect.getsource(room_io_mod.RoomIO.start)
    assert "sync_transcription is not False" in source
    assert "TranscriptSynchronizer" in source


def test_installed_livekit_agents_matches_requirements_pin() -> None:
    import re
    from pathlib import Path

    requirements = (Path(main.__file__).parent / "requirements.txt").read_text()
    pinned = re.search(r"^livekit-agents\[[^\]]*\]==([\w.]+)$", requirements, re.M)
    assert pinned is not None, "livekit-agents must be pinned with == in requirements.txt"
    assert main._livekit_package_versions()["livekit-agents"] == pinned.group(1)


def test_turn_metrics_ms_converts_known_keys_and_skips_junk() -> None:
    item = types.SimpleNamespace(
        metrics={
            "transcription_delay": 0.21,
            "end_of_turn_delay": 0.4,
            "llm_node_ttft": 0.8,
            "tts_node_ttfb": 0.15,
            "e2e_latency": 1.25,
            "started_speaking_at": 1_700_000_000.0,  # timestamp, not a duration
            "playback_latency": -1.0,  # negative values are dropped
            "on_user_turn_completed_delay": True,  # bool is not a duration
        }
    )
    assert main._turn_metrics_ms(item) == {
        "transcription_delay": 210,
        "end_of_turn_delay": 400,
        "llm_node_ttft": 800,
        "tts_node_ttfb": 150,
        "e2e_latency": 1250,
    }
    assert main._format_turn_metrics(main._turn_metrics_ms(item)).startswith(
        "transcription_delay_ms=210 end_of_turn_delay_ms=400"
    )


def test_turn_metrics_ms_handles_missing_metrics() -> None:
    assert main._turn_metrics_ms(types.SimpleNamespace()) == {}
    assert main._turn_metrics_ms(types.SimpleNamespace(metrics=None)) == {}
    assert main._format_turn_metrics({}) == "none"
