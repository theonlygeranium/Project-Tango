"""Unit tests for scripts/llm_response_utils.py"""
import importlib.util
from pathlib import Path

UTILS = Path("/opt/Project-Tango/scripts/llm_response_utils.py")


def _load():
    spec = importlib.util.spec_from_file_location("llm_response_utils", UTILS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_string_content():
    u = _load()
    resp = {"choices": [{"message": {"content": "  [{\"ok\": true}]  "}}]}
    assert u.extract_llm_text(resp) == '[{"ok": true}]'


def test_extract_list_parts():
    u = _load()
    resp = {"choices": [{"message": {"content": [{"type": "text", "text": "["}, {"text": "]"}]}}]}
    assert u.extract_llm_text(resp) == "[]"


def test_extract_reasoning_fallback():
    u = _load()
    resp = {"choices": [{"message": {"content": "", "reasoning_content": "[1]"}}]}
    assert u.extract_llm_text(resp) == "[1]"


def test_extract_empty_is_empty():
    u = _load()
    assert u.extract_llm_text({"choices": [{"message": {"content": ""}}]}) == ""
    assert u.extract_llm_text({"choices": []}) == ""
    assert u.extract_llm_text(None) == ""
    assert u.extract_llm_text({"error": "nope"}) == ""


def test_describe_includes_finish_reason():
    u = _load()
    desc = u.describe_llm_response({
        "model": "writer/palmyra-x6",
        "choices": [{"finish_reason": "stop", "message": {"content": None, "role": "assistant"}}],
        "usage": {"total_tokens": 12},
    })
    assert "finish=stop" in desc
    assert "palmyra-x6" in desc
    assert "role" in desc