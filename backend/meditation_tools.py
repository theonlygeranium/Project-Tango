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
from typing import Annotated

import numpy as np
from livekit import rtc
from livekit.agents import function_tool, get_job_context
from livekit.agents.llm import function_tool as _ft  # noqa: F811 — re-export for clarity
from livekit.rtc import AudioFrame, AudioSource, LocalAudioTrack

logger = logging.getLogger("project-tango.meditation-tools")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEDITATION_TRACK_PATH = os.getenv(
    "TANGO_MEDITATION_TRACK",
    "/opt/Project-Tango/assets/meditation/nathaniel_deep_return_mixed.wav",
)

TRACK_NAME = "meditation-track"
SAMPLE_RATE = 48000          # LiveKit's native audio rate
NUM_CHANNELS = 1             # Mono — simpler and sufficient for meditation
FRAME_MS = 20                # 20 ms frames (standard LiveKit frame size)
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000  # 960 samples per 20 ms frame

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


class MeditationPlayer:
    """Streams a meditation audio track to the LiveKit room.

    Creates a dedicated AudioSource → LocalAudioTrack → room publication,
    then reads the WAV file in 20 ms frames and pushes them via
    capture_frame (which provides natural real-time pacing through queue
    backpressure).  An asyncio.Event gates pause/resume; task cancellation
    handles stop.
    """

    def __init__(self) -> None:
        self._audio_source: AudioSource | None = None
        self._track: LocalAudioTrack | None = None
        self._publication: rtc.LocalTrackPublication | None = None
        self._playback_task: asyncio.Task | None = None
        self._paused = asyncio.Event()
        self._paused.set()  # not paused initially
        self._stopped = False
        self._position_sec: float = 0.0
        self._total_duration_sec: float = 0.0
        self._room: rtc.Room | None = None

    # -- state queries -------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True if a playback task exists and hasn't finished."""
        return self._playback_task is not None and not self._playback_task.done()

    @property
    def is_playing(self) -> bool:
        """True if actively playing (not paused)."""
        return self.is_active and self._paused.is_set()

    @property
    def is_paused(self) -> bool:
        """True if paused but task still alive."""
        return self.is_active and not self._paused.is_set()

    @property
    def position_sec(self) -> float:
        return self._position_sec

    @property
    def duration_sec(self) -> float:
        return self._total_duration_sec

    # -- playback control ----------------------------------------------------

    async def start(self) -> str:
        """Start playing the meditation track from the beginning."""
        if self.is_active:
            await self.stop()

        if not os.path.exists(MEDITATION_TRACK_PATH):
            logger.error("Meditation track not found: %s", MEDITATION_TRACK_PATH)
            return f"Meditation track not found at {MEDITATION_TRACK_PATH}."

        try:
            ctx = get_job_context()
            self._room = ctx.room
        except RuntimeError:
            return "Cannot start meditation: no room context available."

        try:
            with wave.open(MEDITATION_TRACK_PATH, "rb") as w:
                wav_channels = w.getnchannels()
                wav_sample_rate = w.getframerate()
                wav_sample_width = w.getsampwidth()
                self._total_duration_sec = w.getnframes() / w.getframerate()
        except Exception as exc:
            logger.error("Failed to read meditation WAV: %s", exc)
            return f"Failed to read meditation track: {exc}."

        logger.info(
            "Starting meditation track: %s (channels=%d, rate=%d, duration=%.1f sec)",
            MEDITATION_TRACK_PATH,
            wav_channels,
            wav_sample_rate,
            self._total_duration_sec,
        )

        # Create audio source and publish track
        self._audio_source = AudioSource(SAMPLE_RATE, NUM_CHANNELS, queue_size_ms=1000)
        self._track = LocalAudioTrack.create_audio_track(TRACK_NAME, self._audio_source)
        self._publication = await self._room.local_participant.publish_track(
            self._track, rtc.TrackPublishOptions()
        )

        # Reset state
        self._stopped = False
        self._paused.set()
        self._position_sec = 0.0

        # Launch playback task
        self._playback_task = asyncio.create_task(
            self._playback_loop(wav_channels, wav_sample_rate, wav_sample_width)
        )

        mins = int(self._total_duration_sec // 60)
        secs = int(self._total_duration_sec % 60)
        return f"Meditation track started. Duration: {mins} minutes {secs} seconds."

    async def _playback_loop(
        self, wav_channels: int, wav_sample_rate: int, wav_sample_width: int
    ) -> None:
        """Background task: read WAV → convert to mono 48 kHz → push frames."""
        try:
            with wave.open(MEDITATION_TRACK_PATH, "rb") as w:
                while not self._stopped:
                    # Block while paused
                    await self._paused.wait()
                    if self._stopped:
                        break

                    # Read one frame's worth of samples
                    raw = w.readframes(SAMPLES_PER_FRAME)
                    if not raw:
                        logger.info("Meditation track reached end of file")
                        break

                    # Convert bytes → numpy int16
                    samples = np.frombuffer(raw, dtype=np.int16)

                    # Stereo (or more) → mono by averaging channels
                    if wav_channels > 1:
                        samples = samples.reshape(-1, wav_channels)
                        samples = samples.mean(axis=1).astype(np.int16)

                    # Resample if WAV rate ≠ LiveKit rate
                    if wav_sample_rate != SAMPLE_RATE:
                        samples = self._resample(
                            samples, wav_sample_rate, SAMPLE_RATE
                        )

                    # Build and push the audio frame
                    frame = AudioFrame(
                        data=samples.tobytes(),
                        sample_rate=SAMPLE_RATE,
                        num_channels=NUM_CHANNELS,
                        samples_per_channel=len(samples),
                    )
                    if self._audio_source is not None:
                        await self._audio_source.capture_frame(frame)

                    # Advance position
                    self._position_sec += len(samples) / SAMPLE_RATE

            logger.info(
                "Meditation playback loop ended at position %.1f sec",
                self._position_sec,
            )
        except asyncio.CancelledError:
            logger.info("Meditation playback loop cancelled")
        except Exception as exc:
            logger.error("Meditation playback loop error: %s", exc)
        finally:
            await self._cleanup()

    @staticmethod
    def _resample(
        samples: np.ndarray, input_rate: int, output_rate: int
    ) -> np.ndarray:
        """Simple linear-interpolation resample for int16 mono audio."""
        if input_rate == output_rate:
            return samples
        ratio = output_rate / input_rate
        n_out = int(len(samples) * ratio)
        indices = np.arange(n_out) / ratio
        indices = np.clip(indices, 0, len(samples) - 1).astype(int)
        return samples[indices].astype(np.int16)

    async def _cleanup(self) -> None:
        """Clean up audio resources after playback ends or is stopped."""
        if self._audio_source is not None:
            try:
                self._audio_source.clear_queue()
            except Exception:
                pass

        if self._room is not None and self._publication is not None:
            try:
                await self._room.local_participant.unpublish_track(
                    self._publication.sid
                )
            except Exception as exc:
                logger.warning("Failed to unpublish meditation track: %s", exc)

        self._publication = None
        self._track = None
        self._audio_source = None

    async def pause(self) -> str:
        """Pause the meditation playback."""
        if not self.is_active:
            return "No meditation track is currently playing."
        if self.is_paused:
            return "The meditation is already paused."
        self._paused.clear()
        logger.info("Meditation paused at %.1f sec", self._position_sec)
        return f"Meditation paused at {int(self._position_sec)} seconds."

    async def resume(self) -> str:
        """Resume the meditation playback from pause."""
        if not self.is_active:
            return "No meditation track is currently playing."
        if not self.is_paused:
            return "The meditation is already playing."
        self._paused.set()
        logger.info("Meditation resumed at %.1f sec", self._position_sec)
        return f"Meditation resumed from {int(self._position_sec)} seconds."

    async def stop(self) -> str:
        """Stop the meditation playback and clean up."""
        if not self.is_active:
            return "No meditation track is currently playing."

        self._stopped = True
        self._paused.set()  # unblock any pause wait

        if self._playback_task is not None and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass

        logger.info("Meditation stopped at %.1f sec", self._position_sec)
        return "Meditation track stopped."

    async def aclose(self) -> None:
        """Graceful shutdown — called on agent exit."""
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
