"""LiteLLM client wrapper — routes all LLM calls through LiteLLM proxy.

All calls go through http://localhost:4000 (LiteLLM proxy) using the
CircuitBreakerManager.call_llm under key llm:<model>. Every call is
logged to the flywheel via the Nexus Bus (flywheel.llm_call event).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import litellm

from nexus.bus.event import EventType, NexusEvent

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper around litellm.acompletion with circuit-breaker and flywheel logging."""

    DEFAULT_BASE_URL: str = "http://localhost:4000"
    DEFAULT_MODEL: str = "writer/palmyra-x6"

    def __init__(
        self,
        breakers: Any,
        nexus: Any,
        base_url: str = DEFAULT_BASE_URL,
        default_model: str = DEFAULT_MODEL,
        logger: logging.Logger | None = None,
    ) -> None:
        self._breakers = breakers
        self._nexus = nexus
        self._base_url = base_url
        self._default_model = default_model
        self._logger = logger or logging.getLogger(__name__)

    async def call(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        fallback_models: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call LLM through circuit breaker with fallback chain.

        Primary route: http://localhost:4000 (LiteLLM proxy)
        Default model: writer/palmyra-x6
        Every call wrapped by CircuitBreakerManager.call_llm under key llm:<model>
        Every call logged to flywheel via Nexus Bus (flywheel.llm_call event)
        """
        resolved_model = model or self._default_model
        models_to_try = [resolved_model]
        if fallback_models:
            models_to_try.extend(fallback_models)

        last_error: str | None = None
        for m in models_to_try:
            try:
                raw = await self._breakers.call_llm(
                    m,
                    litellm.acompletion,
                    model=m,
                    messages=messages,
                    api_base=self._base_url,
                    **kwargs,
                )
                response = self._parse(raw, m)
                await self._log_call(m, messages, response, success=True)
                return response
            except Exception as e:
                last_error = str(e)
                self._logger.warning("LLM call to model '%s' failed: %s", m, e)
                await self._log_call(m, messages, None, success=False, error=last_error)

        raise RuntimeError(
            f"All LLM models failed (tried {models_to_try}). Last error: {last_error}"
        )

    def _parse(self, raw: Any, model: str) -> Any:
        """Parse the raw litellm response into a normalized shape."""
        try:
            choice = raw.choices[0]
            content = choice.message.content if choice.message else ""
            return {
                "model": model,
                "content": content,
                "raw": raw,
            }
        except (AttributeError, IndexError, KeyError) as e:
            self._logger.error("Failed to parse LLM response: %s", e)
            return {
                "model": model,
                "content": "",
                "raw": raw,
            }

    async def _log_call(
        self,
        model: str,
        messages: list,
        response: Any,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Log the LLM call to the flywheel via the Nexus Bus."""
        try:
            prompt_tokens = 0
            completion_tokens = 0
            latency_ms = 0

            if success and response is not None and response.get("raw") is not None:
                raw = response["raw"]
                usage = getattr(raw, "usage", None)
                if usage is not None:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "completion_tokens", 0) or 0

            event = NexusEvent.create(
                event_type=EventType.FLYWHEEL_LLM_CALL,
                source="llm_client",
                target="broadcast",
                payload={
                    "bot_id": "llm_client",
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "latency_ms": latency_ms,
                    "success": success,
                    "error": error,
                },
            )
            await self._nexus.publish(event)
        except Exception as e:
            self._logger.debug("Failed to log LLM call to flywheel: %s", e)
