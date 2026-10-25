"""Цепочка поставок в ленте и разборах: известная часть платежей, веса, квота, знаки по сторонам, тайна контрагентов."""

import asyncio
import copy
import json
import re
from datetime import datetime, timezone

import pytest

from app import ranking
from app.agent import composer, evidence, orchestrator, prompts, qa
from app.agent.tools import ToolRunner
from app.companies import etl, profiles, supply
from app.companies.sectors import SECTOR_SENSITIVITY
from app.domain_config.runtime import DIRECTION_VALUE
from app.news import store

FIXED_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


# --- построение проверяемых профилей -------------------------------------------------------------

def make_side(known: float, shares: dict[str, float], top1: float | None = None, legacy: bool = False) -> dict:
    """Сторона платежей: known — доля оборота с известной отраслью, shares — доли отраслей от известной части."""
    items = [{"sector": s, "share": known * v, "share_known": v} for s, v in shares.items()]
    side = {"total_amount": 1e9, "counterparties": 10, "top": [], "top1_share": top1, "intra_group_share": 0.0,
            "known_share": known, "unknown_share": 1 - known, "by_sector": items}
    if legacy:  # прежняя форма профиля: доли от всего оборота, «unknown» среди отраслей
        side = {k: v for k, v in side.items() if k not in ("known_share", "unknown_share")}
        side["by_sector"] = [{"sector": i["sector"], "share": i["share"]} for i in items] + (
            [{"sector": "unknown", "share": 1 - known}] if known < 1 else [])
    return side


@pytest.fixture
def base_profile(raw_client):
    c = copy.deepcopy(profiles._load()["companies"][0])
    c["sector"], c["sector_name"] = "auto", "Автомобилестроение"
    c["group"] = {**c["group"], "usable": False}
    c["fts_flag"], c["revenue"] = False, 1e9
    c["products"] = {k: False for k in c["products"]}
    return c


def exposures_of(monkeypatch, profile: dict) -> list[dict]:
    monkeypatch.setattr(profiles, "get", lambda cid: profile)
    return list(profiles._base_exposures.__wrapped__(profile["company_id"]))


def payment_exposures(exps: list[dict]) -> list[dict]:
    return [e for e in exps if e["origin"] == "payments"]


# --- 1. известная часть платежей -------------------------------------------------------------------

def test_etl_known_share_and_unknown_kept_out_of_sectors():
    companies = {f"K{i}": {"sector": s, "okved_name": "x", "region": "r", "group_id": None}
                 for i, s in enumerate(["construction", "construction", "retail", "metallurgy"])}
    flows = {"K0": [30.0, 1], "K1": [30.0, 1], "K2": [20.0, 1], "K3": [10.0, 1], "OUT1": [100.0, 1], "OUT2": [10.0, 1]}
    side = etl._counterparties(flows, companies, None)
    assert side["known_share"] == pytest.approx(90 / 200)
    assert side["unknown_share"] == pytest.approx(110 / 200)
    sectors = {i["sector"]: i for i in side["by_sector"]}
    assert "unknown" not in sectors
    assert sectors["construction"]["share_known"] == pytest.approx(60 / 90)
    assert sectors["construction"]["share"] == pytest.approx(60 / 200)  # как раньше: от всего оборота


def test_etl_keeps_six_known_sectors_when_unknown_is_largest():
    companies = {f"K{i}": {"sector": f"s{i}", "okved_name": "x", "region": "r", "group_id": None} for i in range(8)}
    flows = {f"K{i}": [10.0 + i, 1] for i in range(8)} | {"OUT": [1000.0, 1]}
    side = etl._counterparties(flows, companies, None)
    assert len(side["by_sector"]) == 6 and all(i["sector"] != "unknown" for i in side["by_sector"])
    assert side["known_share"] < 0.2


def test_etl_no_payments():
    side = etl._counterparties({}, {}, None)
    assert side["known_share"] == 0 and side["by_sector"] == [] and side["top1_share"] is None


def test_profile_signature_is_versioned(tmp_path):
    for n in ("df_Uid_data_hack.csv", "df_Uid_payment_hack.csv", "df_Fid_Uid_link_hack.csv"):
        (tmp_path / n).write_text("x", encoding="utf-8")
    assert profiles._signature(tmp_path).startswith("v4|")  # старый кэш профилей (v3) пересобирается


@pytest.mark.parametrize("known,expected", [(0.0, 0), (0.09, 0), (0.1, 0.15), (0.2, 0.325), (0.3, 0.5), (0.5, 0.75), (0.7, 1), (1, 1)])
def test_known_confidence(known, expected):
    assert supply.known_confidence(known) == pytest.approx(expected, abs=1e-3)
    assert supply.known_confidence(0.29) < 0.5 <= supply.known_confidence(0.3)


def test_links_threshold_is_relative_to_known_part():
    # 12% всего оборота, но 24% известной части: в реальных данных (половина неизвестна) порог проходится.
    c = {"sector": "auto", "suppliers": make_side(0.5, {"construction": 0.24, "retail": 0.76}), "customers": make_side(0, {})}
    got = {(x["side"], x["sector"]): x for x in supply.links(c)}
    assert ("suppliers", "construction") in got
    assert got[("suppliers", "construction")]["share"] == pytest.approx(0.24)
    assert got[("suppliers", "construction")]["confidence"] == pytest.approx(0.75)
    # доля ниже порога (14% известной части) отсекается, собственная отрасль не считается
    c["suppliers"] = make_side(1.0, {"construction": 0.14, "auto": 0.5, "retail": 0.36})
    assert {x["sector"] for x in supply.links(c)} == {"retail"}


def test_links_signal_off_when_almost_nothing_is_known():
    c = {"sector": "auto", "suppliers": make_side(0.05, {"construction": 1.0}), "customers": make_side(0.5, {"retail": 1.0})}
    assert [(x["side"], x["sector"]) for x in supply.links(c)] == [("customers", "retail")]


def test_links_read_legacy_profile_shape():
    c = {"sector": "auto", "suppliers": make_side(0.5, {"construction": 0.6, "retail": 0.4}, legacy=True), "customers": {}}
    link = next(x for x in supply.links(c) if x["sector"] == "construction")
    assert link["share"] == pytest.approx(0.6) and link["known_share"] == pytest.approx(0.5)


def test_exposure_weight_scales_with_confidence(monkeypatch, base_profile):
    weights = {}
    for known in (1.0, 0.5, 0.2, 0.05):
        base_profile["suppliers"] = make_side(known, {"construction": 0.5, "retail": 0.5})
        base_profile["customers"] = make_side(0, {})
        exps = payment_exposures(exposures_of(monkeypatch, base_profile))
        weights[known] = max((e["weight"] for e in exps if e["feature"] == "suppliers.by_sector"), default=0)
    assert weights[1.0] == pytest.approx(0.7 * 0.5, abs=1e-3)
    assert weights[0.5] == pytest.approx(0.7 * 0.5 * 0.75, abs=1e-3)
    assert 0 < weights[0.2] < weights[0.5] < weights[1.0]
    assert weights[0.05] == 0  # сигнал выключен


def test_exposure_reason_is_honest_about_unknown_part(monkeypatch, base_profile):
    base_profile["suppliers"] = make_side(0.5, {"construction": 0.4, "retail": 0.6})
    base_profile["customers"] = make_side(0, {})
    texts = [e["why"] for e in payment_exposures(exposures_of(monkeypatch, base_profile))]
    assert texts and all("известной части платежей поставщикам" in t and "отрасль известна у 50% оборота" in t for t in texts)


def test_customer_concentration_exposure_mirrors_suppliers(monkeypatch, base_profile):
    base_profile["suppliers"] = make_side(1.0, {"retail": 1.0}, top1=0.6)
    base_profile["customers"] = make_side(1.0, {"retail": 1.0}, top1=0.7)
    features = {e["feature"] for e in exposures_of(monkeypatch, base_profile)}
    assert {"suppliers.top1_share", "customers.top1_share"} <= features
    base_profile["customers"] = make_side(1.0, {"retail": 1.0}, top1=0.4)
    assert "customers.top1_share" not in {e["feature"] for e in exposures_of(monkeypatch, base_profile)}


# --- 2. вес в оценке ------------------------------------------------------------------------------

def signals(profile: dict, sectors: list[str]):
    reasons: list[dict] = []
    news = {"title": "Новость", "text": "Текст"}
    cls = {"sectors": sectors, "countries": []}
    _, sc, _, _ = ranking._direct_signals(profile, cls, news, reasons)
    return sc, [r for r in reasons if r["kind"] == "supply_chain"]


def test_supply_chain_signal_and_reason_text(base_profile):
    base_profile["suppliers"] = make_side(1.0, {"construction": 0.3, "retail": 0.7})
    base_profile["customers"] = make_side(0.5, {"retail": 0.4, "metallurgy": 0.6})
    sc, reasons = signals(base_profile, ["construction"])
    assert sc == pytest.approx((0.3 ** 0.5))  # вогнутое преобразование: 30% -> 0,55
    (r,) = reasons
    assert r["text"] == "Через ваших поставщиков: отрасль «Строительство», 30% известной части платежей поставщикам"
    sc, reasons = signals(base_profile, ["metallurgy"])
    assert sc == pytest.approx((0.6 * 0.75) ** 0.5)
    assert reasons[0]["text"].startswith("Через ваших покупателей: отрасль «Металлургия")
    assert "40%" not in reasons[0]["text"] and "60% известной части поступлений от покупателей" in reasons[0]["text"]
    assert "отрасль известна у 50% оборота" in reasons[0]["text"]
    assert signals(base_profile, ["auto"]) == (0.0, [])  # собственная отрасль — другой признак


def test_strong_share_competes_with_own_sector():
    w = ranking.weights()["weights"]
    own = w["sector_mention"] * 1.0
    chain = w["supply_chain"] * (0.3 ** 0.5)  # 30% известной части
    assert 0.6 * own <= chain <= 1.2 * own
    assert w["supply_chain"] * (0.15 ** 0.5) < own  # слабая связь свою отрасль не вытесняет


# --- 3. мягкая квота ----------------------------------------------------------------------------

def row(news_id: str, score: float, supply_reason: bool = False) -> dict:
    reasons = [{"kind": "exposure", "weight": 1.0}] + ([{"kind": "supply_chain", "weight": 0.3}] if supply_reason else [])
    return {"news": {"news_id": news_id, "title": news_id}, "relevance": {"score": score, "reasons": reasons}}


def feed_rows(n_main=24, supply_scores=(30.0, 25.0, 15.0)):
    main = [row(f"m{i}", 90 - i) for i in range(n_main)]
    cands = [row(f"s{i}", s, True) for i, s in enumerate(supply_scores)]
    return main, sorted(main + cands, key=lambda r: -r["relevance"]["score"])


def test_quota_inserts_best_supply_items_in_place_of_weakest(raw_client):
    main, ranked = feed_rows()
    out = ranking._supply_quota(main, ranked)
    head = out[:20]
    assert [r["news"]["news_id"] for r in head if ranking._is_supply(r)] == ["s0", "s1"]
    assert len(out) == len(main)
    assert [r["news"]["news_id"] for r in head[:18]] == [f"m{i}" for i in range(18)]  # лучшие не затронуты
    assert "s2" not in {r["news"]["news_id"] for r in out}  # ниже порога оценки


def test_quota_not_applied_when_already_satisfied_or_below_floor(raw_client):
    main = [row(f"m{i}", 90 - i, supply_reason=i in (3, 7)) for i in range(24)]
    assert ranking._supply_quota(main, main) == main
    main, ranked = feed_rows(supply_scores=(19.0, 12.0))
    assert ranking._supply_quota(main, ranked) == main


def test_quota_counts_only_missing_items(raw_client):
    main = [row(f"m{i}", 90 - i, supply_reason=(i == 5)) for i in range(24)]
    cands = [row("s0", 30.0, True), row("s1", 28.0, True)]
    out = ranking._supply_quota(main, sorted(main + cands, key=lambda r: -r["relevance"]["score"]))
    assert sum(ranking._is_supply(r) for r in out[:20]) == 2  # одна уже была, добавлена одна
    assert "s0" in {r["news"]["news_id"] for r in out[:20]}


def test_quota_promotes_candidate_from_tail(raw_client):
    main = [row(f"m{i}", 90 - i) for i in range(20)] + [row("tail", 21.0, True)]
    out = ranking._supply_quota(main, main)
    assert "tail" in {r["news"]["news_id"] for r in out[:20]} and len(out) == 20
    assert sum(1 for r in out if r["news"]["news_id"] == "tail") == 1


def test_quota_does_not_create_story_duplicates(raw_client, monkeypatch):
    main, ranked = feed_rows()
    monkeypatch.setattr(ranking, "_story_id", lambda r: {"s0": "A", "m3": "A", "s1": "B"}.get(r["news"]["news_id"]))
    out = ranking._supply_quota(main, ranked)
    ids = [r["news"]["news_id"] for r in out[:20]]
    assert "s0" not in ids and "s1" in ids  # s0 — тот же сюжет, что m3: пропущен, взята следующая


def test_quota_does_not_fill_with_nothing_when_feed_is_short(raw_client):
    main = [row(f"m{i}", 90 - i) for i in range(5)]
    ranked = main + [row("s0", 30.0, True)]
    out = ranking._supply_quota(main, ranked)
    assert len(out) == 6 and out[-1]["news"]["news_id"] == "s0"  # свободные места: никого не вытесняем


def test_feed_quota_end_to_end(raw_client, monkeypatch):
    """Лента реальных компаний: если есть кандидаты выше порога, в первых 20 их не меньше двух (или все, что есть)."""
    monkeypatch.setattr(ranking, "NOW_OVERRIDE", FIXED_NOW)
    items = store.all_items()
    checked = 0
    for c in profiles._load()["companies"][:25]:
        out = ranking.feed(items, c["company_id"], "ceo", None, 30)
        pool = [r for r in (ranking.score(n, c["company_id"], "ceo") for n in items)
                if any(x["kind"] == "supply_chain" for x in r["reasons"]) and r["score"] >= ranking.SUPPLY_QUOTA_MIN_SCORE]
        in_top = sum(1 for r in out[:20] if ranking._is_supply(r))
        assert in_top >= min(ranking.SUPPLY_QUOTA, len(pool))
        ids = [r["news"]["news_id"] for r in out]
        assert len(ids) == len(set(ids))  # дублей нет
        checked += 1
    assert checked == 25


# --- 4. знаки по сторонам --------------------------------------------------------------------------

def sector_effect(topic: str, sector: str, direction: str) -> float:
    return SECTOR_SENSITIVITY[topic][sector].sign * DIRECTION_VALUE[topic][direction]


def exp(sign: int, side: str) -> dict:
    return {"sign": sign, "side": side, "topic": "fuel_oil", "feature": f"{side}.by_sector"}


def test_sign_convention_fixture_values():
    # Топливо дорожает (up): сельское хозяйство проигрывает, нефтедобыча выигрывает.
    assert DIRECTION_VALUE["fuel_oil"]["up"] > 0 > DIRECTION_VALUE["fuel_oil"]["down"]
    assert SECTOR_SENSITIVITY["fuel_oil"]["agriculture_food"].sign == -1
    assert SECTOR_SENSITIVITY["fuel_oil"]["mining_oil_gas"].sign == 1


def test_customer_problem_is_revenue_risk_and_growth_is_opportunity():
    hurt = exp(SECTOR_SENSITIVITY["fuel_oil"]["agriculture_food"].sign, "customers")
    assert composer.side_effect(hurt, "fuel_oil", "up") < 0      # покупатель проигрывает -> риск выручки
    assert composer.side_effect(hurt, "fuel_oil", "down") > 0    # покупателю легче -> возможность
    wins = exp(SECTOR_SENSITIVITY["fuel_oil"]["mining_oil_gas"].sign, "customers")
    assert composer.side_effect(wins, "fuel_oil", "up") > 0 > composer.side_effect(wins, "fuel_oil", "down")


def test_supplier_problem_is_supply_risk_and_gain_is_not_an_opportunity():
    hurt = exp(SECTOR_SENSITIVITY["fuel_oil"]["agriculture_food"].sign, "suppliers")
    assert composer.side_effect(hurt, "fuel_oil", "up") < 0      # поставщику хуже -> риск поставок и цен
    assert composer.side_effect(hurt, "fuel_oil", "down") is None  # поставщику лучше -> возможностью не считается
    wins = exp(SECTOR_SENSITIVITY["fuel_oil"]["mining_oil_gas"].sign, "suppliers")
    assert composer.side_effect(wins, "fuel_oil", "up") is None
    assert composer.side_effect(wins, "fuel_oil", "down") < 0


def test_side_effect_matches_sector_effect_for_every_topic_and_sector():
    """Знак не переворачивается: эффект = sign × DIRECTION_VALUE; для поставщиков положительный не засчитывается."""
    checked = 0
    for topic, by_sector in SECTOR_SENSITIVITY.items():
        for sector, s in by_sector.items():
            for direction in ("up", "down"):
                if direction not in DIRECTION_VALUE.get(topic, {}):
                    continue
                expected = sector_effect(topic, sector, direction)
                customer = composer.side_effect({"sign": s.sign, "side": "customers"}, topic, direction)
                supplier = composer.side_effect({"sign": s.sign, "side": "suppliers"}, topic, direction)
                assert customer == expected
                assert supplier == (expected if expected <= 0 else None)
                checked += 1
    assert checked > 100


def test_base_exposures_keep_sector_sign_and_side(monkeypatch, base_profile):
    base_profile["suppliers"] = make_side(1.0, {"agriculture_food": 0.5, "mining_oil_gas": 0.5})
    base_profile["customers"] = make_side(1.0, {"agriculture_food": 1.0})
    exps = payment_exposures(exposures_of(monkeypatch, base_profile))
    by = {(e["side"], e["topic"], e["value"]["sector"]): e["sign"] for e in exps}
    for (side, topic, sector), sign in by.items():
        assert sign == SECTOR_SENSITIVITY[topic][sector].sign
    assert {e["side"] for e in exps} == {"suppliers", "customers"}


def sc_ctx(profile: dict, sector: str, topic: str, direction: str) -> dict:
    cls = {"sectors": [sector], "topics": [{"topic": topic}], "direction": direction, "topic_directions": {topic: direction}}
    return {"company": profile, "news": {"classification": cls}}


def test_agent_claims_and_actions_by_side(base_profile):
    base_profile["suppliers"] = make_side(1.0, {"agriculture_food": 0.4}, top1=0.6)
    base_profile["customers"] = make_side(1.0, {"agriculture_food": 0.3}, top1=0.55)
    risks, opps, actions = composer._supply_chain(sc_ctx(base_profile, "agriculture_food", "fuel_oil", "up"), "news:x")
    texts = [c["text"] for c in risks]
    assert any(t.startswith("Через ваших поставщиков") and "перебои поставок" in t and "закупочных цен" in t for t in texts)
    assert any(t.startswith("Через ваших покупателей") and "дебиторской задолженности" in t for t in texts)
    assert not opps
    acts = " | ".join(c["text"] for c in actions)
    assert "альтернативных поставщиков в отрасли «Сельское хозяйство" in acts
    assert "лимиты и сроки отсрочки покупателям из отрасли «Сельское хозяйство" in acts
    assert "крупнейшего поставщика (60%" in acts and "крупнейшего покупателя (55%" in acts  # концентрация обеих сторон
    assert all(c["source_ids"] == ["news:x", "client:payments"] for c in risks + actions)
    # топливо дешевеет: поставщику лучше — ни риска, ни возможности; покупатель — возможность
    risks, opps, actions = composer._supply_chain(sc_ctx(base_profile, "agriculture_food", "fuel_oil", "down"), "news:x")
    assert not risks and len(opps) == 1 and opps[0]["text"].startswith("Через ваших покупателей")
    assert all("поставщик" not in c["text"] for c in actions)


def test_no_concentration_action_below_half(base_profile):
    base_profile["suppliers"] = make_side(1.0, {"agriculture_food": 0.4}, top1=0.5)
    base_profile["customers"] = make_side(0, {})
    _, _, actions = composer._supply_chain(sc_ctx(base_profile, "agriculture_food", "fuel_oil", "up"), "news:x")
    assert all("крупнейшего" not in c["text"] for c in actions)


def test_supply_claim_numbers_are_grounded(base_profile):
    """Числа в рисках и действиях есть в тексте источника client:payments и в тексте сверки."""
    from app.agent import context, evidence, validators
    base_profile["suppliers"] = make_side(0.5, {"agriculture_food": 0.4, "retail": 0.6}, top1=0.6)
    base_profile["customers"] = make_side(0, {})
    ctx = {**sc_ctx(base_profile, "agriculture_food", "fuel_oil", "up"), "theses": [], "story": [], "coverage": []}
    ctx["news"].update(news_id="x", title="Топливо дорожает", text="Цены на топливо растут")
    risks, _, actions = composer._supply_chain(ctx, "news:x")
    payments = evidence.source_texts(ctx)["client:payments"]
    grounding = context.grounding_text(ctx)
    for claim in risks + actions:
        assert not validators.missing_numbers(claim["text"], payments, payments), claim["text"]
        assert not validators.missing_numbers(claim["text"], grounding, grounding), claim["text"]


# --- 5. тайна контрагентов ---------------------------------------------------------------------------

def secrets_of(company: dict) -> tuple[list[str], list[str]]:
    ids, other = [], []
    for side in ("suppliers", "customers"):
        total = company[side]["total_amount"]
        for cp in company[side]["top"]:
            ids.append(cp["company_id"])
            other_company = profiles.get(cp["company_id"])
            if other_company:
                other.append(other_company["display_name"])
            amount = cp["amount"]
            if amount and amount != total and amount > 1e5:
                other.append(f"{amount:.0f}")
    return ids, other


def assert_no_leak(payload, ids, other, where):
    text = json.dumps(payload, ensure_ascii=False, default=str)
    for cid in ids:
        assert not re.search(rf"(?<![\w]){re.escape(cid)}(?!\d)", text), f"{where}: идентификатор контрагента {cid}"
    for value in other:
        assert value not in text, f"{where}: {value}"


def test_counterparty_secrets_stay_out_of_feed_insight_and_tools(raw_client, monkeypatch):
    monkeypatch.setattr(ranking, "NOW_OVERRIDE", FIXED_NOW)
    companies = [c for c in profiles._load()["companies"] if c["suppliers"]["top"] and c["customers"]["top"]]
    sample = companies[:: max(1, len(companies) // 6)][:6]
    assert len(sample) >= 4
    items = store.all_items()
    checked_ids = 0
    for c in sample:
        own = c["company_id"]
        ids, other = secrets_of(c)
        ids = [i for i in ids if i != own]
        checked_ids += len(ids)
        feed = ranking.feed(items, own, "cfo", None, 20)
        assert_no_leak([{"news": r["news"]["news_id"], "relevance": r["relevance"]} for r in feed], ids, other, "feed")
        runner = ToolRunner("req_privacy")
        result, _ = runner.call("get_counterparties", company_id=own)
        assert_no_leak(result, ids, other, "get_counterparties")
        assert set(result["suppliers"]) >= {"known_share", "by_sector", "top1_share"} and "top" not in result["suppliers"]
        # Источники и описание компании, которые уходят в запросы к модели (исправление, составление, проверка).
        news = feed[0]["news"] if feed else items[0]
        assert_no_leak(evidence.source_texts({"company": c, "news": news}), ids, other, "llm sources")
        assert_no_leak(prompts._company_brief(c), ids, other, "llm company brief")
        assert_no_leak(runner.call("get_exposures", company_id=own, topics=[])[0], ids, other, "get_exposures")
        for r in feed[:2]:
            insight = asyncio.run(orchestrator.run(c, "cfo", r["news"], "req_privacy", use_llm=False))
            assert_no_leak(insight, ids, other, "insight")
            answer = qa.answer(insight, c, "Расскажи про контрагентов", runner)
            assert_no_leak(answer, ids, other, "qa")
    assert checked_ids > 20
