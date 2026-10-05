"""Meditation track streaming tools for Project Tango voice agents.

Provides a MeditationPlayer that streams a pre-recorded meditation audio file
to the LiveKit room as a separate audio track, with pause/resume/stop control.
Function tools allow the LLM to start, pause, resume, and stop playback.
Voice-command detection in on_user_turn_completed enables hands-free control.
"""

from __future__ import annotations

import asyncio
import logging
import os
import wave
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
from livekit import rtc
from livekit.agents import function_tool

logger = logging.getLogger("project-tango.meditation-tools")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEDITATION_TRACK_PATH = os.getenv(
    "TANGO_MEDITATION_TRACK",
    "/opt/Project-Tango/assets/meditation/nathaniel_deep_return_mixed.wav",
)

# BackgroundAudioPlayer mixes at 48 kHz mono.
SAMPLE_RATE = 48000
NUM_CHANNELS = 1
# Silence emitted per mixer pull while paused. The mixer cancels a stream
# that yields nothing for 100 ms, which would end playback, so a paused
# track must keep producing (silent) frames.
PAUSE_FRAME_MS = 10
PAUSE_SAMPLES = SAMPLE_RATE * PAUSE_FRAME_MS // 1000

# Track gain while the agent is speaking, so the persona stays intelligible.
DUCKED_GAIN = float(os.getenv("TANGO_MEDITATION_DUCK_GAIN", "0.3"))
# How quickly the gain moves toward its target (full swing in ~250 ms).
GAIN_STEP_PER_SECOND = 4.0

MEDITATION_AVAILABLE = os.path.exists(MEDITATION_TRACK_PATH)

# ---------------------------------------------------------------------------
# Voice-command phrase detection
# ---------------------------------------------------------------------------

PLAY_PHRASES = frozenset({
    "play meditation", "start meditation", "play the meditation",
    "play the meditation track", "start the meditation",
    "begin meditation", "play the track", "meditation track",
    "play nathaniel's meditation", "start the track",
    "play the deep return", "play deep return",
})

PAUSE_PHRASES = frozenset({
    "pause", "pause the meditation", "pause it", "pause the track",
    "pause meditation", "hold on", "wait a moment", "pause the audio",
})

RESUME_PHRASES = frozenset({
    "resume", "resume the meditation", "continue", "continue the meditation",
    "keep going", "unpause", "play again", "resume the track",
    "resume the audio",
})

STOP_PHRASES = frozenset({
    "stop", "stop the meditation", "stop the track", "stop playing",
    "end the meditation", "end meditation", "turn it off",
    "that's enough", "stop the audio", "end the track",
})


def detect_meditation_command(text: str, meditation_active: bool = False) -> str | None:
    """Detect meditation voice commands from user text.

    Returns 'play', 'pause', 'resume', 'stop', or None.

    Pause/resume/stop are only detected when meditation is actively playing
    to avoid false positives in normal conversation.
    """
    if not text:
        return None
    text_lower = text.lower().strip()

    # "play" phrases are always detected (specific enough to avoid false positives)
    for phrase in PLAY_PHRASES:
        if phrase in text_lower:
            return "play"

    # pause/resume/stop only detected when meditation is active
    if meditation_active:
        for phrase in PAUSE_PHRASES:
            if phrase in text_lower:
                return "pause"
        for phrase in RESUME_PHRASES:
            if phrase in text_lower:
                return "resume"
        for phrase in STOP_PHRASES:
            if phrase in text_lower:
                return "stop"

    return None


# ---------------------------------------------------------------------------
# MeditationPlayer
# ---------------------------------------------------------------------------


def _track_duration_seconds(path: str) -> float:
    """Duration of a WAV file, or 0.0 when it cannot be read cheaply."""
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def _decode_track(path: str) -> AsyncIterator[rtc.AudioFrame]:
    """Decode *path* to 48 kHz mono frames with LiveKit's decoder.

    The decoder resamples properly; the previous player picked the nearest
    sample instead, which aliased audibly on 44.1 kHz sources.
    """
    from livekit.agents.utils.audio import audio_frames_from_file

    return audio_frames_from_file(path, sample_rate=SAMPLE_RATE, num_channels=NUM_CHANNELS)


class MeditationPlayer:
    """Plays the meditation track through the session's BackgroundAudioPlayer.

    The track is mixed onto the agent's background-audio track (the same one
    the thinking sound uses) instead of a separately published track. While
    the agent is speaking the track is ducked to ``DUCKED_GAIN`` so the
    persona stays intelligible; it ramps back up when the agent stops. Pause
    holds the read position and emits silence; stop ends the stream.

    ``attach()`` must be called once the session's BackgroundAudioPlayer is
    running; until then ``start()`` reports that playback is unavailable.
    """

    def __init__(self, track_path: str | None = None) -> None:
        self._track_path = track_path or MEDITATION_TRACK_PATH
        self._background_audio: Any | None = None
        self._handle: Any | None = None
        self._stream: Any | None = None
        self._paused = asyncio.Event()
        self._paused.set()  # set == playing
        self._stopped = False
        self._agent_speaking = False
        self._gain = 1.0
        self._position_sec: float = 0.0
        self._total_duration_sec: float = 0.0

    # -- wiring ----------------------------------------------------------------

    def attach(self, background_audio: Any, session: Any | None = None) -> None:
        """Use *background_audio* for playback and duck under *session* speech."""
        self._background_audio = background_audio
        if session is not None:
            session.on("agent_state_changed", self._on_agent_state_changed)

    def _on_agent_state_changed(self, ev: Any) -> None:
        self._agent_speaking = getattr(ev, "new_state", None) == "speaking"

    # -- state queries ---------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True if a track is playing or paused."""
        return self._handle is not None and not self._handle.done()

    @property
    def is_playing(self) -> bool:
        return self.is_active and self._paused.is_set()

    @property
    def is_paused(self) -> bool:
        return self.is_active and not self._paused.is_set()

    @property
    def position_sec(self) -> float:
        return self._position_sec

    @property
    def duration_sec(self) -> float:
        return self._total_duration_sec

    # -- audio generation ------------------------------------------------------

    def _next_gain(self, frame_seconds: float) -> float:
        target = DUCKED_GAIN if self._agent_speaking else 1.0
        step = GAIN_STEP_PER_SECOND * frame_seconds
        if self._gain < target:
            self._gain = min(target, self._gain + step)
        elif self._gain > target:
            self._gain = max(target, self._gain - step)
        return self._gain

    @staticmethod
    def _apply_gain(frame: rtc.AudioFrame, gain: float) -> rtc.AudioFrame:
        if gain >= 0.999:
            return frame
        samples = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32)
        scaled = np.clip(samples * gain, -32768, 32767).astype(np.int16)
        return rtc.AudioFrame(
            data=scaled.tobytes(),
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=frame.samples_per_channel,
        )

    @staticmethod
    def _silence() -> rtc.AudioFrame:
        return rtc.AudioFrame(
            data=bytes(PAUSE_SAMPLES * NUM_CHANNELS * 2),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            samples_per_channel=PAUSE_SAMPLES,
        )

    async def _frames(self, source: AsyncIterator[rtc.AudioFrame]) -> AsyncIterator[rtc.AudioFrame]:
        try:
            async for frame in source:
                while not self._paused.is_set():
                    if self._stopped:
                        return
                    yield self._silence()
                if self._stopped:
                    return
                frame_seconds = frame.samples_per_channel / frame.sample_rate
                # Count the frame before handing it to the mixer, so the
                # position reported at pause time includes it.
                self._position_sec += frame_seconds
                yield self._apply_gain(frame, self._next_gain(frame_seconds))
            logger.info("Meditation track reached end at %.1f sec", self._position_sec)
        finally:
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                await aclose()

    # -- playback control ------------------------------------------------------

    async def start(self) -> str:
        """Start playing the meditation track from the beginning."""
        if self.is_active:
            await self.stop()

        if not os.path.exists(self._track_path):
            logger.error("Meditation track not found: %s", self._track_path)
            return f"Meditation track not found at {self._track_path}."
        if self._background_audio is None:
            logger.warning("Meditation requested but background audio is not running")
            return "Meditation playback is unavailable in this session."

        self._stopped = False
        self._paused.set()
        self._position_sec = 0.0
        self._gain = DUCKED_GAIN if self._agent_speaking else 1.0
        self._total_duration_sec = _track_duration_seconds(self._track_path)

        try:
            self._stream = self._frames(_decode_track(self._track_path))
            self._handle = self._background_audio.play(self._stream)
        except Exception as exc:
            logger.exception("Could not start meditation playback")
            return f"Failed to start the meditation track: {exc}."

        logger.info(
            "Meditation started path=%s duration=%.1f sec",
            self._track_path,
            self._total_duration_sec,
        )
        if self._total_duration_sec > 0:
            mins = int(self._total_duration_sec // 60)
            secs = int(self._total_duration_sec % 60)
            return f"Meditation track started. Duration: {mins} minutes {secs} seconds."
        return "Meditation track started."

    async def pause(self) -> str:
        """Pause playback, holding the current position."""
        if not self.is_active:
            return "No meditation track is currently playing."
        if self.is_paused:
            return "The meditation is already paused."
        self._paused.clear()
        logger.info("Meditation paused at %.1f sec", self._position_sec)
        return f"Meditation paused at {int(self._position_sec)} seconds."

    async def resume(self) -> str:
        """Resume playback from the paused position."""
        if not self.is_active:
            return "No meditation track is currently playing."
        if not self.is_paused:
            return "The meditation is already playing."
        self._paused.set()
        logger.info("Meditation resumed at %.1f sec", self._position_sec)
        return f"Meditation resumed from {int(self._position_sec)} seconds."

    async def stop(self) -> str:
        """Stop playback."""
        if not self.is_active:
            return "No meditation track is currently playing."
        self._stopped = True
        self._paused.set()
        handle = self._handle
        if handle is not None:
            handle.stop()
            try:
                await asyncio.wait_for(handle.wait_for_playout(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Meditation stream did not finish within 2 s of stop")
        # The mixer stops pulling a stopped stream but does not close it; close
        # it here so the file decoder task is released now, not at GC time.
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                await stream.aclose()
            except RuntimeError:
                pass  # still mid-pull in the mixer; it returns on its next pull
        logger.info("Meditation stopped at %.1f sec", self._position_sec)
        return "Meditation track stopped."

    async def aclose(self) -> None:
        """Stop playback on agent shutdown."""
        if self.is_active:
            await self.stop()


# ---------------------------------------------------------------------------
# Function-tool builder
# ---------------------------------------------------------------------------


def build_meditation_tools(player: MeditationPlayer) -> list:
    """Build function_tools for meditation playback control, bound to *player*."""

    @function_tool
    async def play_meditation_track() -> str:
        """Play the guided meditation audio track from the beginning.

        Use this when the user asks to play, start, or begin a meditation
        track. The track streams from start to finish (approximately 30
        minutes). The user can pause, resume, or stop it at any time.
        """
        return await player.start()

    @function_tool
    async def pause_meditation() -> str:
        """Pause the currently playing meditation track.

        Use this when the user asks to pause the meditation. The track
        will resume from the same position when resumed.
        """
        return await player.pause()

    @function_tool
    async def resume_meditation() -> str:
        """Resume the paused meditation track.

        Use this when the user asks to resume or continue the meditation
        after it has been paused.
        """
        return await player.resume()

    @function_tool
    async def stop_meditation() -> str:
        """Stop the meditation track completely.

        Use this when the user asks to stop or end the meditation. This
        stops playback and cleans up the audio track.
        """
        return await player.stop()

    return [play_meditation_track, pause_meditation, resume_meditation, stop_meditation]


# ---------------------------------------------------------------------------
# System-prompt instruction text
# ---------------------------------------------------------------------------

MEDITATION_INSTRUCTIONS = (
    "\n\nMEDITATION TRACK ACCESS: You have tools to play a guided meditation "
    "audio track. When the user asks to play, start, or begin a meditation "
    "track, use the play_meditation_track tool to stream it from start to "
    "finish. The track is approximately 30 minutes long. If the user asks to "
    "pause the meditation, use pause_meditation. To resume after pausing, use "
    "resume_meditation. To stop completely, use stop_meditation. Voice "
    "commands for pause, resume, and stop are also detected automatically "
    "during playback, so you do not need to call the tools yourself if the "
    "user simply says 'pause' or 'resume' — the system handles it. Just "
    "acknowledge the action naturally."
)
