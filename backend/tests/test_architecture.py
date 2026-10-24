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


def test_checker_flags_imports_only_inside_functions(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "config.py").write_text("try:\n    import json\nexcept ImportError:\n    json = None\n\n\ndef f():\n"
                                   "    import os\n    import math  # optional\n    return os, math\n", encoding="utf-8")
    monkeypatch.setattr(check_imports, "ROOT", tmp_path)
    monkeypatch.setattr(check_imports, "APP", app)
    _, problems = check_imports.analyze()
    assert [p for p in problems if "импорт" in p] == ["app.config:8: импорт внутри функции (os) — перенесите в начало модуля"]


def test_checker_catches_cycles_and_upward_imports():
    assert check_imports.cycles({"a": {"b"}, "b": {"a"}, "c": {"a"}}) == [["a", "b"]]
    assert check_imports.layer_of("app.news.store") < check_imports.layer_of("app.agent.orchestrator")
    assert check_imports.layer_of("app.auth.store") < check_imports.layer_of("app.auth.router")
