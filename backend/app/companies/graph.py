"""Граф контрагентов (SPR4-01): кто кому платит, второй уровень цепочки поставок и связи через физлиц.

Ребро «плательщик → получатель» из df_Uid_payment_hack.csv: для плательщика получатель — поставщик
(доля в его исходящих платежах), для получателя плательщик — покупатель (доля во входящих).
Второй уровень: вес = доля₁ × доля₂ (поставщик вашего поставщика), с порогом SECOND_LEVEL_MIN — объяснение
цепочкой «вы → поставщик А (32% закупок) → его поставщик Б (51%)».
Связи через общих физлиц (df_Fid_Uid_link_hack.csv) — отдельный тип с низким весом и подписью «возможная связь»:
это не вывод о юридической аффилированности.
Граф строится из тех же CSV, что профили, один раз на подпись данных; ребра сохраняются в company_edges (воркер).
"""

import argparse
import csv
import json
import logging
import threading
import time
from collections import Counter, defaultdict
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete

from app import config, database
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.models import CompanyEdge

logger = logging.getLogger("app.companies.graph")

FIRST_LEVEL_MIN = 0.05   # контрагент первого уровня, через которого смотрим дальше: от 5% платежей
SECOND_LEVEL_MIN = 0.02  # цепочка второго уровня: доля₁ × доля₂ от 2%
PERSON_WEIGHT = 0.1      # связь через общих физлиц — слабый признак
TOP = 20
SYNC_KEY = "graph_signature"
_lock = threading.Lock()


@dataclass
class Graph:
    suppliers: dict[str, list[tuple[str, float, float, int]]] = field(default_factory=dict)  # cid -> (поставщик, доля, сумма, платежей)
    customers: dict[str, list[tuple[str, float, float, int]]] = field(default_factory=dict)
    persons: dict[str, set[str]] = field(default_factory=dict)  # cid -> компании с общими физлицами
    sectors: dict[str, str] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


def _num(value: str | None) -> float:
    try:
        return float((value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _payments(path: Path) -> dict[tuple[str, str], list]:
    flows: dict[tuple[str, str], list] = defaultdict(lambda: [0.0, 0])
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            payer, benef = (row.get("PAYER") or "").strip(), (row.get("BENEFICIARY") or "").strip()
            amount = _num(row.get("PAY_AMT"))
            if payer and benef and payer != benef and amount > 0:
                acc = flows[(payer, benef)]
                acc[0] += amount
                acc[1] += int(_num(row.get("PAY_CNT")))
    return flows


def _persons(path: Path) -> dict[str, set[str]]:
    by_person: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            fid, cid = (row.get("SYNTHETIC_F") or "").strip(), (row.get("SYNTHETIC_U") or "").strip()
            if fid and cid:
                by_person[fid].add(cid)
    linked: dict[str, set[str]] = defaultdict(set)
    for companies in by_person.values():
        for cid in companies:
            linked[cid] |= companies - {cid}
    return linked


def build(data_dir: Path) -> Graph:
    """Граф из CSV кейса; stats — размер, время построения и распределение степеней (docs/graph.md)."""
    started = time.perf_counter()
    flows = _payments(data_dir / "df_Uid_payment_hack.csv")
    out_total, in_total = Counter(), Counter()
    for (payer, benef), (amount, _) in flows.items():
        out_total[payer] += amount
        in_total[benef] += amount
    g = Graph()
    for (payer, benef), (amount, count) in flows.items():
        g.suppliers.setdefault(payer, []).append((benef, amount / out_total[payer], amount, count))
        g.customers.setdefault(benef, []).append((payer, amount / in_total[benef], amount, count))
    for side in (g.suppliers, g.customers):
        for edges in side.values():
            edges.sort(key=lambda e: -e[1])
    links = data_dir / "df_Fid_Uid_link_hack.csv"
    g.persons = _persons(links) if links.exists() else {}
    degrees = Counter(len(v) for v in g.suppliers.values())
    nodes = set(out_total) | set(in_total)
    g.stats = {"nodes": len(nodes), "payment_edges": len(flows),
               "person_links": sum(len(v) for v in g.persons.values()) // 2,
               "build_seconds": round(time.perf_counter() - started, 2),
               "out_degree": {"max": max(degrees, default=0), "median": _median(degrees),
                              "histogram": _histogram(degrees)}}
    return g


def _median(degrees: Counter) -> int:
    values = sorted(d for d, n in degrees.items() for _ in range(n))
    return values[len(values) // 2] if values else 0


def _histogram(degrees: Counter) -> dict[str, int]:
    bins = {"1": 0, "2–5": 0, "6–20": 0, "21–100": 0, ">100": 0}
    for d, n in degrees.items():
        key = "1" if d == 1 else "2–5" if d <= 5 else "6–20" if d <= 20 else "21–100" if d <= 100 else ">100"
        bins[key] += n
    return bins


_cache: tuple[str | None, Graph] | None = None


def current() -> Graph:
    """Граф по текущим данным кейса (строится один раз на подпись профилей в процессе)."""
    global _cache
    signature = profiles.signature()
    with _lock:
        if _cache is None or _cache[0] != signature:
            _cache = (signature, build(config.data_dir()))
            logger.info("graph built: %s", _cache[1].stats)
        return _cache[1]


def name(cid: str) -> str:
    """Название для интерфейса: из профилей (вымышленное демо-имя) или «компания отрасли …» — без новых данных."""
    p = profiles.get(cid)
    if p:
        return p["display_name"]
    return f"Контрагент {cid}"  # компании нет среди профилей — только идентификатор из данных кейса


def _sector(cid: str) -> str | None:
    p = profiles.get(cid)
    return SECTOR_NAMES.get(p["sector"]) if p else None


def _pct(share: float) -> str:
    return f"{share * 100:.0f}%"


REL = {"supplier": ("поставщик", "закупок", "его поставщик"), "customer": ("покупатель", "продаж", "его покупатель")}


def neighbors(company_id: str, depth: int = 2) -> list[dict]:
    """Контрагенты до второго уровня с цепочкой-объяснением. Первый уровень — все прямые, второй — с порогом веса."""
    g = current()
    out: dict[tuple[str, str], dict] = {}
    for relation, side in (("supplier", g.suppliers), ("customer", g.customers)):
        role, what, deeper = REL[relation]
        for cp, share, amount, count in side.get(company_id, []):
            first = f"вы → {role} {name(cp)} ({_pct(share)} {what})"
            out[(cp, relation)] = {"company_id": cp, "name": name(cp), "sector": _sector(cp), "relation": relation, "level": 1,
                                   "weight": share, "amount": amount, "count": count, "text": first}
            if depth < 2 or share < FIRST_LEVEL_MIN:
                continue
            for cp2, share2, _, _ in side.get(cp, []):
                weight = share * share2
                if cp2 == company_id or weight < SECOND_LEVEL_MIN or (cp2, relation) in out and out[(cp2, relation)]["level"] == 1:
                    continue
                if weight > out.get((cp2, relation), {}).get("weight", 0):
                    out[(cp2, relation)] = {"company_id": cp2, "name": name(cp2), "sector": _sector(cp2), "relation": relation,
                                            "level": 2, "weight": weight, "via": cp,
                                            "text": f"{first} → {deeper} {name(cp2)} ({_pct(share2)})"}
    for cp in sorted(g.persons.get(company_id, set())):
        out.setdefault((cp, "person"), {"company_id": cp, "name": name(cp), "sector": _sector(cp), "relation": "person",
                                        "level": 1, "weight": PERSON_WEIGHT,
                                        "text": f"вы → {name(cp)}: возможная связь через общих физлиц"})
    return sorted(out.values(), key=lambda x: (x["level"], -x["weight"]))


@lru_cache(maxsize=512)
def _strongest(company_id: str, _signature: str | None) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for n in neighbors(company_id):
        if n["weight"] > best.get(n["company_id"], {}).get("weight", -1):
            best[n["company_id"]] = n
    return best


def chain_to(company_id: str, target: str) -> dict | None:
    """Самая сильная цепочка от компании к контрагенту (для алерта, ленты и разбора); кэш на подпись данных."""
    return _strongest(company_id, profiles.signature()).get(target)


def sync() -> int:
    """Воркер: ребра графа — в company_edges при смене данных кейса. Возвращает число ребер (0 — без изменений)."""
    signature = profiles.signature()
    if database.state(SYNC_KEY) == signature:
        return 0
    g = current()
    share_in = {(payer, benef): share for benef, edges in g.customers.items() for payer, share, _, _ in edges}
    rows = [CompanyEdge(src=payer, dst=benef, kind="payment", share_out=share, share_in=share_in[(payer, benef)],
                        amount=amount, count=count)
            for payer, edges in g.suppliers.items() for benef, share, amount, count in edges]
    rows += [CompanyEdge(src=a, dst=b, kind="person", share_out=PERSON_WEIGHT, share_in=PERSON_WEIGHT, amount=0, count=0)
             for a, linked in g.persons.items() for b in linked if a < b]
    with database.session() as db:
        db.execute(delete(CompanyEdge))
        db.add_all(rows)
        database.set_state(SYNC_KEY, signature, db)
    return len(rows)


def main() -> None:
    """Профиль графа на CSV кейса: python -m app.companies.graph --data-dir ../data/synthetic (docs/graph.md)."""
    parser = argparse.ArgumentParser(description="Построить граф контрагентов из CSV кейса и показать его профиль")
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.data_dir).stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
