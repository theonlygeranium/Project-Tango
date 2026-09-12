"""Approval button helpers (2026-08-22)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path("/opt/Project-Tango")
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from approval_buttons import (  # noqa: E402
    PROCEED_TEXT,
    looks_like_approval_request,
    looks_like_completion,
    progress_anchor,
    should_attach_proceed,
)


def test_proceed_text_is_explicit():
    assert "proceed" in PROCEED_TEXT.lower()
    assert "plan" in PROCEED_TEXT.lower()


def test_detects_shall_i_proceed():
    assert looks_like_approval_request(
        "I can patch those three files. Shall I proceed with the implementation?"
    )
    assert looks_like_approval_request("Want me to apply this patch?")
    assert looks_like_approval_request("Ready to implement. Awaiting your approval.")


def test_ignores_status_updates():
    assert not looks_like_approval_request("**Fixed.**")
    assert not looks_like_approval_request("Fleet is healthy. All seven bots are running.")


def test_should_attach_proceed_skips_errors():
    assert should_attach_proceed("## Situation Report\nI can add automation. Proceed?")
    assert not should_attach_proceed("⏹️ Task cancelled.")
    assert not should_attach_proceed("❌ Error: boom")


def test_should_attach_proceed_skips_completed_work():
    assert looks_like_completion("**Implementation complete.**\n### What was delivered")
    assert looks_like_completion("**Summary of what was accomplished:**\n### ✅ Completed")
    assert looks_like_completion("**Done.** The auto-patch automation is now live.")
    assert not should_attach_proceed("**Implementation complete.**\n### What was delivered")
    assert not should_attach_proceed("**Summary of what was accomplished:**")
    assert should_attach_proceed(
        "Now I have the complete picture. Here's my analysis and recommendation."
    )


def test_progress_anchor_reuses_existing_thread():
    thread = SimpleNamespace(id=99)
    source = SimpleNamespace(thread=thread, id=1)
    assert progress_anchor(source) is thread
    bare = SimpleNamespace(id=2, thread=None)
    assert progress_anchor(bare) is bare


def test_bots_import_approval_buttons():
    for name in ("architect-bot.py", "proctor-bot.py", "dr-voss-bot.py"):
        tree = ast.parse((SCRIPTS / name).read_text())
        imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "approval_buttons":
                imported = True
        assert imported, name
        src = (SCRIPTS / name).read_text()
        assert "on_proceed=_on_proceed_click" in src
        assert "progress_anchor(" in src
        assert "PROCEED_TEXT" in src