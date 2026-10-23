"""Профили крупных компаний: загрузка, поиск и экспозиции к макрофакторам.

Профили строит ETL (app.companies.etl) из CSV в DATA_DIR и сохраняет в
PostgreSQL. Экспозиции — объяснимые признаки, по которым
новости сопоставляются с компанией: каждая ссылается на поле данных.
"""

import json
import logging
import os
import threading
from functools import lru_cache

from app import config, database
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from app.models import Company
from app.companies import etl, names
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
        data_dir = config.data_dir()
        if not (data_dir / "df_Uid_data_hack.csv").exists():
            fallback = config.fallback_data_dir()
            logger.warning("no case CSV in %s, falling back to %s", data_dir, fallback)
            data_dir = fallback
        signature = _signature(data_dir)
        with database.session() as db:
            db.execute(select(func.pg_advisory_xact_lock(72810402)))
            meta = database.state("profiles", db)
            explicit = os.environ.get("PROFILES_PATH")  # optional legacy import / test fixture
            if not meta or meta.get("signature") != signature:
                if explicit:
                    from pathlib import Path
                    data = json.loads(Path(explicit).read_text(encoding="utf-8"))
                else:
                    if not signature:
                        raise ProfilesError(f"Нет данных: {data_dir}/df_Uid_data_hack.csv")
                    logger.info("building company profiles from %s", data_dir)
                    data = etl.build_profiles(data_dir)
                data["signature"] = signature
                data["synthetic"] = (data_dir / "SYNTHETIC").is_file()
                rows = [dict(company_id=c["company_id"], sector=c["sector"], revenue=c.get("revenue"), payload=c)
                        for c in data["companies"]]
                if rows:
                    stmt = insert(Company)
                    db.execute(stmt.on_conflict_do_update(index_elements=[Company.company_id],
                                 set_={k: getattr(stmt.excluded, k) for k in ("sector", "revenue", "payload")}), rows)
                meta = {k: v for k, v in data.items() if k != "companies"}
                meta["company_ids"] = [c["company_id"] for c in data["companies"]]
                database.set_state("profiles", meta, db)
            data = {k: v for k, v in meta.items() if k != "company_ids"}
            data["companies"] = list(db.scalars(select(Company.payload)
                .where(Company.company_id.in_(meta["company_ids"]))
                .order_by(Company.revenue.desc().nulls_last(), Company.company_id)))
        names.assign(data["companies"])  # вымышленные названия вместо «Компания №…»
        data["by_id"] = {c["company_id"]: c for c in data["companies"]}
        _cache = data
        exposures.cache_clear()
        return _cache


def _signature(data_dir) -> str | None:
    files = [data_dir / n for n in ("df_Uid_data_hack.csv", "df_Uid_payment_hack.csv", "df_Fid_Uid_link_hack.csv")]
    if not files[0].exists():
        return None
    return "v2|" + str((data_dir / "SYNTHETIC").is_file()) + "|" + "|".join(
        f"{f.name}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files if f.exists())


def reset_cache() -> None:
    global _cache
    _cache = None
    exposures.cache_clear()


def signature() -> str | None:
    """Подпись исходных CSV: меняется при пересборке профилей (ключ кэшей ленты)."""
    return _load().get("signature")


def meta() -> dict:
    d = _load()
    return {k: d.get(k) for k in ("generated_at", "source_dir", "total_companies", "selection_rule")} | {
        "profiles": len(d["companies"]), "synthetic": bool(d.get("synthetic", True))}


def list_companies(query: str = "", sector: str | None = None, limit: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
    items = _load()["companies"]
    q = query.strip().lower()
    if q:
        items = [c for c in items if q in c["company_id"].lower() or q in c["display_name"].lower()
                 or q in (c["okved_name"] or "").lower()
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
        add("key_rate", 1.2, -1, "products.loans", True, "Есть кредитные продукты: стоимость новых заимствований чувствительна к ставке; эффект для действующего долга зависит от договора")
        add("credit_market", 0.8, 1, "products.loans", True, "Есть кредитные продукты: условия кредитования влияют на финансирование")
        add("bonds", 0.4, -1, "products.loans", True, "Ставки рынка долга задают ориентир стоимости новых заимствований")
    if p.get("leasing"):
        add("key_rate", 0.6, -1, "products.leasing", True, "Есть лизинг: стоимость новых сделок и условия пересмотра платежей могут зависеть от стоимости фондирования")
    if p.get("deposits"):
        add("key_rate", 0.7, 1, "products.deposits", True, "Есть депозиты: высокая ставка повышает доходность размещения ликвидности")
        add("deposits", 0.6, 1, "products.deposits", True, "Есть депозиты: важна доходность размещения")
    if p.get("factoring"):
        add("corporate_finance", 0.6, 0, "products.factoring", True, "Есть факторинг: компания управляет дебиторской задолженностью")
        add("consumer_demand", 0.3, 1, "products.factoring", True, "Факторинг связан с отсрочками платежей покупателей")
    if p.get("guarantees"):
        add("budget", 0.6, 1, "products.guarantees", True, "Есть банковские гарантии: вероятны контракты, в т.ч. государственные")
    if p.get("payroll") or c.get("workers_fns") in ("101-250", "Более 251"):
        feature = "workers_fns" if c.get("workers_fns") else "products.payroll"
        why = f"Штат {c['workers_fns']} сотрудников: рост зарплат увеличивает издержки" if c.get("workers_fns") else \
            "Есть зарплатный проект: изменения зарплат могут влиять на расходы на персонал"
        add("labor", 0.6, -1, feature, c.get("workers_fns") or True, why)
    if c.get("fts_flag"):
        countries = ", ".join(c["fts_countries"]) or "страны не указаны"
        add("fx", 1.0, 0, "fts_countries", c["fts_countries"], f"Есть внешнеэкономическая деятельность ({countries}): курс влияет на расчеты")
        add("imports_exports", 1.0, 0, "fts_countries", c["fts_countries"], f"ВЭД с контрагентами: {countries}")
        add("sanctions_geopolitics", 0.7, -1, "fts_countries", c["fts_countries"], "ВЭД чувствительна к ограничениям на платежи и логистику")
        add("logistics", 0.6, -1, "fts_countries", c["fts_countries"], "ВЭД: поставки зависят от пропускной способности границ, портов и транзита")
    if c.get("revenue"):
        add("taxes_regulation", 0.6, -1, "revenue", c["revenue"],
            f"Выручка {_bn(c['revenue'])}: изменения налогов и регулирования напрямую меняют нагрузку на компанию")
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
