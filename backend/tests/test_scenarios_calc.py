"""Сценарии «что если» (SPR4-02): формулы, монотонность, отказ без данных, число только с формулой."""

import pytest

from app.agent import validators
from app.companies import extra, profiles
from app.scenarios import calc
from app.scenarios.corridor import corridor


def _company(sector: str | None = None) -> dict:
    items = profiles.list_companies(limit=10**6)[1]
    return next(c for c in items if sector is None or c["sector"] == sector)


def test_key_rate_formula_monotonic_and_zero(client):
    cid = _company("construction")["company_id"]
    results = [calc.key_rate(cid, s) for s in (-2, -1, 0, 1, 2)]
    effects = [r.effect_rub for r in results]
    assert effects == sorted(effects, reverse=True), "чем выше ставка, тем больше процентные расходы"
    assert results[2].effect_rub == 0, "нулевой шок — ноль"
    r = calc.key_rate(cid, 1)
    revenue = profiles.get(cid)["revenue"]
    assert r.effect_rub == pytest.approx(-revenue * 0.6 * calc.DEFAULT_FLOATING * 0.01), "долг × доля плавающих × 1 п.п."
    assert {i.origin for i in r.inputs} == {"client_data", "estimate"} and r.shock_unit == "п.п."
    assert "долг ≈" in r.formula and r.caveats, "оценка долга подписана"


def test_user_inputs_replace_estimates(client):
    cid = _company()["company_id"]
    r = calc.key_rate(cid, 1, debt=1e9, floating_share=0.3)
    assert r.effect_rub == pytest.approx(-3e6) and calc.mln(r.effect_rub) == "3,0 млн ₽"
    assert {i.origin for i in r.inputs} == {"user"}


def test_fx_needs_shares_and_refuses_otherwise(client, company):
    cid = company["company_id"]
    with pytest.raises(calc.ScenarioError) as exc:
        calc.fx(cid, 10)
    assert set(exc.value.missing) == {"fx_revenue_share", "import_share"}, "нет данных — отказ, а не ноль"
    extra.save(cid, {"fx_revenue_share": 40, "import_share": 30}, "", "u1")
    up, down = calc.fx(cid, 10), calc.fx(cid, -10)
    assert up.effect_rub == pytest.approx(-down.effect_rub) and calc.fx(cid, 0).effect_rub == 0
    assert {"client_data", "company_reported"} <= {i.origin for i in up.inputs}


def test_commodity_only_for_raw_materials(client):
    oil = _company("mining_oil_gas") if any(c["sector"] == "mining_oil_gas" for c in profiles.list_companies(limit=10**6)[1]) \
        else _company("metallurgy")
    r = calc.commodity(oil["company_id"], 10)
    assert r.effect_rub > 0 and calc.commodity(oil["company_id"], -10).effect_rub == pytest.approx(-r.effect_rub)
    retail = next((c for c in profiles.list_companies(limit=10**6)[1] if c["sector"] in ("retail", "it_telecom", "services")), None)
    if retail:
        with pytest.raises(calc.ScenarioError):
            calc.commodity(retail["company_id"], 10)


def test_api_returns_formula_or_refusal(client, company):
    cid = company["company_id"]
    ok = client.post("/api/v1/scenarios", json={"company_id": cid, "scenario": "key_rate", "shock": 1}).json()
    assert ok["ok"] and ok["result"]["formula"] and ok["corridor"]["unit"] == "%"
    assert ok["corridor"]["low"] <= ok["corridor"]["high"] and ok["corridor"]["sources"][0].startswith("bank:")
    refused = client.post("/api/v1/scenarios", json={"company_id": cid, "scenario": "fx", "shock": 10}).json()
    assert refused["ok"] is False and refused["refusal"]["missing"]
    assert client.post("/api/v1/scenarios", json={"company_id": cid, "scenario": "key_rate", "shock": 99}).status_code == 400


def test_validator_drops_scenario_number_without_formula():
    """Число сценария проходит проверку только со ссылкой на расчет (формулу); без нее — ошибка numbers."""
    claim_text = "Каждый +1 п.п. ставки — это ≈ 123 млн ₽ процентных расходов в год"
    formula = "При изменении ставки на +1 п.п. процентные расходы вырастут ≈ на 123 млн ₽ в год долг ≈ 24600 млн ₽ × 50%"
    assert validators.missing_numbers(claim_text, formula, formula) == set()
    assert "123" in validators.missing_numbers(claim_text, "Новость о ставке Банка России", formula)


def test_insight_on_key_rate_news_cites_formula(client, company):
    feed = client.get("/api/v1/feed", params={"company_id": company["company_id"], "limit": 500}).json()["items"]
    news = next((i["news"] for i in feed if any(t["topic"] == "key_rate" for t in i["news"]["topics"][:2])), None)
    if news is None:
        pytest.skip("в ленте компании нет новости о ставке")
    ins = client.post("/api/v1/insights", json={"company_id": company["company_id"], "news_id": news["news_id"], "fast": True}).json()
    claims = [c for c in ins["risks"] if c["text"].startswith("Чувствительность к ставке")]
    assert claims and "client:scenario:key_rate" in claims[0]["source_ids"], "число сценария — со ссылкой на формулу"
    assert any(s["source_id"] == "client:scenario:key_rate" for s in ins["sources"])


def test_corridor_from_bank_forecasts():
    assert corridor("commodity") is None
    fx = corridor("fx")
    assert fx and fx["unit"] == "руб./$" and fx["low"] <= fx["high"]
