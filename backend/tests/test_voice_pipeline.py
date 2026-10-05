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


def test_preemptive_generation_follows_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # Vision no longer forces it off; see _preemptive_generation_enabled.
    monkeypatch.delenv("TANGO_PREEMPTIVE_GENERATION", raising=False)
    assert main._preemptive_generation_enabled() is True
    monkeypatch.setenv("TANGO_PREEMPTIVE_GENERATION", "false")
    assert main._preemptive_generation_enabled() is False


def test_context_injection_invalidates_a_preemptive_request() -> None:
    # LiveKit reuses a preemptive generation only if the chat context after
    # on_user_turn_completed is_equivalent() to the one it was started with.
    # Injecting visual context must break that equivalence so the stale
    # draft is discarded and the reply is generated with the frame summary.
    from livekit.agents.llm import ChatContext

    before = ChatContext()
    before.add_message(role="user", content="what's on my screen?")
    after = before.copy()
    after.add_message(role="system", content="Visual context from the user's screen: ...")

    assert before.copy().is_equivalent(before)
    assert not before.is_equivalent(after)


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


def _resolved_turn_detection(turn_handling: dict) -> object:
    """Mode the real AgentSession resolves from Tango's turn_handling dict."""
    from livekit.agents import AgentSession

    return AgentSession(turn_handling=turn_handling).turn_detection


@pytest.mark.asyncio
@pytest.mark.parametrize("env_value", [None, "", "stt", "STT", "flux"])
async def test_english_personas_use_flux_stt_turn_detection(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None
) -> None:
    if env_value is None:
        monkeypatch.delenv("TANGO_TURN_DETECTION", raising=False)
    else:
        monkeypatch.setenv("TANGO_TURN_DETECTION", env_value)
    persona = main.get_persona("general-info")

    turn_handling = main._turn_handling_for_session(persona, persona.llm_model)

    assert turn_handling["turn_detection"] == "stt"
    assert main._turn_detection_label(turn_handling) == "stt"
    # "stt" is the only mode in which LiveKit consumes Flux EndOfTurn events.
    assert _resolved_turn_detection(turn_handling) == "stt"


@pytest.mark.asyncio
async def test_audio_turn_detector_remains_available_as_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from livekit.agents import inference

    monkeypatch.setenv("TANGO_TURN_DETECTION", "audio")
    persona = main.get_persona("jeremiah")

    turn_handling = main._turn_handling_for_session(persona, persona.llm_model)

    assert isinstance(turn_handling["turn_detection"], inference.TurnDetector)
    assert main._turn_detection_label(turn_handling) == "TurnDetector"


def test_invalid_turn_detection_value_falls_back_to_stt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TANGO_TURN_DETECTION", "semantic")
    assert main._turn_detection_strategy() == main.TURN_DETECTION_STT


@pytest.mark.asyncio
@pytest.mark.parametrize("persona_id", ["mama-lulu", "pinoy-pride"])
@pytest.mark.parametrize("env_value", ["stt", "audio"])
async def test_tagalog_personas_always_use_vad_turn_detection(
    monkeypatch: pytest.MonkeyPatch, persona_id: str, env_value: str
) -> None:
    monkeypatch.setenv("TANGO_TURN_DETECTION", env_value)
    persona = main.get_persona(persona_id)
    assert persona.stt_language == "tl"

    turn_handling = main._turn_handling_for_session(persona, persona.llm_model)

    assert turn_handling["turn_detection"] == "vad"
    assert _resolved_turn_detection(turn_handling) == "vad"


def test_turn_handling_keeps_preemptive_tts_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TANGO_TURN_DETECTION", raising=False)
    persona = main.get_persona("general-info")

    turn_handling = main._turn_handling_for_session(
        persona, persona.llm_model, preemptive_generation_enabled=True
    )

    assert turn_handling["preemptive_generation"] == {"enabled": True, "preemptive_tts": False}


@pytest.mark.parametrize("persona_id", sorted(__import__("personas").TANGO_PERSONAS))
def test_flux_eager_threshold_never_exceeds_eot_threshold(persona_id: str) -> None:
    # deepgram.STTv2 raises ValueError at session start when eager > eot.
    persona = main.get_persona(persona_id)
    if persona.stt_language == "tl" or persona.eager_eot_threshold is None:
        return
    assert persona.eager_eot_threshold <= persona.eot_threshold


@pytest.mark.parametrize("persona_id", sorted(__import__("personas").TANGO_PERSONAS))
def test_elevenlabs_style_is_zero_for_latency(persona_id: str) -> None:
    # ElevenLabs: non-zero style "might increase latency"; recommended 0.
    assert main.get_persona(persona_id).voice_settings.get("style", 0.0) == 0.0


def _built_elevenlabs(persona_id: str):
    from livekit.plugins import elevenlabs

    return main._build_elevenlabs_tts(main.get_persona(persona_id), elevenlabs)


@pytest.mark.parametrize("persona_id", ["mama-lulu", "pinoy-pride"])
def test_tagalog_personas_send_filipino_language_code(
    monkeypatch: pytest.MonkeyPatch, persona_id: str
) -> None:
    from livekit.plugins.elevenlabs import tts as el_tts

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.delenv("TANGO_ELEVENLABS_LANGUAGE_HINTS", raising=False)

    engine = _built_elevenlabs(persona_id)

    # The streaming WebSocket URL is what production uses for synthesis.
    assert "language_code=fil" in el_tts._multi_stream_url(engine._opts)


def test_english_personas_send_no_language_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from livekit.plugins.elevenlabs import tts as el_tts

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    engine = _built_elevenlabs("general-info")

    assert "language_code" not in el_tts._multi_stream_url(engine._opts)


def test_language_hints_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from livekit.plugins.elevenlabs import tts as el_tts

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("TANGO_ELEVENLABS_LANGUAGE_HINTS", "false")
    engine = _built_elevenlabs("pinoy-pride")

    assert "language_code" not in el_tts._multi_stream_url(engine._opts)


def test_prewarm_loads_vad_once_and_sessions_reuse_it() -> None:
    from livekit.plugins import silero

    proc = types.SimpleNamespace(userdata={})
    main.prewarm(proc)
    vad = proc.userdata["vad"]
    assert isinstance(vad, silero.VAD)
    assert vad._opts.min_silence_duration == main.VAD_MIN_SILENCE_DURATION
    assert vad._opts.prefix_padding_duration == main.VAD_PREFIX_PADDING_DURATION

    ctx = types.SimpleNamespace(proc=proc)
    assert main._session_vad(ctx) is vad
    assert main._session_vad(ctx) is vad


def test_session_vad_falls_back_to_loading_without_prewarm() -> None:
    from livekit.plugins import silero

    ctx = types.SimpleNamespace(proc=types.SimpleNamespace(userdata={}))
    assert isinstance(main._session_vad(ctx), silero.VAD)


def test_worker_registers_prewarm() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path(main.__file__).read_text())
    keywords = {
        kw.arg: kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "WorkerOptions"
        for kw in node.keywords
    }
    assert isinstance(keywords.get("prewarm_fnc"), ast.Name)
    assert keywords["prewarm_fnc"].id == "prewarm"


def test_thinking_sound_is_off_for_calm_personas() -> None:
    off = {pid for pid in __import__("personas").TANGO_PERSONAS if not main.get_persona(pid).thinking_sound}
    assert off == {"therapy", "meditation"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persona_id", "env_value", "expected"),
    [
        ("general-info", None, True),
        ("general-info", "false", False),
        ("therapy", None, False),
        ("meditation", None, False),
    ],
)
async def test_background_audio_thinking_sound_selection(
    monkeypatch: pytest.MonkeyPatch, persona_id: str, env_value: str | None, expected: bool
) -> None:
    from livekit import agents as lk_agents

    captured: dict[str, object] = {}

    class FakePlayer:
        def __init__(self, *, thinking_sound: object = None) -> None:
            captured["thinking_sound"] = thinking_sound

        async def start(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(lk_agents, "BackgroundAudioPlayer", FakePlayer)
    if env_value is None:
        monkeypatch.delenv("TANGO_THINKING_SOUND", raising=False)
    else:
        monkeypatch.setenv("TANGO_THINKING_SOUND", env_value)

    ctx = types.SimpleNamespace(room=object())
    player = await main._start_background_audio(ctx, object(), main.get_persona(persona_id))

    assert isinstance(player, FakePlayer)  # meditation needs it even without thinking sound
    assert (captured["thinking_sound"] is not None) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("persona_id", ["mama-lulu", "pinoy-pride"])
async def test_tagalog_sessions_use_documented_endpointing(persona_id: str) -> None:
    from livekit.agents import AgentSession

    persona = main.get_persona(persona_id)
    turn_handling = main._turn_handling_for_session(persona, persona.llm_model)

    session = AgentSession(turn_handling=turn_handling)
    assert session.turn_detection == "vad"
    assert session._opts.endpointing["min_delay"] == 0.7


@pytest.mark.parametrize(
    "persona_id", ["therapy", "general-info", "jeremiah", "jeremiah-v2", "jacob", "meditation"]
)
def test_english_sessions_keep_sdk_endpointing_defaults(persona_id: str) -> None:
    persona = main.get_persona(persona_id)
    assert "endpointing" not in main._turn_handling_for_session(persona, persona.llm_model)


def test_tagalog_stt_sends_keyterms_with_plain_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from livekit.agents import stt as lk_stt
    from livekit.plugins import deepgram

    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.delenv("TANGO_TAGALOG_KEYTERMS", raising=False)
    persona = main.get_persona("pinoy-pride")

    engine = main._build_tagalog_stt(persona, deepgram)

    assert isinstance(engine, lk_stt.FallbackAdapter)
    boosted, plain = engine._stt_instances
    for instance in (boosted, plain):
        assert instance._opts.model == "nova-3"
        assert instance._opts.language.language == "tl"
        assert instance._opts.endpointing_ms == 300
        assert instance._opts.smart_format is True
    assert boosted._opts.keyterm == list(persona.keyterms)
    assert plain._opts.keyterm == []


def test_tagalog_keyterms_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from livekit.plugins import deepgram

    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setenv("TANGO_TAGALOG_KEYTERMS", "false")

    engine = main._build_tagalog_stt(main.get_persona("mama-lulu"), deepgram)

    assert isinstance(engine, deepgram.STT)
    assert engine._opts.keyterm == []
    assert engine._opts.endpointing_ms == 300
