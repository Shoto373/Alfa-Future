"""Conservative evidence boundaries shared by generation and self-checks.

These are deterministic checks, not a semantic proof of correctness. Bank
statements must be exact reviewed theses; uncertain AI claims remain labelled AI.
"""
import json
import re

from app.agent import composer
from app.companies import extra as company_extra
from app.companies.profiles import group
from app.text import INSTRUCTION, safe_text


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip(" .;:")


def valid_features(company: dict) -> set[str]:
    result = {"sector"}
    for key, value in company.get("products", {}).items():
        if value is True:
            result.add(f"products.{key}")
    for key in ("revenue", "workers_fns"):
        if company.get(key):
            result.add(key)
    if company.get("fts_flag"):
        result.add("fts_countries")
    if company.get("market", {}).get("okved_rank"):
        result.add("market")
    if group(company):
        result.add("group")
    for key, share in ((company.get("extra") or {}).get("shares") or {}).items():
        if share > 0:
            result.add(f"extra.{key}")
    for side in ("suppliers", "customers"):
        if company.get(side, {}).get("by_sector"):
            result.add(f"{side}.by_sector")
        if company.get(side, {}).get("top1_share") is not None:
            result.add(f"{side}.top1_share")
    return result


def source_texts(ctx: dict) -> dict[str, str]:
    c = ctx["company"]
    profile = json.dumps({k: v for k, v in c.items() if k != "extra"}, ensure_ascii=False)
    # Same display units as the deterministic composer, with explicit origin.
    profile += f" {c.get('company_id', '')} {(c.get('revenue') or 0) / 1e9:.1f}"
    profile += f" {(c.get('market', {}).get('okved_share') or 0) * 100:.1f}%"
    g = c.get("group") or {}
    if g.get("revenue"):  # выручка группы — в тех же единицах, что в тексте вывода
        profile += f" {g['revenue'] / 1e9:.1f} млрд ₽ {g.get('members')}"
        profile += "".join(f" {x['share'] * 100:.0f}%" for x in g.get("sector_shares", []))
    payments = json.dumps({k: c.get(k) for k in ("suppliers", "customers")}, ensure_ascii=False)
    for side in ("suppliers", "customers"):
        # Доли — и округленные, и с одним знаком: модель пишет «24,7%», правила — «25%».
        for s in c.get(side, {}).get("by_sector", []):
            payments += f" {s['share'] * 100:.0f}% {s['share'] * 100:.1f}%"
        if c.get(side, {}).get("top1_share") is not None:
            payments += f" {c[side]['top1_share'] * 100:.0f}% {c[side]['top1_share'] * 100:.1f}%"
        total = c.get(side, {}).get("total_amount")
        if total:  # суммы платежей в тех единицах, в которых их пишут в тексте
            payments += f" {total / 1e6:.1f} млн руб. {total / 1e9:.2f} млрд руб."
    result = {f"news:{ctx['news']['news_id']}": safe_text(ctx["news"]["title"] + " " + ctx["news"]["text"]),
              "client:profile": profile, "client:payments": payments}
    result.update({f"news:{n['news_id']}": safe_text(f"{n['title']} {n['lead']} {n['published_at']} {composer.day(n['published_at'])}")
                   for n in ctx.get("story", []) + ctx.get("coverage", [])})
    result.update({f"bank:{t['id']}": t["text"] for t in ctx.get("theses", [])})
    result.update({f"product:{p['id']}": p["text"] for p in ctx.get("products", [])})
    if c.get("extra"):
        result["client:extra"] = company_extra.text(c["extra"])
    return result


def contradictions(text: str, company: dict) -> bool:
    t = text.lower()
    if INSTRUCTION.search(t):
        return True
    ownership = r"(?:у\s+компании|компания\s+имеет|ваш\w*|ее|её)\s+(?:есть\s+)?"
    # Сведения от компании тоже подтверждают долг и ВЭД, даже если в данных кейса их нет.
    reported = {k for k, v in ((company.get("extra") or {}).get("shares") or {}).items() if v > 0}
    for product, noun in (("loans", r"(?:кредит|долг)"), ("deposits", r"депозит"), ("leasing", r"лизинг")):
        if product == "loans" and "floating_debt_share" in reported:
            continue
        if company["products"].get(product) is not True and re.search(ownership + noun, t):
            return True
    if not company.get("fts_flag") and not reported & {"fx_revenue_share", "import_share"} and re.search(ownership + r"(?:импорт|экспорт|вэд|валютн\w*\s+выручк)", t):
        return True
    return False
