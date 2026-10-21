"""Профили крупных компаний: загрузка, поиск и экспозиции к макрофакторам.

Профили строит ETL (app.companies.etl) из CSV в DATA_DIR и кэширует в
RUNTIME_DIR/companies.json. Экспозиции — объяснимые признаки, по которым
новости сопоставляются с компанией: каждая ссылается на поле данных.
"""

import json
import logging
import os
import threading
from functools import lru_cache

from app import config
from app.companies import etl
from app.companies.sectors import SECTOR_NAMES, SECTOR_SENSITIVITY

logger = logging.getLogger("app.companies")
_lock = threading.Lock()
_cache: dict | None = None


class ProfilesError(Exception):
    pass


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = config.profiles_path()
        data_dir = config.data_dir()
        if not (data_dir / "df_Uid_data_hack.csv").exists():
            fallback = config.fallback_data_dir()
            logger.warning("no case CSV in %s, falling back to %s", data_dir, fallback)
            data_dir = fallback
        signature = _signature(data_dir)
        data = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
        explicit = bool(os.environ.get("PROFILES_PATH"))
        if data is None or (not explicit and signature and data.get("signature") != signature):
            if not signature:
                raise ProfilesError(f"Нет данных: {data_dir}/df_Uid_data_hack.csv")
            logger.info("building company profiles from %s", data_dir)
            data = etl.build_profiles(data_dir)
            data["signature"] = signature
            data["synthetic"] = (data_dir / "SYNTHETIC").exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        data["by_id"] = {c["company_id"]: c for c in data["companies"]}
        _cache = data
        exposures.cache_clear()
        return _cache


def _signature(data_dir) -> str | None:
    files = [data_dir / n for n in ("df_Uid_data_hack.csv", "df_Uid_payment_hack.csv", "df_Fid_Uid_link_hack.csv")]
    if not files[0].exists():
        return None
    return "|".join(f"{f.name}:{f.stat().st_size}:{int(f.stat().st_mtime)}" for f in files if f.exists())


def reset_cache() -> None:
    global _cache
    _cache = None
    exposures.cache_clear()


def meta() -> dict:
    d = _load()
    return {k: d.get(k) for k in ("generated_at", "source_dir", "total_companies", "selection_rule")} | {
        "profiles": len(d["companies"]), "synthetic": bool(d.get("synthetic", True))}


def list_companies(query: str = "", sector: str | None = None, limit: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
    items = _load()["companies"]
    q = query.strip().lower()
    if q:
        items = [c for c in items if q in c["company_id"].lower() or q in (c["okved_name"] or "").lower()
                 or q in (c["region"] or "").lower() or q in c["sector_name"].lower() or q in (c["okved_code"] or "")]
    if sector:
        items = [c for c in items if c["sector"] == sector]
    return len(items), [summary(c) for c in items[offset:offset + limit]]


def get(company_id: str) -> dict | None:
    return _load()["by_id"].get(company_id)


def summary(c: dict) -> dict:
    return {
        "company_id": c["company_id"], "display_name": c["display_name"], "sector": c["sector"],
        "sector_name": c["sector_name"], "okved_code": c["okved_code"], "okved_name": c["okved_name"],
        "region": c["region"], "revenue": c["revenue"], "client_type": c["client_type"],
        "fts_countries": c["fts_countries"],
    }


def _bn(value: float | None) -> str:
    return f"{value / 1e9:.1f} млрд ₽" if value else "нет данных"


@lru_cache(maxsize=2048)
def exposures(company_id: str) -> tuple[dict, ...]:
    """Чувствительность компании к темам новостей с обоснованием по признакам."""
    c = get(company_id)
    if c is None:
        return ()
    p = c["products"]
    out: list[dict] = []

    def add(topic: str, weight: float, sign: int, feature: str, value, why: str, origin: str = "client_data"):
        out.append({"topic": topic, "weight": weight, "sign": sign, "feature": feature, "value": value,
                    "why": why, "origin": origin})

    for topic, by_sector in SECTOR_SENSITIVITY.items():
        s = by_sector.get(c["sector"])
        if s:
            add(topic, 1.0, s.sign, "sector", c["sector_name"], f"Отрасль «{c['sector_name']}»: {s.why}", "sector_model")

    if p.get("loans"):
        add("key_rate", 1.2, -1, "products.loans", True, "Есть кредитные продукты: стоимость долга зависит от ключевой ставки")
        add("credit_market", 0.8, 1, "products.loans", True, "Есть кредитные продукты: условия кредитования влияют на финансирование")
        add("bonds", 0.4, -1, "products.loans", True, "Ставки рынка долга задают ориентир стоимости новых заимствований")
    if p.get("leasing"):
        add("key_rate", 0.6, -1, "products.leasing", True, "Есть лизинг: лизинговые платежи привязаны к стоимости фондирования")
    if p.get("deposits"):
        add("key_rate", 0.7, 1, "products.deposits", True, "Есть депозиты: высокая ставка повышает доходность размещения ликвидности")
        add("deposits", 0.6, 1, "products.deposits", True, "Есть депозиты: важна доходность размещения")
    if p.get("factoring"):
        add("corporate_finance", 0.6, 0, "products.factoring", True, "Есть факторинг: компания управляет дебиторской задолженностью")
        add("consumer_demand", 0.3, 1, "products.factoring", True, "Факторинг связан с отсрочками платежей покупателей")
    if p.get("guarantees"):
        add("budget", 0.6, 1, "products.guarantees", True, "Есть банковские гарантии: вероятны контракты, в т.ч. государственные")
    if p.get("payroll") or c.get("workers_fns") in ("101-250", "Более 251"):
        add("labor", 0.6, -1, "workers_fns", c.get("workers_fns"), f"Штат {c.get('workers_fns') or 'н/д'} сотрудников: рост зарплат увеличивает издержки")
    if c.get("fts_flag"):
        countries = ", ".join(c["fts_countries"]) or "страны не указаны"
        add("fx", 1.0, 0, "fts_countries", c["fts_countries"], f"Есть внешнеэкономическая деятельность ({countries}): курс влияет на расчеты")
        add("imports_exports", 1.0, 0, "fts_countries", c["fts_countries"], f"ВЭД с контрагентами: {countries}")
        add("sanctions_geopolitics", 0.7, -1, "fts_countries", c["fts_countries"], "ВЭД чувствительна к ограничениям на платежи и логистику")
    if (c.get("revenue") or 0) > 50e9:
        add("gdp_industry", 0.4, 1, "revenue", c["revenue"], f"Выручка {_bn(c['revenue'])}: масштаб делает компанию зависимой от общей динамики экономики")

    for side, label in (("suppliers", "поставщиков"), ("customers", "покупателей")):
        for item in c[side]["by_sector"]:
            sector, share = item["sector"], item["share"]
            if sector in ("unknown", c["sector"]) or share < 0.15:
                continue
            for topic, by_sector in SECTOR_SENSITIVITY.items():
                s = by_sector.get(sector)
                if s:
                    add(topic, round(0.7 * share, 3), s.sign, f"{side}.by_sector", {"sector": sector, "share": round(share, 3)},
                        f"{round(share * 100)}% платежей {label} приходится на отрасль «{SECTOR_NAMES.get(sector, sector)}»: {s.why}",
                        "payments")
    top1 = c["suppliers"]["top1_share"]
    if top1 and top1 > 0.5:
        add("corporate_finance", 0.5, -1, "suppliers.top1_share", round(top1, 3),
            f"{round(top1 * 100)}% платежей поставщикам уходит одному контрагенту — высокая концентрация цепочки поставок", "payments")
    return tuple(out)
