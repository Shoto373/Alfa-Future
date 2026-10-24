import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import date, datetime, timezone

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import select, func
from app.models import BankProduct

from app import database, llm, llm_usage, storage
from app.agent import orchestrator
from app.companies import profiles
from app.knowledge import kb
from app.news import store


def saved(client, company):
    insight = asyncio.run(orchestrator.run(company, "cfo", store.get("seed-rate-hold"), "req_db"))
    storage.save_insight(insight)
    return insight


def test_migrations_are_idempotent_and_transactional():
    database.migrate()
    database.migrate()
    with database.session() as conn:
        context = MigrationContext.configure(conn.connection(), opts={"version_table_schema": database.schema()})
        assert context.get_current_revision() == "0017"
    with pytest.raises(RuntimeError):
        with database.session() as conn:
            database.set_state("rollback_probe", {"value": 1}, conn)
            raise RuntimeError("rollback")
    assert database.state("rollback_probe") is None


def test_insights_history_feedback_answers_survive_cache_reset(client, company):
    first = saved(client, company)
    second = saved(client, company)
    storage.add_feedback({"insight_id": first["insight_id"], "rating": 1})
    storage.save_answer({"insight_id": first["insight_id"], "question": "Источники?", "answer": "Список"})
    profiles.reset_cache()
    store.reset_cache()
    kb._index.cache_clear()
    assert storage.get_insight(first["insight_id"]) == first
    assert storage.get_insight(second["insight_id"]) == second
    assert len(storage._read("answers")) == 1
    assert storage.metrics()["personalization"]["feedback"]["up"] == 1


def test_concurrent_events_and_usage_are_not_lost():
    def write(i):
        storage.log_event("probe", index=i)
        llm_usage.commit(llm_usage.reserve("deepseek-v4.1-flash", 30, 10), 3, 0.01)
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(write, range(20)))
    assert len(storage._read("events")) == 20
    usage = llm.usage()
    assert usage["tokens"] == 60 and usage["cost"] == 0.2 and usage["calls"] == 20
    assert usage["reserved_tokens"] == 0 and usage["reserved_cost"] == 0


def test_llm_budget_uses_utc_day_and_persistent_usage(monkeypatch):
    from app.models import LLMUsage

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # 00:30 Moscow on Oct 22 is still Oct 21 in the gateway budget.
            return datetime(2026, 10, 21, 21, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(llm_usage, "datetime", FrozenDatetime)
    assert llm_usage.budget_day() == date(2026, 10, 21)
    llm_usage.commit(llm_usage.reserve("deepseek-v4.1-flash", 30, 10), 7, 0.1)
    assert llm.usage()["date"] == "2026-10-21"
    assert llm.usage()["tokens"] == 7
    with database.session() as db:
        assert db.get(LLMUsage, date(2026, 10, 21)).tokens == 7


def test_news_concurrent_dedup_survives_reset():
    item = store.make_item("ЦБ сохранил ключевую ставку", "Банк России сохранил ключевую ставку на уровне 14%. Условия нового кредитования не изменились.", "Проверка")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.add(item), range(8)))
    assert sum(created for _, created in results) == 1
    store.reset_cache()
    assert store.get(item["news_id"])["text"] == item["text"]


def test_knowledge_import_and_review_manifest():
    assert len(kb.documents()) == 9
    manifest = json.loads(Path(kb.__file__).with_name("review.json").read_text(encoding="utf-8"))
    assert len(manifest["theses"]) == 43
    for row in manifest["theses"]:
        t = kb.thesis(row["thesis_id"])
        assert hashlib.sha256(t["text"].encode()).hexdigest() == row["text_sha256"]
        assert 1 <= row["page"] <= row["pdf_pages"]
        assert "???" not in t["text"]
    with database.session() as conn:
        assert conn.scalar(select(func.count()).select_from(BankProduct)) == 8


def test_forecasts_compare_same_metric_and_horizon():
    from app.agent.tools import _forecasts
    changes = _forecasts(["key_rate"])
    rate = next(c for c in changes if c["metric"] == "key_rate:2026-12-31")
    assert rate["kind"] == "revision"
    assert rate["items"][0]["value"] == 14 and rate["items"][1]["value"] == 13.5
    assert not any(c["metric"] == "key_rate:2027-12-31" for c in changes)
    assert "fi-03" not in {t["id"] for t in kb.search("ставка ЦБ", topics=["key_rate"], limit=100)}
    assert not kb.search("Госдума открыла данные ЕГРЮЛ для компаний после исчезновения санкционных рисков", topics=["sanctions_geopolitics"])


def test_client_contradiction_is_removed(client, company):
    from app.agent import composer, validators
    c = dict(company, products=company["products"] | {"loans": False})
    ctx = {"news": store.get("seed-rate-hold"), "company": c, "role": "cfo", "exposures": [], "theses": [], "products": []}
    draft = composer.compose(ctx)
    draft["risks"].append({"text": "У компании есть кредит", "origin": "ai", "source_ids": ["client:profile"], "features": []})
    ids = {"client:profile", "client:payments", "news:seed-rate-hold"}
    checks = validators.check(draft, ctx, ids, "")
    assert not next(r for r in checks if r["name"] == "consistent_with_client")["passed"]
    validators.apply_fix(draft, checks, ids, "", ctx)
    assert all(cl["text"] != "У компании есть кредит" for cl in draft["risks"])


def test_source_specific_numbers_cannot_borrow_from_other_thesis(client, company):
    from app.agent.validators import claim_errors
    ctx = {"news": store.get("seed-rate-hold"), "company": company, "theses": [kb.thesis("rate-05"), kb.thesis("bond-04")]}
    cl = {"text": "Банк ожидает долг 412 млрд", "origin": "ai", "source_ids": ["bank:rate-05"], "features": []}
    assert "numbers" in claim_errors("risks", cl, ctx, {"bank:rate-05", "bank:bond-04"})


def test_legacy_import_is_idempotent(tmp_path):
    from app.legacy_import import import_runtime
    (tmp_path / "events.jsonl").write_text('{"kind":"feed_view","company_id":"U_1"}\n', encoding="utf-8")
    assert import_runtime(tmp_path)["events"] == 1
    assert import_runtime(tmp_path)["events"] == 0


def test_headline_and_bank_summary_are_checked_and_repaired(client, company):
    from app.agent import composer, validators
    ctx = {"news": store.get("seed-rate-hold"), "company": company, "role": "cfo",
           "exposures": [e for e in profiles.exposures(company["company_id"]) if e["topic"] == "key_rate"],
           "theses": [kb.thesis("rate-05")], "products": [], "bank_search_complete": True}
    draft = composer.compose(ctx)
    original_headline = draft["headline"]
    draft["headline"] = "Долг компании вырастет на 999 млрд рублей"
    draft["bank_view"]["summary"] = "Банк гарантирует прибыль 999%"
    ids = {"client:profile", "client:payments", "news:seed-rate-hold", "bank:rate-05"}
    checks = validators.check(draft, ctx, ids, "")
    assert not next(c for c in checks if c["name"] == "headline_grounded")["passed"]
    assert not next(c for c in checks if c["name"] == "bank_summary_grounded")["passed"]
    validators.apply_fix(draft, checks, ids, "", ctx)
    assert draft["headline"] == original_headline
    assert draft["bank_view"]["summary"] == kb.thesis("rate-05")["text"]


def test_demo_precomputation_uses_active_dataset(client):
    from app.demo import prepare
    result = asyncio.run(prepare(rules=True, synthetic=True))
    assert result["synthetic"] and len(result["items"]) >= 4
    assert all(i["quality_passed"] for i in result["items"])
    again = asyncio.run(prepare(rules=True, synthetic=True))
    assert [i["insight_id"] for i in again["items"]] == [i["insight_id"] for i in result["items"]]
