"""Stopping a transcription must not delay the agent's reply.

stop() runs inside on_user_turn_completed. It used to await the Postgres
insert and a /usr/sbin/sendmail subprocess before returning, so the agent
stayed silent for the length of both.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import transcription_tools
from transcription_tools import TranscriptionRecorder

SLOW_SECONDS = 0.5


def _recorder(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> TranscriptionRecorder:
    recorder = TranscriptionRecorder(persona_id="jacob", persona_name="Jacob")

    async def slow_save(_text: str, _json: str, _count: int) -> None:
        await asyncio.sleep(SLOW_SECONDS)
        events.append("saved")

    async def slow_email(_text: str) -> None:
        await asyncio.sleep(SLOW_SECONDS)
        events.append("emailed")

    monkeypatch.setattr(recorder, "_save_to_db", slow_save)
    monkeypatch.setattr(recorder, "_send_email", slow_email)
    return recorder


@pytest.mark.asyncio
async def test_stop_returns_before_save_and_email_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    recorder = _recorder(monkeypatch, events)
    await recorder.start()
    await recorder.add_turn("User", "hello")

    started = time.perf_counter()
    transcript = await recorder.stop()
    elapsed = time.perf_counter() - started

    assert transcript is not None and "hello" in transcript
    assert elapsed < SLOW_SECONDS / 5
    assert events == []

    assert await recorder.wait_for_persistence(timeout=5) is True
    assert events == ["saved", "emailed"]


@pytest.mark.asyncio
async def test_finalize_waits_for_pending_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    recorder = _recorder(monkeypatch, events)
    await recorder.start()
    await recorder.add_turn("Agent", "goodbye")

    # Call drops while recording: finalize must stop and finish persisting.
    await recorder.finalize()

    assert events == ["saved", "emailed"]


@pytest.mark.asyncio
async def test_finalize_also_waits_for_an_earlier_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    recorder = _recorder(monkeypatch, events)
    await recorder.start()
    await recorder.add_turn("User", "hello")
    await recorder.stop()  # persistence now running in the background

    await recorder.finalize()

    assert events == ["saved", "emailed"]


@pytest.mark.asyncio
async def test_wait_for_persistence_respects_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    recorder = _recorder(monkeypatch, events)
    await recorder.start()
    await recorder.add_turn("User", "hello")
    await recorder.stop()

    assert await recorder.wait_for_persistence(timeout=0.05) is False
    assert await recorder.wait_for_persistence(timeout=5) is True


def test_finalize_timeout_fits_shutdown_budget() -> None:
    # main.py sets WorkerOptions(shutdown_process_timeout=15.0).
    assert transcription_tools.FINALIZE_PERSIST_TIMEOUT_SECONDS < 15.0
