"""Vision context must not block the LiveKit event loop."""

from __future__ import annotations

import logging
import threading
import time
import types

import pytest

from vision_context import LiveVideoContext


def _context(monkeypatch: pytest.MonkeyPatch) -> LiveVideoContext:
    config = types.SimpleNamespace(
        enabled=True,
        model="openai/gpt-4o-mini",
        injection_mode="always",
        max_frame_age_seconds=10.0,
        debug_summaries=False,
        ocr_model="openai/gpt-4o",
    )
    ctx = LiveVideoContext(room=None, config=config)  # type: ignore[arg-type]
    ctx._latest_frame = object()
    ctx._latest_frame_source = "screen share"
    ctx._latest_frame_at = time.monotonic()
    monkeypatch.setattr(ctx, "_model_for_mode", lambda _mode: "openai/gpt-4o-mini")
    return ctx


@pytest.mark.asyncio
async def test_frame_encode_and_request_run_off_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _context(monkeypatch)
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def fake_encode(_frame: object, _mode: str) -> str:
        seen["encode"] = threading.get_ident()
        return "data:image/jpeg;base64,AAAA"

    def fake_request(_url: str, source: str, _text: str, _mode: str) -> str:
        seen["request"] = threading.get_ident()
        return f"a terminal in the {source}"

    monkeypatch.setattr(ctx, "_encode_frame", fake_encode)
    monkeypatch.setattr(ctx, "_request_summary", fake_request)

    result = await ctx.describe_latest_frame("what's on my screen?")

    assert result is not None and "a terminal in the screen share" in result
    assert seen["encode"] != loop_thread
    assert seen["request"] != loop_thread


@pytest.mark.asyncio
async def test_encode_failure_returns_none_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _context(monkeypatch)

    def broken_encode(_frame: object, _mode: str) -> str:
        raise ValueError("bad frame")

    monkeypatch.setattr(ctx, "_encode_frame", broken_encode)
    monkeypatch.setattr(ctx, "_request_summary", lambda *_a: pytest.fail("must not request"))

    with caplog.at_level(logging.ERROR):
        assert await ctx.describe_latest_frame("look at this") is None
    assert "Could not encode LiveKit video frame" in caplog.text


@pytest.mark.asyncio
async def test_request_failure_returns_none_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _context(monkeypatch)
    monkeypatch.setattr(ctx, "_encode_frame", lambda *_a: "data:image/jpeg;base64,AAAA")

    def failing_request(*_args: object) -> str:
        raise TimeoutError("vision model timed out")

    monkeypatch.setattr(ctx, "_request_summary", failing_request)

    with caplog.at_level(logging.ERROR):
        assert await ctx.describe_latest_frame("look at this") is None
    assert "Vision model request failed" in caplog.text
