"""MeditationPlayer on BackgroundAudioPlayer: resampling, ducking, pause, stop."""

from __future__ import annotations

import asyncio
import math
import struct
import types
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from livekit.agents.voice.background_audio import PlayHandle

import meditation_tools
from meditation_tools import MeditationPlayer

SOURCE_RATE = 44100  # deliberately not 48 kHz, to exercise resampling
AMPLITUDE = 10000
MIXER_TIMEOUT = 0.1  # rtc.AudioMixer default stream_timeout_ms=100
# The real mixer is paced by its AudioSource (real time). The fake runs at a
# fixed 10x real time so test timing does not depend on machine speed; an
# unpaced fake let a fast CI runner finish the track before stop().
PLAYBACK_SPEEDUP = 10.0


def _write_tone(path: Path, seconds: float) -> None:
    n = int(SOURCE_RATE * seconds)
    samples = (int(AMPLITUDE * math.sin(2 * math.pi * 440 * i / SOURCE_RATE)) for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SOURCE_RATE)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))


class _FakeBackgroundAudio:
    """Consumes play() streams like BackgroundAudioPlayer's mixer does."""

    def __init__(self) -> None:
        self.frames: list[Any] = []
        self.timed_out = False
        self._tasks: list[asyncio.Task[None]] = []

    def play(self, stream: Any) -> PlayHandle:
        handle = PlayHandle()

        async def consume() -> None:
            try:
                while not handle._stop_fut.done():
                    try:
                        frame = await asyncio.wait_for(stream.__anext__(), MIXER_TIMEOUT)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        # The real mixer cancels __anext__, which finalizes the generator.
                        self.timed_out = True
                        break
                    self.frames.append(frame)
                    await asyncio.sleep(
                        frame.samples_per_channel / frame.sample_rate / PLAYBACK_SPEEDUP
                    )
            finally:
                try:
                    await stream.aclose()
                except RuntimeError:
                    pass  # generator still running when the loop shuts down
                handle._mark_playout_done()

        self._tasks.append(asyncio.create_task(consume()))
        return handle

    async def drain(self) -> None:
        await asyncio.gather(*self._tasks, return_exceptions=True)


def _peak(frame: Any) -> int:
    return int(np.abs(np.frombuffer(frame.data, dtype=np.int16)).max(initial=0))


async def _wait_until(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.005)


def _speaking(state: str) -> Any:
    return types.SimpleNamespace(new_state=state)


@pytest.fixture
def tone(tmp_path: Path) -> Path:
    path = tmp_path / "tone.wav"
    _write_tone(path, seconds=1.0)
    return path


@pytest.mark.asyncio
async def test_start_without_background_audio_reports_unavailable(tone: Path) -> None:
    player = MeditationPlayer(track_path=str(tone))
    assert await player.start() == "Meditation playback is unavailable in this session."
    assert not player.is_active


@pytest.mark.asyncio
async def test_plays_whole_track_resampled_to_48k_mono(tone: Path) -> None:
    background = _FakeBackgroundAudio()
    player = MeditationPlayer(track_path=str(tone))
    player.attach(background)

    message = await player.start()
    assert message.startswith("Meditation track started. Duration: 0 minutes 1 seconds")
    await _wait_until(lambda: not player.is_active)

    assert background.frames
    assert {f.sample_rate for f in background.frames} == {48000}
    assert {f.num_channels for f in background.frames} == {1}
    # Every sample LiveKit's decoder yields reaches the mixer. (The decoder
    # itself drops ~90 ms at the end of a file; irrelevant for a 30 min track.)
    decoded = 0
    async for frame in meditation_tools._decode_track(str(tone)):
        decoded += frame.samples_per_channel
    played = sum(f.samples_per_channel for f in background.frames)
    assert played == decoded
    assert played / 48000 == pytest.approx(1.0, abs=0.12)
    assert player.position_sec == pytest.approx(played / 48000, abs=1e-6)
    assert max(_peak(f) for f in background.frames) == pytest.approx(AMPLITUDE, rel=0.1)
    assert not background.timed_out


@pytest.mark.asyncio
async def test_track_is_ducked_while_agent_speaks(tmp_path: Path) -> None:
    path = tmp_path / "long.wav"
    _write_tone(path, seconds=3.0)
    background = _FakeBackgroundAudio()
    session_handlers: dict[str, Any] = {}
    session = types.SimpleNamespace(on=lambda event, cb: session_handlers.__setitem__(event, cb))
    player = MeditationPlayer(track_path=str(path))
    player.attach(background, session)

    session_handlers["agent_state_changed"](_speaking("speaking"))
    await player.start()
    await _wait_until(lambda: player.position_sec > 0.5)
    ducked = [_peak(f) for f in background.frames[-5:]]

    session_handlers["agent_state_changed"](_speaking("listening"))
    mark = len(background.frames)
    await _wait_until(lambda: player.position_sec > 1.5)
    restored = [_peak(f) for f in background.frames[mark:][-5:]]
    await player.stop()
    await background.drain()

    assert max(ducked) == pytest.approx(AMPLITUDE * meditation_tools.DUCKED_GAIN, rel=0.15)
    assert min(restored) == pytest.approx(AMPLITUDE, rel=0.15)


@pytest.mark.asyncio
async def test_pause_holds_position_and_keeps_the_mixer_fed(tmp_path: Path) -> None:
    path = tmp_path / "long.wav"
    _write_tone(path, seconds=3.0)
    background = _FakeBackgroundAudio()
    player = MeditationPlayer(track_path=str(path))
    player.attach(background)

    await player.start()
    await _wait_until(lambda: player.position_sec > 0.3)
    assert (await player.pause()).startswith("Meditation paused at")
    held = player.position_sec
    mark = len(background.frames)
    await _wait_until(lambda: len(background.frames) > mark + 50)

    paused_frames = background.frames[mark + 2 :]
    assert player.is_paused
    assert player.position_sec == held
    assert all(_peak(f) == 0 for f in paused_frames)
    assert not background.timed_out  # silence kept arriving within 100 ms

    assert (await player.resume()).startswith("Meditation resumed from")
    await _wait_until(lambda: player.position_sec > held + 0.2)
    assert await player.stop() == "Meditation track stopped."
    assert not player.is_active
    await background.drain()


@pytest.mark.asyncio
async def test_stop_while_paused_ends_playback(tmp_path: Path) -> None:
    path = tmp_path / "long.wav"
    _write_tone(path, seconds=3.0)
    background = _FakeBackgroundAudio()
    player = MeditationPlayer(track_path=str(path))
    player.attach(background)

    await player.start()
    await _wait_until(lambda: player.position_sec > 0.1)
    await player.pause()
    assert await player.stop() == "Meditation track stopped."
    assert not player.is_active
    assert await player.resume() == "No meditation track is currently playing."
    await background.drain()
