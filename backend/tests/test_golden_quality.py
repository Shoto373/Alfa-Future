"""Порог качества разборов на golden set (tests/golden/cases.json) в режиме правил — проверяется в CI.

Ожидания golden set записаны до прогона и не подгоняются под результат. Полный отчет и LLM-прогон:
python -m app.eval_quality --set tests/golden --mode rules|llm --md report.md
"""

import asyncio
from pathlib import Path

from app import eval_quality

GOLDEN = Path(__file__).with_name("golden")


def test_golden_set_is_complete():
    cases = eval_quality.load_golden(GOLDEN)
    assert len(cases) >= 30 and len({c["id"] for c in cases}) == len(cases)
    topics = {t for c in cases for t in c["expect"]["topics"]}
    assert {"key_rate", "fx", "sanctions_geopolitics", "fuel_oil", "metals_steel", "logistics"} <= topics
    assert any(c["expect"]["effect"] == "none" for c in cases), "есть новости не про бизнес"


def test_rules_quality_meets_bar(company):
    s = asyncio.run(eval_quality.run_golden(eval_quality.load_golden(GOLDEN), "rules"))["summary"]
    assert s["errors"] == 0, s
    assert s["first_pass_rate"] >= 0.8, s          # критерий SPR2-04
    assert s["sourced_rate"] == 1.0, s             # 100% выводов со ссылкой на собранный источник
    assert s["forbidden_ok"] == 1.0, s
    assert s["topic_match"] >= 0.9 and s["sign_match"] >= 0.9, s
    # Без embedding-модели (CI) тезис ищется только по словам; на проде с моделью — 100% на golden set.
    assert s["bank_coverage"] >= 0.85, s
