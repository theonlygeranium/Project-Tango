from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("project-tango-tts")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

APP_ROOT = Path(os.getenv("TANGO_APP_ROOT", "/opt/Project-Tango"))
DEFAULT_VOICE_DIR = APP_ROOT / "tts-voices"
DEFAULT_JEREMIAH_REFERENCE = DEFAULT_VOICE_DIR / "jeremiah_reference.wav"
DEFAULT_JEREMIAH_REFERENCE_TEXT_PATH = DEFAULT_VOICE_DIR / "jeremiah_reference.txt"

F5_TTS_DEVICE = os.getenv("F5_TTS_DEVICE", "cuda")
F5_TTS_MODEL = os.getenv("F5_TTS_MODEL", "").strip()


def _jeremiah_reference_text() -> str:
    env_text = os.getenv("JEREMIAH_F5_REF_TEXT")
    if env_text is not None:
        return env_text
    if DEFAULT_JEREMIAH_REFERENCE_TEXT_PATH.exists():
        return DEFAULT_JEREMIAH_REFERENCE_TEXT_PATH.read_text().strip()
    return ""


class VoiceConfig(BaseModel):
    ref_audio: Path
    ref_text: str


VOICE_REGISTRY: dict[str, VoiceConfig] = {
    "jeremiah": VoiceConfig(
        ref_audio=Path(os.getenv("JEREMIAH_F5_REF_AUDIO", str(DEFAULT_JEREMIAH_REFERENCE))),
        ref_text=_jeremiah_reference_text(),
    ),
}


class SynthesizeRequest(BaseModel):
    persona_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    ref_audio_override: str | None = None
    ref_text_override: str | None = None


app = FastAPI(title="Project Tango F5-TTS Server", version="1.0.0")
_tts = None
_tts_lock = asyncio.Lock()


def _load_f5_tts():
    global _tts
    if _tts is not None:
        return _tts

    try:
        from f5_tts import F5TTS
    except ImportError:
        from f5_tts.api import F5TTS

    _patch_torchaudio_wav_loader()

    kwargs = {"device": F5_TTS_DEVICE}
    if F5_TTS_MODEL:
        kwargs["model"] = F5_TTS_MODEL

    logger.info("Loading F5-TTS model device=%s model=%s", F5_TTS_DEVICE, F5_TTS_MODEL or "default")
    _tts = F5TTS(**kwargs)
    logger.info("F5-TTS model ready")
    return _tts


def _patch_torchaudio_wav_loader() -> None:
    import soundfile as sf
    import torch
    import torchaudio

    if getattr(torchaudio.load, "_tango_soundfile_wav_loader", False):
        return

    original_load = torchaudio.load

    def load_with_soundfile_for_wav(uri, *args, **kwargs):
        path = Path(uri) if isinstance(uri, str | Path) else None
        if path is None or path.suffix.lower() != ".wav" or not path.exists():
            return original_load(uri, *args, **kwargs)

        frame_offset = kwargs.get("frame_offset", 0)
        num_frames = kwargs.get("num_frames", -1)
        channels_first = kwargs.get("channels_first", True)
        frames = -1 if num_frames is None or num_frames < 0 else num_frames
        data, sample_rate = sf.read(
            str(path),
            dtype="float32",
            always_2d=True,
            start=frame_offset,
            frames=frames,
        )
        if channels_first:
            data = data.T
        return torch.from_numpy(data.copy()), sample_rate

    load_with_soundfile_for_wav._tango_soundfile_wav_loader = True
    torchaudio.load = load_with_soundfile_for_wav


@app.on_event("startup")
async def startup() -> None:
    await asyncio.to_thread(_load_f5_tts)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "model": "f5-tts",
        "device": F5_TTS_DEVICE,
        "voices": sorted(VOICE_REGISTRY),
    }


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Response:
    voice = VOICE_REGISTRY.get(req.persona_id)
    if voice is None and not req.ref_audio_override:
        raise HTTPException(status_code=404, detail=f"No F5-TTS voice registered for {req.persona_id!r}")

    ref_audio = Path(req.ref_audio_override) if req.ref_audio_override else voice.ref_audio
    ref_text = req.ref_text_override if req.ref_text_override else voice.ref_text
    if not ref_audio.exists():
        raise HTTPException(status_code=500, detail=f"Reference audio not found: {ref_audio}")
    if not ref_text.strip():
        raise HTTPException(
            status_code=500,
            detail="Reference transcript is empty; run scripts/extract_jeremiah_reference.py or set JEREMIAH_F5_REF_TEXT.",
        )

    started = time.perf_counter()
    output_path = ""
    try:
        fd, output_path = tempfile.mkstemp(prefix=f"tango_tts_{req.persona_id}_", suffix=".wav")
        os.close(fd)

        async with _tts_lock:
            tts = _load_f5_tts()
            await asyncio.to_thread(
                tts.infer,
                ref_file=str(ref_audio),
                ref_text=ref_text,
                gen_text=req.text,
                file_wave=output_path,
                show_info=logger.info,
            )

        audio_bytes = Path(output_path).read_bytes()
    except Exception as exc:
        logger.exception("F5-TTS synthesis failed persona=%s", req.persona_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if output_path:
            Path(output_path).unlink(missing_ok=True)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Synthesized %d chars for persona=%s bytes=%d elapsed_ms=%d",
        len(req.text),
        req.persona_id,
        len(audio_bytes),
        elapsed_ms,
    )
    return Response(content=audio_bytes, media_type="audio/wav")
