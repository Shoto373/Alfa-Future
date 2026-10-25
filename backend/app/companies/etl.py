"""ETL: CSV кейса -> профили крупных компаний (JSON).

Входные файлы (разделитель «;», схема из Приложения 1 кейса):
    df_Uid_data_hack.csv       — юрлица
    df_Uid_payment_hack.csv    — платежи между юрлицами
    df_Fid_Uid_link_hack.csv   — связи физлиц с юрлицами

Только стандартная библиотека: ETL запускается в runtime-образе без pandas.
Шумные данные обрабатываются явно: пропуски -> None, выручка-заглушка 1000 ₽,
«группы» из сотен разнородных компаний помечаются как ненадежные.

    python -m app.companies.etl --data-dir ../data/synthetic --out ../data/processed/companies.json
"""

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from app.companies.sectors import SECTOR_NAMES, sector_for_okved

LARGE_REVENUE = 15e9           # крупный бизнес по условию кейса
GROUP_MEMBER_MIN_REVENUE = 1e9  # участник группы > 15 млрд попадает в выборку с этой выручкой
MAX_RELIABLE_GROUP = 50         # для отбора в выборку: группы крупнее не «дотягивают» мелких участников
# Группа используется в выводах, если у ее выручки есть центр: отрасль с долей не меньше этой.
# Число компаний не критерий: у девелопера сотни проектных юрлиц, но выручка — в стройке и недвижимости.
GROUP_FOCUS_SHARE = 0.2
PLACEHOLDER_REVENUE = 1000.0    # 601 компания имеет ровно 1000 ₽ — заглушка
TOP_COUNTERPARTIES = 8

PRODUCT_COLUMNS = {
    "rko": "CL_PRODUCT_RKO_MARK",
    "guarantees": "CL_PRODUCT_GAR_MARK",
    "loans": "CL_PRODUCT_LOA_MARK",
    "leasing": "CL_PRODUCT_LEA_MARK",
    "deposits": "CL_PRODUCT_DEP_MARK",
    "payroll": "CL_PRODUCT_ZPP_MARK",
    "factoring": "FACTORING_MARK",
}


def _flag(value: str | None) -> bool | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value) >= 1
    except ValueError:
        return None


def _num(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _countries(value: str | None) -> list[str]:
    return [c.strip().title() for c in (value or "").split(",") if c.strip()]


def _open(path: Path):
    return path.open(encoding="utf-8-sig", newline="")


def read_companies(path: Path) -> dict[str, dict]:
    companies: dict[str, dict] = {}
    with _open(path) as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            cid = _text(row.get("SYNTHETIC_U"))
            if not cid:
                continue
            code = _text(row.get("MAINOKVED_CODE"))
            revenue = _num(row.get("REVENUE_COMPANY"))
            companies[cid] = {
                "company_id": cid,
                "okved_code": code,
                "okved_name": _text(row.get("MAINOKVED_NAME")),
                "sector": sector_for_okved(code),
                "ownership": _text(row.get("OKFS_NAME")),
                "age_years": _text(row.get("COMPANY_AGE_YEARS_GRADATION")),
                "stage": _text(row.get("ECO_MARK_LABEL")),
                "key_owner_mark": _flag(row.get("NEGATIVEMARK")),
                "workers_fns": _text(row.get("AMOUNT_WORKERS_FNS_GRADATION")),
                "workers_spark": _text(row.get("AMOUNT_WORKERS_SPARK_GRADATION")),
                "client_type": _text(row.get("CL_TYPE")),
                "products": {k: _flag(row.get(col)) for k, col in PRODUCT_COLUMNS.items()},
                "fts_flag": _flag(row.get("FTS_FLAG")),
                "fts_countries": _countries(row.get("FTS_COUNTRY_NAME")),
                "revenue": revenue,
                "group_id": _text(row.get("GROUP_ID")),
                "city": _text(row.get("CITY")),
                "region": _text(row.get("REGION")),
            }
    return companies


def select_large(companies: dict[str, dict]) -> tuple[set[str], dict[str, dict]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for cid, c in companies.items():
        if c["group_id"]:
            groups[c["group_id"]].append(cid)

    group_stats = {}
    for gid, members in groups.items():
        revenue = sum(companies[m]["revenue"] or 0 for m in members)
        sectors = Counter(companies[m]["sector"] for m in members)
        # Доли выручки группы по отраслям (заглушки выручки не считаются).
        by_sector: Counter = Counter()
        for m in members:
            r = companies[m]["revenue"] or 0
            if r > PLACEHOLDER_REVENUE and companies[m]["sector"] not in (None, "unknown"):
                by_sector[companies[m]["sector"]] += r
        total = sum(by_sector.values())
        shares = [{"sector": s, "share": round(v / total, 3)} for s, v in by_sector.most_common(4)] if total else []
        focus = [x["sector"] for x in shares if x["share"] >= GROUP_FOCUS_SHARE]
        group_stats[gid] = {
            "group_id": gid,
            "members": len(members),
            "revenue": revenue,
            "reliable": len(members) <= MAX_RELIABLE_GROUP,
            "top_sectors": [s for s, _ in sectors.most_common(3)],
            "sector_shares": shares,
            "focus_sectors": focus,
            "usable": len(members) >= 2 and bool(focus),
        }

    selected = set()
    for cid, c in companies.items():
        revenue = c["revenue"] or 0
        group = group_stats.get(c["group_id"] or "")
        if revenue > LARGE_REVENUE:
            selected.add(cid)
        elif group and group["reliable"] and group["revenue"] > LARGE_REVENUE and revenue >= GROUP_MEMBER_MIN_REVENUE:
            selected.add(cid)
    return selected, group_stats


def industry_stats(companies: dict[str, dict]) -> dict[str, dict]:
    by_okved: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for cid, c in companies.items():
        if c["okved_code"] and c["revenue"] and c["revenue"] > PLACEHOLDER_REVENUE:
            by_okved[c["okved_code"]].append((c["revenue"], cid))
    stats = {}
    for code, items in by_okved.items():
        items.sort(reverse=True)
        total = sum(r for r, _ in items)
        for rank, (rev, cid) in enumerate(items, 1):
            stats[cid] = {"okved_peers": len(items), "okved_rank": rank, "okved_share": rev / total if total else None}
    return stats


def aggregate_payments(path: Path, selected: set[str]) -> dict[str, dict]:
    out = {cid: {"in": defaultdict(lambda: [0.0, 0]), "out": defaultdict(lambda: [0.0, 0]), "self": 0.0}
           for cid in selected}
    with _open(path) as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            payer, benef = _text(row.get("PAYER")), _text(row.get("BENEFICIARY"))
            amt, cnt = _num(row.get("PAY_AMT")) or 0.0, int(_num(row.get("PAY_CNT")) or 0)
            if not payer or not benef or amt <= 0:
                continue
            if payer == benef:
                if payer in out:
                    out[payer]["self"] += amt
                continue
            if payer in out:
                acc = out[payer]["out"][benef]
                acc[0] += amt
                acc[1] += cnt
            if benef in out:
                acc = out[benef]["in"][payer]
                acc[0] += amt
                acc[1] += cnt
    return out


def read_links(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    persons_by_company: dict[str, set[str]] = defaultdict(set)
    companies_by_person: dict[str, set[str]] = defaultdict(set)
    person_region: dict[str, str] = {}
    with _open(path) as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            fid, cid = _text(row.get("SYNTHETIC_F")), _text(row.get("SYNTHETIC_U"))
            if not fid or not cid:
                continue
            persons_by_company[cid].add(fid)
            companies_by_person[fid].add(cid)
            if _text(row.get("RC_NAME")):
                person_region[fid] = row["RC_NAME"].strip()
    return persons_by_company, companies_by_person, person_region


def _counterparties(flows: dict, companies: dict[str, dict], group_id: str | None) -> dict:
    total = sum(v[0] for v in flows.values())
    ranked = sorted(flows.items(), key=lambda kv: kv[1][0], reverse=True)
    sector_amounts: Counter = Counter()
    unknown = 0.0
    intra = 0.0
    for cp, (amt, _) in flows.items():
        info = companies.get(cp)
        if info is None or info["sector"] in (None, "unknown"):
            unknown += amt
        else:
            sector_amounts[info["sector"]] += amt
        if info and group_id and info["group_id"] == group_id:
            intra += amt
    known = total - unknown
    top = []
    for cp, (amt, cnt) in ranked[:TOP_COUNTERPARTIES]:
        info = companies.get(cp)
        top.append({
            "company_id": cp,
            "in_dataset": info is not None,
            "okved_name": info["okved_name"] if info else None,
            "sector": info["sector"] if info else "unknown",
            "region": info["region"] if info else None,
            "amount": amt,
            "count": cnt,
            "share": amt / total if total else None,
        })
    return {
        "total_amount": total,
        "counterparties": len(flows),
        "top": top,
        "top1_share": top[0]["share"] if top else None,
        "intra_group_share": intra / total if total else None,
        # Доля оборота с известной отраслью; «unknown» (контрагент вне выборки) не занимает место среди отраслей.
        "known_share": known / total if total else 0.0,
        "unknown_share": unknown / total if total else 0.0,
        # share — от всего оборота (как раньше), share_known — от его известной части (по ней порог и веса).
        "by_sector": [
            {"sector": s, "share": a / total, "share_known": a / known if known else 0.0}
            for s, a in sector_amounts.most_common(6) if total
        ],
    }


def _data_quality(c: dict, group: dict | None, pay: dict) -> list[str]:
    """Пробелы и оговорки в данных компании — для профиля и проверок разбора."""
    quality = []
    if c["revenue"] is None or c["revenue"] <= PLACEHOLDER_REVENUE:
        quality.append("Выручка отсутствует или указана заглушкой")
    if not c["okved_code"]:
        quality.append("Не указан основной ОКВЭД")
    if c["stage"] is None:
        quality.append("Не указана стадия развития бизнеса")
    if c["workers_spark"] is None:
        quality.append("Численность по СПАРК отсутствует, используется оценка ФНС")
    if group and group["members"] >= 2 and not group["usable"]:
        quality.append(f"Выручка группы из {group['members']} компаний разбросана по отраслям без явного центра — "
                       "группа не используется для выводов")
    if c["fts_flag"] and not c["fts_countries"]:
        quality.append("Есть признак ВЭД, но страны не указаны")
    if not pay["in"] and not pay["out"]:
        quality.append("Нет платежей в выборке — контрагенты неизвестны")
    return quality


def build_profiles(data_dir: Path) -> dict:
    started = time.perf_counter()
    companies = read_companies(data_dir / "df_Uid_data_hack.csv")
    selected, groups = select_large(companies)
    industries = industry_stats(companies)
    payments = aggregate_payments(data_dir / "df_Uid_payment_hack.csv", selected)
    persons_by_company, companies_by_person, person_region = read_links(data_dir / "df_Fid_Uid_link_hack.csv")

    sector_revenue: Counter = Counter()
    for c in companies.values():
        if c["revenue"] and c["revenue"] > PLACEHOLDER_REVENUE:
            sector_revenue[c["sector"]] += c["revenue"]

    profiles = []
    for cid in sorted(selected, key=lambda x: -(companies[x]["revenue"] or 0)):
        c = dict(companies[cid])
        group = groups.get(c["group_id"] or "")
        persons = persons_by_company.get(cid, set())
        affiliated = set()
        for fid in persons:
            affiliated |= companies_by_person.get(fid, set())
        affiliated.discard(cid)
        pay = payments[cid]

        quality = _data_quality(c, group, pay)

        industry = industries.get(cid, {})
        c.update({
            "display_name": f"Компания {cid.replace('U_', '№')}",
            "sector_name": SECTOR_NAMES.get(c["sector"], c["sector"]),
            "is_synthetic_id": True,
            "market": {
                "okved_peers": industry.get("okved_peers"),
                "okved_rank": industry.get("okved_rank"),
                "okved_share": industry.get("okved_share"),
                "sector_share": (c["revenue"] / sector_revenue[c["sector"]])
                if c["revenue"] and sector_revenue[c["sector"]] else None,
                "note": "Доля и место — внутри набора данных кейса, а не всего рынка",
            },
            "group": {
                "group_id": c["group_id"],
                "members": group["members"] if group else None,
                "revenue": group["revenue"] if group else None,
                "reliable": group["reliable"] if group else None,
                "top_sectors": group["top_sectors"] if group else [],
                "sector_shares": group["sector_shares"] if group else [],
                "focus_sectors": group["focus_sectors"] if group else [],
                "usable": group["usable"] if group else False,
            },
            "suppliers": _counterparties(pay["out"], companies, c["group_id"]),
            "customers": _counterparties(pay["in"], companies, c["group_id"]),
            "self_transfers": pay["self"],
            "linked_persons": len(persons),
            "affiliated_companies": len(affiliated),
            "affiliated_sample": sorted(affiliated)[:10],
            "person_regions": [r for r, _ in Counter(person_region.get(f) for f in persons if person_region.get(f)).most_common(3)],
            "data_quality": quality,
        })
        profiles.append(c)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_dir": data_dir.name,
        "total_companies": len(companies),
        "selection_rule": f"выручка > {LARGE_REVENUE / 1e9:.0f} млрд ₽ или участник надежной группы (≤ {MAX_RELIABLE_GROUP} компаний) с выручкой группы > {LARGE_REVENUE / 1e9:.0f} млрд ₽ и собственной ≥ {GROUP_MEMBER_MIN_REVENUE / 1e9:.0f} млрд ₽",
        "build_seconds": round(time.perf_counter() - started, 1),
        "companies": profiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Построить профили крупных компаний из CSV кейса")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = build_profiles(args.data_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"{len(result['companies'])} профилей из {result['total_companies']} компаний за {result['build_seconds']} с -> {args.out}")


if __name__ == "__main__":
    main()
