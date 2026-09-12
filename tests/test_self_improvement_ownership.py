"""Guard the AutoUpdater ownership split after the Nexus rebuild.

Proctor owns itself + Admiral. Architect owns itself. Voss owns itself.
Nobody races on architect-bot.py / schubert-bot-v2.py anymore.
"""
from pathlib import Path
import re

SCRIPTS = Path("/opt/Project-Tango/scripts")


def _block(name: str) -> str:
    src = (SCRIPTS / name).read_text()
    m = re.search(r"OPTIMIZATION_TARGETS = \{.*?\n\}", src, re.S)
    assert m, f"OPTIMIZATION_TARGETS not found in {name}"
    return m.group(0)


def _keys(name: str) -> set[str]:
    return set(re.findall(r'\n    "([a-z_]+)": \{', _block(name)))


def test_proctor_owns_self_and_admiral():
    block = _block("proctor-bot.py")
    assert _keys("proctor-bot.py") == {"proctor", "schubert"}
    assert "architect-bot.py" not in block
    assert "schubert-proctor" in block
    assert "schubert-bot" in block
    assert '"can_restart_self": True' in block
    assert '"can_restart_self": False' in block


def test_architect_owns_self_only():
    block = _block("architect-bot.py")
    assert _keys("architect-bot.py") == {"architect"}
    assert "schubert-bot-v2.py" not in block
    assert "schubert-architect" in block


def test_voss_owns_self_only():
    block = _block("dr-voss-bot.py")
    assert _keys("dr-voss-bot.py") == {"dr_voss"}
    assert "architect-bot.py" not in block
    assert "schubert-bot-v2.py" not in block
    assert "VOSS_SCRIPT_PATH" in block
    src = (SCRIPTS / "dr-voss-bot.py").read_text()
    assert 'VOSS_SCRIPT_PATH = "/opt/Project-Tango/scripts/dr-voss-bot.py"' in src
    assert "schubert-dr-voss" in block


def test_file_size_cap_covers_current_bots():
    """200KB cap was smaller than Architect (207KB) and Proctor (229KB)."""
    for name in ("proctor-bot.py", "architect-bot.py", "dr-voss-bot.py"):
        src = (SCRIPTS / name).read_text()
        assert (
            "512 * 1024" in src
            or "512*1024" in src
            or "524288" in src
        ), f"{name} still uses the 200KB auto-update cap"


def test_proctor_uses_own_metrics_files():
    src = (SCRIPTS / "proctor-bot.py").read_text()
    assert ".proctor-metrics.json" in src
    assert 'METRICS_FILE = "/opt/Project-Tango/scripts/.architect-metrics.json"' not in src


def test_voss_uses_own_metrics_files():
    src = (SCRIPTS / "dr-voss-bot.py").read_text()
    assert ".voss-metrics.json" in src
    assert 'METRICS_FILE = "/opt/Project-Tango/scripts/.architect-metrics.json"' not in src


def test_empty_content_is_hard_failure():
    src = (SCRIPTS / "proctor-bot.py").read_text()
    assert "not treating as all-clear" in src
    assert "extract_llm_text" in src
    assert "describe_llm_response" in src


def test_weekly_analysis_persists_last_run():
    src = (SCRIPTS / "proctor-bot.py").read_text()
    assert ".proctor-weekly-analysis.json" in src
    assert "await asyncio.sleep(7 * 24 * 60 * 60)" not in src