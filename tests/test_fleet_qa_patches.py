"""Regression tests for Proctor-QA fleet bugs (2026-08-22)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path("/opt/Project-Tango")
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from response_scoring import calculate_response_score  # noqa: E402


VOSS_ID = 1539047086597873684
PROCTOR_ID = 1539047471899086988
ADMIN_ID = 1075596247966167131


def test_direct_mention_scores_one():
    score = calculate_response_score(
        message_content=f"<@{VOSS_ID}> [PROCTOR-QA] Confirm you are dr_voss.",
        agent_name="dr_voss",
        bot_user_id=VOSS_ID,
        message_author_id=PROCTOR_ID,
        admin_user_id=ADMIN_ID,
        is_bot_message=True,
        mentioned_user_ids=[VOSS_ID],
    )
    assert score == 1.0


def test_raw_mention_without_cache_scores_one():
    score = calculate_response_score(
        message_content=f"<@{VOSS_ID}> ping",
        agent_name="dr_voss",
        bot_user_id=VOSS_ID,
        message_author_id=PROCTOR_ID,
        admin_user_id=ADMIN_ID,
        is_bot_message=True,
        mentioned_user_ids=[],
    )
    assert score == 1.0


def test_other_agent_mention_is_not_forced():
    architect_id = 1538766501035642890
    score = calculate_response_score(
        message_content=f"<@{architect_id}> [PROCTOR-QA] Confirm you are architect.",
        agent_name="dr_voss",
        bot_user_id=VOSS_ID,
        message_author_id=PROCTOR_ID,
        admin_user_id=ADMIN_ID,
        is_bot_message=True,
        mentioned_user_ids=[architect_id],
    )
    assert score < 0.5


def _calls_undefined_run_agent_loop(filename: str) -> list[int]:
    tree = ast.parse((SCRIPTS / filename).read_text())
    defined = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run_agent_loop":
            if "run_agent_loop" not in defined:
                bad.append(n.lineno)
    return bad


def test_quartermaster_does_not_call_missing_run_agent_loop():
    assert _calls_undefined_run_agent_loop("quartermaster-bot.py") == []


def test_cartographer_does_not_call_missing_run_agent_loop():
    assert _calls_undefined_run_agent_loop("cartographer-bot.py") == []


def test_admiral_authorizes_fleet_agents():
    src = (SCRIPTS / "schubert-bot-v2.py").read_text()
    assert "AUTHORIZED_AGENT_IDS" in src
    assert "is_authorized_agent" in src
    assert "is_senior" in src
