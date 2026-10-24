"""Предложение банка — только при выявленной потребности (SPR4-06).

Потребность = тема события ∩ знак события для компании ∩ признак компании (экспозиция). Правила —
в доменной конфигурации (topics.yaml, раздел offers), признаки — фиксированный набор проверок ниже.
Нет потребности — нет предложения. Каждое предложение помечено «Реклама банка» и объясняет, почему показано.
"""

from app.companies import extra
from app.domain_config import runtime

LABEL = "Реклама банка"
EFFECTS = {"risk": {"neg", "mixed"}, "opportunity": {"pos", "mixed"}, "any": {"neg", "pos", "mixed", "unclear"}}


def _concentration(company: dict, rule: dict, news: dict) -> str | None:
    share = (company.get("customers") or {}).get("top1_share") or 0
    if share >= rule["min_share"]:
        return f"на крупнейшего покупателя приходится {share:.0%} поступлений"
    return None


def _fx(company: dict, rule: dict, news: dict) -> str | None:
    shares = (extra.get(company["company_id"]) or {}).get("shares") or {}
    if (shares.get("fx_revenue_share") or 0) > 0 or (shares.get("import_share") or 0) > 0:
        return "компания сообщила о валютной выручке или импорте"
    if company.get("fts_flag"):
        countries = ", ".join(company.get("fts_countries") or []) or "есть"
        return f"компания ведет внешнеэкономические расчеты ({countries})"
    return None


def _new_countries(company: dict, rule: dict, news: dict) -> str | None:
    if not company.get("fts_flag"):
        return None
    known = {c.lower() for c in company.get("fts_countries") or []}
    new = [c for c in news["classification"].get("countries") or [] if c.lower() not in known]
    if new:
        return f"в событии — {', '.join(new[:3])}; в ваших расчетах ВЭД этих стран пока нет"
    return None


def _loans(company: dict, rule: dict, news: dict) -> str | None:
    return "у компании есть кредиты" if (company.get("products") or {}).get("loans") else None


EXPOSURES = {"customers_concentration": _concentration, "fx_operations": _fx, "new_countries": _new_countries,
             "loans": _loans}


def offers_for(insight: dict, company: dict, news: dict) -> list[dict]:
    """Предложения по правилам конфигурации; пустой список — потребность не выявлена."""
    topics = {t["topic"] for t in news["classification"]["topics"][:3]}
    effect = insight.get("effect") or "unclear"
    out = []
    for offer_id, rule in runtime.OFFERS.items():
        if not topics & set(rule["topics"]) or effect not in EFFECTS[rule["effect"]]:
            continue
        reason = EXPOSURES[rule["exposure"]](company, rule, news)
        if reason is None:
            continue
        out.append({"offer_id": offer_id, "title": rule["title"], "text": rule["text"], "need": rule["need"],
                    "reason": reason, "label": LABEL})
    return out
