"""Guard against logger calls whose %-placeholders do not match their arguments.

Python logging defers formatting until a handler emits the record. When the
placeholder count is wrong, the record is dropped and a traceback goes to
stderr instead of the journal. Tango shipped 13 such calls (``pcts`` instead
of ``%s``), which hid every Control Mode, program, and TTS-fallback event.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
# %% is a literal percent; everything else that starts with % is a placeholder.
PLACEHOLDER = re.compile(r"%(?!%)[-#0 +]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[sdirfgexXoc]")


def _backend_sources() -> list[Path]:
    return sorted(
        path
        for path in BACKEND.glob("*.py")
        if path.is_file() and not path.is_symlink()
    )


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    target = func.value
    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
    return "log" in name.lower()


def _mismatches(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_logger_call(node):
            continue
        if not node.args:
            continue
        message = node.args[0]
        if not (isinstance(message, ast.Constant) and isinstance(message.value, str)):
            continue
        if any(isinstance(arg, ast.Starred) for arg in node.args[1:]):
            continue
        expected = len(PLACEHOLDER.findall(message.value))
        supplied = len(node.args) - 1
        if expected != supplied:
            problems.append(
                f"{path.name}:{node.lineno}: {expected} placeholder(s), "
                f"{supplied} argument(s): {message.value!r}"
            )
    return problems


@pytest.mark.parametrize("path", _backend_sources(), ids=lambda p: p.name)
def test_logger_placeholders_match_arguments(path: Path) -> None:
    assert _mismatches(path) == []


def test_checker_detects_pcts_regression(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text('logger.info("Control Mode enabled persona=pcts tools=pctd", a, b)\n')
    assert len(_mismatches(sample)) == 1
