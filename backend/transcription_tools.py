"""Transcription recording tools for Project Tango voice agents.

Provides a TranscriptionRecorder that accumulates conversation turns with
speaker diarization (User vs Agent), saves transcripts to the database,
and emails them automatically. Voice-command detection enables hands-free
start/stop control.

Call-drop resilience: the finalize() method is registered as a shutdown
callback, so even if the call drops mid-transcription, the accumulated
transcript is saved to the database and emailed.
"""

from __future__ import annotations

import asyncio
import json
import uuid as uuid_mod
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger("project-tango.transcription-tools")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TRANSCRIPTION_ENABLED = os.getenv("TANGO_TRANSCRIPTION_ENABLED", "1") != "0"
TRANSCRIPTION_EMAIL_FROM = os.getenv(
    "TANGO_TRANSCRIPTION_EMAIL_FROM", "jeff@jgeronimo.com"
)

# ---------------------------------------------------------------------------
# Voice-command phrase detection
# ---------------------------------------------------------------------------

START_PHRASES = frozenset({
    "begin transcription", "start transcription", "begin recording",
    "start recording", "record this conversation", "record this",
    "record our conversation", "start transcribing", "begin transcribing",
    "transcribe this", "transcribe our conversation",
    "record the conversation", "begin the transcription",
    "start the transcription", "let's record this",
    "let's transcribe this", "can you transcribe",
    "can you record this", "record what we say",
})

STOP_PHRASES = frozenset({
    "stop transcription", "stop recording", "end transcription",
    "end recording", "stop transcribing", "end transcribing",
    "finish transcription", "finish recording",
    "stop the transcription", "stop the recording",
    "end the transcription", "end the recording",
    "done recording", "done transcribing",
    "save the transcript", "save the transcription",
    "send me the transcript", "send me the transcription",
    "that's all for the transcription", "wrap up the transcription",
})


def detect_transcription_command(
    text: str, transcription_active: bool = False
) -> str | None:
    """Detect transcription voice commands from user text.

    Returns 'start', 'stop', or None.

    Stop is only detected when transcription is actively recording
    to avoid false positives in normal conversation. Start is only
    detected when NOT already recording.
    """
    if not text:
        return None

    text_lower = text.lower().strip()

    # Check stop phrases only when actively recording
    if transcription_active:
        for phrase in STOP_PHRASES:
            if phrase in text_lower:
                return "stop"

    # Check start phrases only when NOT already recording
    if not transcription_active:
        for phrase in START_PHRASES:
            if phrase in text_lower:
                return "start"

    return None


# ---------------------------------------------------------------------------
# TranscriptionRecorder
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionTurn:
    """A single conversation turn in the transcription."""
    speaker: str  # "User" or "Agent"
    text: str
    timestamp: float  # Unix timestamp
    seq: int = 0


class TranscriptionRecorder:
    """Records conversation turns with speaker diarization.

    Starts on voice command, accumulates turns, and on stop or shutdown
    saves the transcript to the database and emails it to the user.
    """

    def __init__(
        self,
        persona_id: str,
        persona_name: str,
        user_id: str | None = None,
        user_email: str | None = None,
        db_pool: Any | None = None,
        room_name: str | None = None,
    ):
        self.persona_id = persona_id
        self.persona_name = persona_name
        self.user_id = user_id
        self.user_email = user_email
        self.db_pool = db_pool
        self.room_name = room_name

        self._active: bool = False
        self._turns: list[TranscriptionTurn] = []
        self._start_time: float | None = None
        self._stop_time: float | None = None
        self._seq: int = 0
        self._lock = asyncio.Lock()

    @property
    def is_active(self) -> bool:
        return self._active

    async def start(self) -> None:
        """Begin recording conversation turns."""
        async with self._lock:
            if self._active:
                return
            self._active = True
            self._start_time = time.time()
            self._turns = []
            self._seq = 0
            logger.info(
                "Transcription started persona=%s room=%s",
                self.persona_id, self.room_name,
            )

    async def add_turn(self, speaker: str, text: str) -> None:
        """Add a conversation turn to the recording.

        Args:
            speaker: "User" or "Agent"
            text: The spoken text
        """
        if not self._active or not text:
            return
        async with self._lock:
            if not self._active:
                return
            self._seq += 1
            self._turns.append(TranscriptionTurn(
                speaker=speaker,
                text=text,
                timestamp=time.time(),
                seq=self._seq,
            ))

    async def stop(self) -> str | None:
        """Stop recording and save + email the transcript.

        Returns the transcript text, or None if nothing was recorded.
        """
        async with self._lock:
            if not self._active:
                return None
            self._active = False
            self._stop_time = time.time()

            if not self._turns:
                logger.info(
                    "Transcription stopped but no turns recorded persona=%s",
                    self.persona_id,
                )
                return None

            transcript_text = self._format_transcript()
            transcript_json = self._to_json()
            turn_count = len(self._turns)

            logger.info(
                "Transcription stopped persona=%s turns=%d duration_s=%d",
                self.persona_id, turn_count,
                int(self._stop_time - (self._start_time or self._stop_time)),
            )

        # Save to DB and send email outside the lock
        await self._save_to_db(transcript_text, transcript_json, turn_count)
        await self._send_email(transcript_text)

        return transcript_text

    async def finalize(self) -> None:
        """Finalize transcription on session shutdown (call-drop resilience).

        If transcription is still active when the session ends (either
        normally or due to a dropped call), this saves and emails the
        accumulated transcript.
        """
        if self._active:
            logger.info(
                "Transcription finalize on shutdown persona=%s turns=%d",
                self.persona_id, len(self._turns),
            )
            await self.stop()

    def _format_transcript(self) -> str:
        """Format turns as a readable transcript with timestamps."""
        lines: list[str] = []
        lines.append(f"Transcription — {self.persona_name} (Project Tango)")
        if self._start_time:
            start_dt = datetime.fromtimestamp(self._start_time, tz=timezone.utc)
            lines.append(
                f"Recorded: {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
        if self._stop_time and self._start_time:
            duration = int(self._stop_time - self._start_time)
            lines.append(f"Duration: {duration // 60}m {duration % 60}s")
        lines.append(f"Turns: {len(self._turns)}")
        lines.append("=" * 60)
        lines.append("")

        for turn in self._turns:
            elapsed = turn.timestamp - (self._start_time or turn.timestamp)
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            lines.append(f"[{mins:02d}:{secs:02d}] {turn.speaker}: {turn.text}")
            lines.append("")

        return "\n".join(lines)

    def _to_json(self) -> str:
        """Serialize turns as JSON for database storage."""
        return json.dumps({
            "persona_id": self.persona_id,
            "persona_name": self.persona_name,
            "room_name": self.room_name,
            "start_time": self._start_time,
            "stop_time": self._stop_time,
            "turns": [
                {
                    "seq": t.seq,
                    "speaker": t.speaker,
                    "text": t.text,
                    "timestamp": t.timestamp,
                }
                for t in self._turns
            ],
        })

    async def _save_to_db(
        self, transcript_text: str, transcript_json: str, turn_count: int
    ) -> None:
        """Save transcript to the tango.transcriptions table."""
        if self.db_pool is None:
            logger.warning("No DB pool; transcript not saved to database")
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO tango.transcriptions
                        (persona_id, user_id, room_name, started_at, ended_at,
                         transcript_text, transcript_json, turn_count)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    self.persona_id,
                    uuid_mod.UUID(self.user_id) if self.user_id else None,
                    self.room_name,
                    datetime.fromtimestamp(
                        self._start_time, tz=timezone.utc
                    ) if self._start_time else None,
                    datetime.fromtimestamp(
                        self._stop_time, tz=timezone.utc
                    ) if self._stop_time else None,
                    transcript_text,
                    transcript_json,
                    turn_count,
                )
            logger.info(
                "Transcript saved to DB persona=%s turns=%d",
                self.persona_id, turn_count,
            )
        except Exception:
            logger.exception(
                "Could not save transcript to DB persona=%s", self.persona_id
            )

    async def _send_email(self, transcript_text: str) -> None:
        """Email the transcript to the user via sendmail (msmtp on Schubert)."""
        recipient = self.user_email
        if not recipient:
            logger.warning("No user email; transcript not emailed")
            return

        try:
            if self._start_time:
                start_dt = datetime.fromtimestamp(
                    self._start_time, tz=timezone.utc
                )
                subject = (
                    f"Tango Transcription — {self.persona_name} — "
                    f"{start_dt.strftime('%Y-%m-%d %H:%M UTC')}"
                )
            else:
                subject = f"Tango Transcription — {self.persona_name}"

            msg = MIMEText(transcript_text)
            msg["Subject"] = subject
            msg["From"] = TRANSCRIPTION_EMAIL_FROM
            msg["To"] = recipient

            # Use sendmail subprocess (msmtp configured on Schubert)
            proc = await asyncio.create_subprocess_exec(
                "/usr/sbin/sendmail", "-t",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(
                msg.as_string().encode("utf-8")
            )

            if proc.returncode == 0:
                logger.info(
                    "Transcript emailed to=%s persona=%s",
                    recipient, self.persona_id,
                )
            else:
                logger.error(
                    "Sendmail failed rc=%s stderr=%s",
                    proc.returncode,
                    stderr.decode() if stderr else "",
                )
        except Exception:
            logger.exception(
                "Could not email transcript persona=%s", self.persona_id
            )


# ---------------------------------------------------------------------------
# System prompt instructions
# ---------------------------------------------------------------------------

TRANSCRIPTION_INSTRUCTIONS = (
    "\n\nTRANSCRIPTION CAPABILITY: You can record and transcribe conversations. "
    "When the user asks to begin transcription or record the conversation, start "
    "recording with the start_transcription tool. When they ask to stop, use the "
    "stop_transcription tool — the transcript will be automatically saved to the "
    "database and emailed to them. You can also detect voice commands like "
    "'begin transcription' or 'stop recording' automatically."
)


# ---------------------------------------------------------------------------
# LiveKit function tools
# ---------------------------------------------------------------------------

def build_transcription_tools(recorder: TranscriptionRecorder) -> list:
    """Build LiveKit function_tools for the transcription recorder."""
    from livekit.agents import function_tool

    @function_tool
    async def start_transcription() -> str:
        """Begin recording the conversation for transcription.

        Use this when the user asks to start recording, begin
        transcription, or record the conversation.
        """
        await recorder.start()
        return "Transcription started."

    @function_tool
    async def stop_transcription() -> str:
        """Stop recording and save/email the transcript.

        Use this when the user asks to stop recording, end
        transcription, or save the transcript.
        """
        transcript = await recorder.stop()
        if transcript:
            return (
                "Transcription stopped. The transcript has been saved "
                "to the database and emailed to the user."
            )
        return "No transcription was active."

    return [start_transcription, stop_transcription]
