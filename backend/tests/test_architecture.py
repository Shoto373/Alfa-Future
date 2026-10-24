"""Архитектура backend (SPR2-01): слои без циклов, импорты в начале модулей, функции до 80 строк.

Правила и список слоев — tools/check_imports.py; тест ловит регресс в CI.
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("check_imports", Path(__file__).resolve().parents[1] / "tools" / "check_imports.py")
check_imports = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_imports)


def test_architecture_has_no_violations():
    _, problems = check_imports.analyze()
    assert problems == [], "\n".join(problems)


def test_checker_catches_cycles_and_upward_imports():
    assert check_imports.cycles({"a": {"b"}, "b": {"a"}, "c": {"a"}}) == [["a", "b"]]
    assert check_imports.layer_of("app.news.store") < check_imports.layer_of("app.agent.orchestrator")
    assert check_imports.layer_of("app.auth.store") < check_imports.layer_of("app.auth.router")
