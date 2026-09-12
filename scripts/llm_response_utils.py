"""Helpers for pulling text out of LiteLLM / OpenAI-style chat completions.

Shared by the fleet AutoUpdater loops so empty `message.content` is not
silently treated as "no proposals, all systems optimal."
"""
from __future__ import annotations


def _coerce_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
        return "".join(parts).strip()
    return str(content).strip()


def extract_llm_text(response: dict | None) -> str:
    """Return the best available text from a chat-completions payload.

    Handles string content, list-of-parts content, and reasoning fields
    some models populate instead of `message.content`.
    """
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    msg = choices[0].get("message") or {}
    if not isinstance(msg, dict):
        return ""
    text = _coerce_content(msg.get("content"))
    if text:
        return text
    for key in ("reasoning_content", "reasoning", "thinking"):
        text = _coerce_content(msg.get(key))
        if text:
            return text
    return ""


def describe_llm_response(response: dict | None) -> str:
    """Compact diagnostic for empty/odd LLM replies."""
    if not isinstance(response, dict):
        return f"non-dict response: {type(response).__name__}"
    choices = response.get("choices") or []
    finish = None
    keys: list = []
    if choices and isinstance(choices[0], dict):
        finish = choices[0].get("finish_reason")
        msg = choices[0].get("message") or {}
        if isinstance(msg, dict):
            keys = list(msg.keys())
    return (
        f"model={response.get('model')} finish={finish} msg_keys={keys} "
        f"usage={response.get('usage')} error={response.get('error')} "
        f"n_choices={len(choices)}"
    )