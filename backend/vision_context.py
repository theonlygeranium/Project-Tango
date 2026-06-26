from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("project-tango.vision")


DEFAULT_VISION_MODEL = "openai/gpt-4o-mini"
DEFAULT_VISION_OCR_MODEL = "openai/gpt-4o"
VISUAL_REFERENCE_TERMS = (
    "app",
    "camera",
    "current",
    "here",
    "image",
    "look",
    "now",
    "over here",
    "photo",
    "picture",
    "read",
    "screen",
    "see",
    "share",
    "show",
    "that",
    "this",
    "video",
    "visual",
    "webcam",
    "ano",
    "ito",
    "iyan",
    "larawan",
    "tingnan",
    "yan",
)
OCR_REFERENCE_TERMS = (
    "about window",
    "app",
    "application",
    "branding",
    "command",
    "copy",
    "directory",
    "editor",
    "error",
    "exact",
    "file",
    "filename",
    "folder",
    "ide",
    "identify",
    "interface",
    "line",
    "log",
    "menu",
    "menu bar",
    "number",
    "output",
    "paste",
    "prompt",
    "recognize",
    "repo",
    "repository",
    "read",
    "say",
    "says",
    "screen says",
    "software",
    "stderr",
    "stdout",
    "terminal",
    "text",
    "title bar",
    "toolbar",
    "uptime",
    "version",
    "what app",
    "what does it say",
    "what does that say",
    "what interface",
    "what software",
    "what window",
    "where am i",
    "which app",
    "which editor",
    "which software",
    "do you see it now",
    "there is the output",
)

CAMERA_SOURCE_VALUES = {1}
SCREEN_SHARE_SOURCE_VALUES = {3, 4}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using %s", name, value, default)
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using %s", name, value, default)
        return default


def _litellm_chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _contains_reference_term(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    for term in terms:
        normalized_term = term.lower()
        if " " in normalized_term:
            if normalized_term in normalized:
                return True
            continue

        if re.search(rf"\b{re.escape(normalized_term)}\b", normalized):
            return True
    return False


@dataclass(frozen=True)
class VisionContextConfig:
    enabled: bool
    model: str
    ocr_model: str
    base_url: str
    api_key: str
    max_tokens: int
    ocr_max_tokens: int
    timeout_seconds: float
    ocr_timeout_seconds: float
    frame_width: int
    frame_height: int
    ocr_frame_width: int
    ocr_frame_height: int
    max_frame_age_seconds: float
    injection_mode: str
    image_detail: str
    ocr_image_detail: str
    debug_summaries: bool

    @classmethod
    def from_env(cls, base_url: str, api_key: str) -> VisionContextConfig:
        return cls(
            enabled=_env_bool("TANGO_VISION_ENABLED", True),
            model=os.getenv("TANGO_VISION_MODEL", DEFAULT_VISION_MODEL).strip(),
            ocr_model=os.getenv("TANGO_VISION_OCR_MODEL", DEFAULT_VISION_OCR_MODEL).strip(),
            base_url=base_url,
            api_key=api_key,
            max_tokens=max(_env_int("TANGO_VISION_MAX_TOKENS", 120), 20),
            ocr_max_tokens=max(_env_int("TANGO_VISION_OCR_MAX_TOKENS", 220), 40),
            timeout_seconds=max(_env_float("TANGO_VISION_TIMEOUT_SECONDS", 8.0), 1.0),
            ocr_timeout_seconds=max(_env_float("TANGO_VISION_OCR_TIMEOUT_SECONDS", 14.0), 1.0),
            frame_width=max(_env_int("TANGO_VISION_FRAME_WIDTH", 768), 128),
            frame_height=max(_env_int("TANGO_VISION_FRAME_HEIGHT", 768), 128),
            ocr_frame_width=max(_env_int("TANGO_VISION_OCR_FRAME_WIDTH", 1536), 512),
            ocr_frame_height=max(_env_int("TANGO_VISION_OCR_FRAME_HEIGHT", 1536), 512),
            max_frame_age_seconds=max(_env_float("TANGO_VISION_MAX_FRAME_AGE_SECONDS", 10.0), 1.0),
            injection_mode=os.getenv("TANGO_VISION_INJECTION_MODE", "auto").strip().lower(),
            image_detail=os.getenv("TANGO_VISION_IMAGE_DETAIL", "auto").strip().lower(),
            ocr_image_detail=os.getenv("TANGO_VISION_OCR_IMAGE_DETAIL", "high").strip().lower(),
            debug_summaries=_env_bool("TANGO_VISION_DEBUG_SUMMARIES", False),
        )


class LiveVideoContext:
    def __init__(self, room: Any, config: VisionContextConfig):
        self.room = room
        self.config = config
        self._started = False
        self._video_stream: Any | None = None
        self._active_track: Any | None = None
        self._active_priority = 0
        self._active_source_label = "video"
        self._latest_frame: Any | None = None
        self._latest_frame_source = "video"
        self._latest_frame_at = 0.0
        self._tasks: list[asyncio.Task[Any]] = []

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def enabled(self) -> bool:
        return self.config.enabled and bool(self.config.model)

    def start(self) -> None:
        if self._started:
            return
        self._started = True

        if not self.enabled:
            logger.info("Tango vision context disabled.")
            return

        try:
            from livekit import rtc
        except Exception:
            logger.exception("LiveKit RTC import failed; vision context is unavailable.")
            return

        self._select_best_existing_track(rtc)

        @self.room.on("track_subscribed")
        def on_track_subscribed(track: Any, publication: Any, participant: Any) -> None:
            if getattr(track, "kind", None) == rtc.TrackKind.KIND_VIDEO:
                self._use_video_track(track, publication, participant)

        @self.room.on("track_unsubscribed")
        def on_track_unsubscribed(track: Any, publication: Any, participant: Any) -> None:
            del publication, participant
            if track is self._active_track:
                self._clear_active_stream()
                self._select_best_existing_track(rtc)

        logger.info(
            "Tango vision context enabled model=%s mode=%s frame=%sx%s",
            self.config.model,
            self.config.injection_mode,
            self.config.frame_width,
            self.config.frame_height,
        )

    async def aclose(self) -> None:
        stream = self._video_stream
        self._video_stream = None
        self._active_track = None
        self._active_priority = 0
        if stream is not None:
            await stream.aclose()

        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def describe_latest_frame(self, user_text: str) -> str | None:
        if not self.enabled or not self._should_describe(user_text):
            return None

        frame = self._latest_frame
        if frame is None:
            logger.info("Vision context requested but no video frame is available yet.")
            return None

        frame_age = time.monotonic() - self._latest_frame_at
        if frame_age > self.config.max_frame_age_seconds:
            logger.info("Skipping stale vision frame age=%.1fs", frame_age)
            return None

        mode = "ocr" if self._should_use_ocr(user_text) else "scene"
        try:
            data_url = self._encode_frame(frame, mode)
        except Exception:
            logger.exception("Could not encode LiveKit video frame for vision context.")
            return None

        try:
            summary = await asyncio.to_thread(
                self._request_summary,
                data_url,
                self._latest_frame_source,
                user_text,
                mode,
            )
        except Exception:
            logger.exception("Vision model request failed.")
            return None

        if not summary:
            return None

        logger.info(
            "Injected visual context mode=%s source=%s model=%s chars=%d",
            mode,
            self._latest_frame_source,
            self._model_for_mode(mode),
            len(summary),
        )
        if self.config.debug_summaries:
            logger.info(
                "Visual context summary mode=%s source=%s model=%s summary=%r",
                mode,
                self._latest_frame_source,
                self._model_for_mode(mode),
                self._debug_summary(summary),
            )
        context_kind = "Visual OCR context" if mode == "ocr" else "Visual context"
        return f"{context_kind} from the user's current {self._latest_frame_source}: {summary}"

    def _select_best_existing_track(self, rtc: Any) -> None:
        candidates: list[tuple[int, Any, Any, Any]] = []
        for participant in list(getattr(self.room, "remote_participants", {}).values()):
            publications = getattr(participant, "track_publications", {}) or {}
            for publication in list(publications.values()):
                track = getattr(publication, "track", None)
                if track is None or getattr(track, "kind", None) != rtc.TrackKind.KIND_VIDEO:
                    continue
                candidates.append(
                    (self._source_priority(publication, track, participant), track, publication, participant)
                )

        if not candidates:
            return

        _, track, publication, participant = sorted(candidates, key=lambda item: item[0])[-1]
        self._use_video_track(track, publication, participant)

    def _use_video_track(self, track: Any, publication: Any, participant: Any) -> None:
        priority = self._source_priority(publication, track, participant)
        if self._active_track is track:
            return
        if self._active_track is not None and priority < self._active_priority:
            return

        self._clear_active_stream()
        self._active_track = track
        self._active_priority = priority
        self._active_source_label = self._source_label(publication, track, participant)

        try:
            from livekit import rtc

            self._video_stream = rtc.VideoStream(track)
        except Exception:
            logger.exception("Could not create LiveKit video stream.")
            self._clear_active_stream()
            return

        task = asyncio.create_task(self._read_video_stream(self._video_stream, self._active_source_label))
        self._tasks.append(task)
        task.add_done_callback(self._remove_task)
        logger.info(
            "Tango vision subscribed to %s track source_hint=%s.",
            self._active_source_label,
            self._source_debug_hint(publication, track, participant),
        )

    async def _read_video_stream(self, stream: Any, source_label: str) -> None:
        try:
            async for event in stream:
                self._latest_frame = event.frame
                self._latest_frame_source = source_label
                self._latest_frame_at = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveKit video stream reader stopped unexpectedly.")

    def _clear_active_stream(self) -> None:
        stream = self._video_stream
        self._video_stream = None
        self._active_track = None
        self._active_priority = 0
        if stream is not None:
            asyncio.create_task(stream.aclose())

    def _remove_task(self, task: asyncio.Task[Any]) -> None:
        try:
            self._tasks.remove(task)
        except ValueError:
            return

    def _source_priority(
        self,
        publication: Any,
        track: Any | None = None,
        participant: Any | None = None,
    ) -> int:
        label = self._source_label(publication, track, participant)
        if label == "screen share":
            return 3
        if label == "camera":
            return 2
        return 1

    def _source_label(
        self,
        publication: Any,
        track: Any | None = None,
        participant: Any | None = None,
    ) -> str:
        for value in self._source_values(publication, track, participant):
            numeric_value = self._numeric_source_value(value)
            if numeric_value in SCREEN_SHARE_SOURCE_VALUES:
                return "screen share"
            if numeric_value in CAMERA_SOURCE_VALUES:
                return "camera"

        source_text = " ".join(self._source_text_values(publication, track, participant)).lower()
        if any(term in source_text for term in ("screen", "screenshare", "screen_share", "display")):
            return "screen share"
        if any(term in source_text for term in ("camera", "webcam")):
            return "camera"
        return "video"

    def _source_values(
        self,
        publication: Any,
        track: Any | None = None,
        participant: Any | None = None,
    ) -> list[Any]:
        candidates: list[Any] = []
        for owner, attributes in (
            (publication, ("source", "_source")),
            (track, ("source", "_source")),
            (getattr(publication, "_info", None), ("source", "track_source")),
            (getattr(track, "_info", None), ("source", "track_source")),
        ):
            if owner is None:
                continue
            for attribute in attributes:
                if hasattr(owner, attribute):
                    candidates.append(getattr(owner, attribute))

        del participant
        return candidates

    def _source_text_values(
        self,
        publication: Any,
        track: Any | None = None,
        participant: Any | None = None,
    ) -> list[str]:
        values: list[str] = []
        for value in self._source_values(publication, track, participant):
            values.extend(self._stringify_source_value(value))

        for owner, attributes in (
            (publication, ("name", "sid", "track_sid", "track_name")),
            (track, ("name", "sid")),
            (getattr(publication, "_info", None), ("name", "sid", "track_sid", "track_name")),
            (getattr(track, "_info", None), ("name", "sid")),
            (participant, ("identity", "name")),
        ):
            if owner is None:
                continue
            for attribute in attributes:
                value = getattr(owner, attribute, None)
                if value is not None:
                    values.append(str(value))

        return values

    def _stringify_source_value(self, value: Any) -> list[str]:
        if value is None:
            return []

        parts = [str(value)]
        for attribute in ("name", "value"):
            attribute_value = getattr(value, attribute, None)
            if attribute_value is not None:
                parts.append(str(attribute_value))
        return parts

    def _numeric_source_value(self, value: Any) -> int | None:
        if isinstance(value, int):
            return int(value)

        raw_value = getattr(value, "value", None)
        if isinstance(raw_value, int):
            return int(raw_value)

        if isinstance(value, str) and value.isdigit():
            return int(value)
        if isinstance(raw_value, str) and raw_value.isdigit():
            return int(raw_value)

        return None

    def _source_debug_hint(
        self,
        publication: Any,
        track: Any | None = None,
        participant: Any | None = None,
    ) -> str:
        values = [value for value in self._source_text_values(publication, track, participant) if value]
        if not values:
            return "unavailable"
        return " | ".join(values)[:300]

    def _should_describe(self, user_text: str) -> bool:
        mode = self.config.injection_mode
        if mode in {"always", "all"}:
            return True
        if mode in {"off", "never", "false"}:
            return False

        return _contains_reference_term(user_text, VISUAL_REFERENCE_TERMS)

    def _should_use_ocr(self, user_text: str) -> bool:
        return _contains_reference_term(user_text, OCR_REFERENCE_TERMS)

    def _model_for_mode(self, mode: str) -> str:
        if mode == "ocr" and self.config.ocr_model:
            return self.config.ocr_model
        return self.config.model

    def _image_detail_for_mode(self, mode: str) -> str:
        if mode == "ocr":
            return self.config.ocr_image_detail
        return self.config.image_detail

    def _max_tokens_for_mode(self, mode: str) -> int:
        if mode == "ocr":
            return self.config.ocr_max_tokens
        return self.config.max_tokens

    def _timeout_for_mode(self, mode: str) -> float:
        if mode == "ocr":
            return self.config.ocr_timeout_seconds
        return self.config.timeout_seconds

    def _frame_size_for_mode(self, mode: str) -> tuple[int, int]:
        if mode == "ocr":
            return self.config.ocr_frame_width, self.config.ocr_frame_height
        return self.config.frame_width, self.config.frame_height

    def _encode_frame(self, frame: Any, mode: str) -> str:
        from livekit.agents.utils.images import EncodeOptions, ResizeOptions, encode

        width, height = self._frame_size_for_mode(mode)
        image_bytes = encode(
            frame,
            EncodeOptions(
                format="JPEG",
                resize_options=ResizeOptions(
                    width=width,
                    height=height,
                    strategy="scale_aspect_fit",
                ),
            ),
        )
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def _system_prompt_for_mode(self, mode: str) -> str:
        if mode == "ocr":
            return (
                "You provide OCR-style visual context for a voice assistant. Read visible "
                "terminal, code, UI, or document text that is relevant to the user's latest "
                "turn. Preserve exact commands, numbers, filenames, and error text when "
                "visible. For software or editor identification questions, inspect visible "
                "app names, browser tabs, title bars, menus, sidebars, logos, URLs, and "
                "workspace labels. Distinguish Codex, ChatGPT/Codex desktop, VS Code, and "
                "GitHub Codespaces only from visible evidence; state uncertainty when the "
                "branding is not readable. Do not guess text that is too small or blurry; "
                "say what is unreadable. Keep the answer under 90 words."
            )

        return (
            "You produce compact visual context for a voice assistant. "
            "Describe only visible details that help answer the user's latest turn. "
            "If the user asks what app, software, code editor, or interface is visible, "
            "identify the visible clues first and avoid overconfident product guesses; "
            "Codex, ChatGPT/Codex desktop, VS Code, and GitHub Codespaces can look similar. "
            "If the frame is unreadable or irrelevant, say so briefly. "
            "Keep the answer under 45 words."
        )

    def _user_prompt_for_mode(self, source_label: str, user_text: str, mode: str) -> str:
        if mode == "ocr":
            return (
                f"The user is sharing their {source_label}. "
                f"The user just said: {user_text[:500]!r}. "
                "Extract the exact visible text or command output needed to answer them. "
                "For interface identification, prioritize readable app chrome, tab titles, "
                "menus, URL bars, window titles, and workspace labels. "
                "Then add a very short explanation only if it helps."
            )

        return (
            f"The user is sharing their {source_label}. "
            f"The user just said: {user_text[:500]!r}. "
            "Summarize the useful visual context."
        )

    def _debug_summary(self, summary: str) -> str:
        compact = " ".join(summary.split())
        if len(compact) <= 700:
            return compact
        return f"{compact[:697]}..."

    def _request_summary(
        self,
        image_data_url: str,
        source_label: str,
        user_text: str,
        mode: str,
    ) -> str | None:
        model = self._model_for_mode(mode)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt_for_mode(mode),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self._user_prompt_for_mode(source_label, user_text, mode),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url,
                                "detail": self._image_detail_for_mode(mode),
                            },
                        },
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": self._max_tokens_for_mode(mode),
        }
        request = urllib.request.Request(
            _litellm_chat_completions_url(self.config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_for_mode(mode)) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            logger.warning("Vision model HTTP %s mode=%s model=%s: %s", exc.code, mode, model, detail)
            return None

        choices = body.get("choices") or []
        if not choices:
            logger.warning("Vision model returned no choices.")
            return None

        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            logger.warning("Vision model returned non-text content.")
            return None

        return content.strip() or None
