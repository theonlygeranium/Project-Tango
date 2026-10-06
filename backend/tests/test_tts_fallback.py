"""The TTS fallback must engage on the streaming path AgentSession uses.

The previous hand-written wrapper forwarded stream() straight to the primary,
so an ElevenLabs outage still produced silence ("no audio frames were
pushed") instead of falling back to Deepgram Aura.
"""

from __future__ import annotations

import asyncio

import pytest
from livekit.agents import APIConnectionError, tts as lk_tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

import main

SAMPLE_RATE = 24000
# 100 ms of 16-bit mono silence with a non-zero marker so frames are identifiable.
PCM_CHUNK = (b"\x01\x00" * (SAMPLE_RATE // 10))


class _FakeTTS(lk_tts.TTS):
    def __init__(self, *, name: str, fail: bool, streaming: bool) -> None:
        super().__init__(
            capabilities=lk_tts.TTSCapabilities(streaming=streaming),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self.name = name
        self.fail = fail
        self.calls = 0

    @property
    def model(self) -> str:
        return self.name

    @property
    def provider(self) -> str:
        return "fake"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> lk_tts.ChunkedStream:
        return _FakeChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> lk_tts.SynthesizeStream:
        return _FakeSynthesizeStream(tts=self, conn_options=conn_options)


class _FakeChunkedStream(lk_tts.ChunkedStream):
    async def _run(self, output_emitter: lk_tts.AudioEmitter) -> None:
        fake: _FakeTTS = self._tts  # type: ignore[assignment]
        fake.calls += 1
        if fake.fail:
            raise APIConnectionError(f"{fake.name} is down")
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(PCM_CHUNK)
        output_emitter.flush()


class _FakeSynthesizeStream(lk_tts.SynthesizeStream):
    async def _run(self, output_emitter: lk_tts.AudioEmitter) -> None:
        fake: _FakeTTS = self._tts  # type: ignore[assignment]
        fake.calls += 1
        if fake.fail:
            raise APIConnectionError(f"{fake.name} is down")
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=utils.shortuuid())
        async for item in self._input_ch:
            if isinstance(item, str):
                output_emitter.push(PCM_CHUNK)
        output_emitter.end_input()


async def _stream_audio_bytes(engine: lk_tts.TTS, text: str) -> int:
    stream = engine.stream()
    stream.push_text(text)
    stream.end_input()
    total = 0
    async with stream:
        async for event in stream:
            total += len(event.frame.data.tobytes())
    return total


async def _synth_audio_bytes(engine: lk_tts.TTS, text: str) -> int:
    total = 0
    async with engine.synthesize(text) as chunked:
        async for event in chunked:
            total += len(event.frame.data.tobytes())
    return total


@pytest.mark.asyncio
async def test_streaming_primary_failure_falls_back_on_stream_path() -> None:
    primary = _FakeTTS(name="elevenlabs", fail=True, streaming=True)
    fallback = _FakeTTS(name="aura", fail=False, streaming=True)
    adapter = main._build_fallback_tts(primary, fallback, main.get_persona("general-info"))
    try:
        audio = await asyncio.wait_for(_stream_audio_bytes(adapter, "Hello there."), 10)
    finally:
        await adapter.aclose()

    assert primary.calls >= 1
    assert fallback.calls >= 1
    assert audio > 0


@pytest.mark.asyncio
async def test_non_streaming_primary_failure_falls_back() -> None:
    # F5-TTS (Jeremiah pilot) is non-streaming.
    primary = _FakeTTS(name="f5", fail=True, streaming=False)
    fallback = _FakeTTS(name="aura", fail=False, streaming=True)
    adapter = main._build_fallback_tts(primary, fallback, main.get_persona("jeremiah"))
    try:
        audio = await asyncio.wait_for(_synth_audio_bytes(adapter, "Hello there."), 10)
    finally:
        await adapter.aclose()

    assert fallback.calls >= 1
    assert audio > 0


@pytest.mark.asyncio
async def test_healthy_primary_is_used_without_touching_fallback() -> None:
    primary = _FakeTTS(name="elevenlabs", fail=False, streaming=True)
    fallback = _FakeTTS(name="aura", fail=False, streaming=True)
    adapter = main._build_fallback_tts(primary, fallback, main.get_persona("general-info"))
    try:
        audio = await asyncio.wait_for(_stream_audio_bytes(adapter, "Hello there."), 10)
    finally:
        await adapter.aclose()

    assert primary.calls == 1
    assert fallback.calls == 0
    assert audio > 0
