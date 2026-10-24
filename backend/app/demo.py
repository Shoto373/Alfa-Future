"""Prepare contrasting, checked demo insights in the active PostgreSQL dataset.

Run with --rules for an offline demonstration. Reuses valid cached analyses;
--refresh intentionally builds new history entries.
"""
import argparse
import asyncio
import json
import os
import uuid

from app import database, storage
from app.agent import orchestrator
from app.companies import profiles
from app.knowledge import kb
from app.news import store


async def prepare(rules: bool = False, refresh: bool = False, synthetic: bool = False) -> dict:
    if rules:
        os.environ.pop("LLM_API_KEY", None)
    database.migrate()
    meta = profiles.meta()
    if synthetic and not meta["synthetic"]:
        raise ValueError("Active dataset is not synthetic; omit --synthetic to explicitly use the active case data")
    kb.documents()
    store.all_items()
    companies = profiles._load()["companies"]
    credit = next(c for c in companies if c["products"].get("loans"))
    deposit = next((c for c in companies if c["products"].get("deposits") and c["products"].get("loans") is False), None)
    transport = next((c for c in companies if c["sector"] == "transport"), None)
    choices = [("Кредит: финансовый директор", credit, "cfo", "seed-rate-hold"),
               ("Та же компания: генеральный директор", credit, "ceo", "seed-rate-hold")]
    if deposit:
        choices.append(("Депозиты без кредитного продукта", deposit, "treasurer", "seed-rate-hold"))
    if transport:
        choices.append(("Транспорт и топливо", transport, "ceo", "seed-fuel-prices"))
    fresh, _ = store.add(store.make_item("Китай изменил условия таможенного оформления", "Китай изменил порядок таможенного оформления импортных поставок. Компаниям предлагается проверить документы и сроки международных расчетов.", "Демонстрационный пример", kind="user"))
    foreign = next((c for c in companies if c.get("fts_flag") and "Китай" in c["fts_countries"]), credit)
    choices.append(("Новая новость: ВЭД", foreign, "cfo", fresh["news_id"]))
    result = {"synthetic": meta["synthetic"], "rules_requested": rules, "items": []}
    for label, company, role, news_id in choices:
        insight = None if refresh else storage.cached_insight(company["company_id"], role, news_id)
        if not insight or (rules and insight["mode"] != "rules"):
            insight = await orchestrator.run(company, role, store.get(news_id), f"req_demo_{uuid.uuid4().hex}")
            storage.save_insight(insight)
        result["items"].append({"scenario": label, "company_id": company["company_id"], "role": role,
                                "news_id": news_id, "insight_id": insight["insight_id"], "mode": insight["mode"],
                                "quality_passed": insight["quality"]["passed"]})
    with database.session() as db:
        database.set_state("demo_manifest", result, db)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rules", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--synthetic", action="store_true")
    args = p.parse_args()
    print(json.dumps(asyncio.run(prepare(args.rules, args.refresh, args.synthetic)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
