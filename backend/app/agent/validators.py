"""Самопроверка черновика интерпретации.

Каждая проверка возвращает (passed, detail, fix): fix — какое действие
агент выполнит при провале (расширить поиск, убрать утверждение, дополнить
раздел правилами). Проверки детерминированы и работают в обоих режимах.
"""

import re

from app.news.store import similarity

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS = re.compile(r"(?<=\d)[  ](?=\d{3}(?!\d))")


def _norm_numbers(text: str) -> set[str]:
    return {n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n
            for n in _NUM.findall(_THOUSANDS.sub("", text))}


def _claims(draft: dict) -> list[tuple[str, dict]]:
    out = [("what_happened", c) for c in draft["what_happened"]["facts"] + draft["what_happened"]["assumptions"]]
    for section in ("why_important", "risks", "opportunities", "actions"):
        out += [(section, c) for c in draft[section]]
    out += [("bank_view", c) for c in draft["bank_view"]["theses"]]
    return out


def check(draft: dict, ctx: dict, source_ids: set[str], grounding_text: str) -> list[dict]:
    results = []

    def add(name: str, passed: bool, detail: str, fix: str | None = None):
        results.append({"name": name, "passed": passed, "detail": detail, "fix": None if passed else fix})

    # 1. Полнота разделов.
    missing = [s for s in ("why_important", "actions") if not draft[s]]
    if not draft["what_happened"]["facts"]:
        missing.append("what_happened")
    if not draft["risks"] and not draft["opportunities"]:
        missing.append("risks/opportunities")
    add("completeness", not missing, "Все разделы заполнены" if not missing else f"Пустые разделы: {', '.join(missing)}",
        "fill_from_rules")

    # 2. Каждое утверждение связано с существующим источником.
    unlinked = [c["text"][:60] for _, c in _claims(draft) if not c["source_ids"] or not set(c["source_ids"]) <= source_ids]
    add("sources_linked", not unlinked, "Каждое утверждение ссылается на источник" if not unlinked
        else f"Без источника или с неизвестным источником: {len(unlinked)}", "drop_unlinked")

    # 3. Позиция банка — только из материалов банка; нужна, если материалы есть.
    wrong_bank = [c for c in draft["bank_view"]["theses"]
                  if c["origin"] != "bank" or not all(s.startswith("bank:") for s in c["source_ids"])]
    has_kb = bool(ctx["theses"])
    add("bank_view_grounded", not wrong_bank and (draft["bank_view"]["available"] or not has_kb),
        "Позиция банка опирается только на материалы банка" if not wrong_bank else "В позиции банка есть утверждения не из материалов банка",
        "drop_unlinked")
    add("bank_view_found", has_kb, "Найдены релевантные материалы банка" if has_kb else "Материалы банка по теме не найдены",
        "broaden_search")

    # 4. Цифры в выводах есть в источниках (минимизация фактологических ошибок).
    grounded = _norm_numbers(grounding_text)
    ungrounded = []
    for section, c in _claims(draft):
        if c["origin"] == "ai" or section == "what_happened":
            bad = _norm_numbers(c["text"]) - grounded
            if bad:
                ungrounded.append((c["text"][:60], sorted(bad)))
    add("numbers_grounded", not ungrounded, "Все числа подтверждены источниками" if not ungrounded
        else f"Числа без подтверждения: {ungrounded[:3]}", "drop_ungrounded")

    # 5. Нет противоречий с данными клиента.
    p = ctx["company"]["products"]
    contradictions = []
    for _, c in _claims(draft):
        t = c["text"].lower()
        if c["origin"] in ("client_data", "ai"):
            if p.get("loans") is False and re.search(r"(ваш|у компании|ее|её)\s+(кредит|долг)", t):
                contradictions.append("утверждается наличие кредита, хотя кредитных продуктов нет")
            if not ctx["company"].get("fts_flag") and re.search(r"(ваш|у компании)\s+(импорт|экспорт|вэд)", t):
                contradictions.append("утверждается ВЭД, хотя признака ВЭД нет")
    add("consistent_with_client", not contradictions, "Противоречий с данными клиента нет" if not contradictions
        else "; ".join(sorted(set(contradictions))), "drop_contradictions")

    # 6. Не пересказ: вывод опирается на признаки компании и несколько факторов.
    features = {f for _, c in _claims(draft) for f in c.get("features", [])}
    headline_copy = similarity(draft["headline"], ctx["news"]["title"] + " " + ctx["news"]["lead"]) > 0.5
    add("personalized", len(features) >= 2 and not headline_copy,
        f"Использовано признаков компании: {len(features)}" if len(features) >= 2 and not headline_copy
        else "Вывод слабо привязан к компании или повторяет новость", "fill_from_rules")
    return results


def apply_fix(draft: dict, results: list[dict], source_ids: set[str], grounding_text: str) -> list[str]:
    """Чинит черновик по провалившимся проверкам. Возвращает список выполненных исправлений."""
    done = []
    fixes = {r["fix"] for r in results if not r["passed"]}
    grounded = _norm_numbers(grounding_text)

    def keep(section: str, c: dict) -> bool:
        if "drop_unlinked" in fixes and (not c["source_ids"] or not set(c["source_ids"]) <= source_ids):
            return False
        if "drop_ungrounded" in fixes and (c["origin"] == "ai" or section == "what_happened") and _norm_numbers(c["text"]) - grounded:
            return False
        return True

    for section in ("why_important", "risks", "opportunities", "actions"):
        before = len(draft[section])
        draft[section] = [c for c in draft[section] if keep(section, c)]
        if len(draft[section]) != before:
            done.append(f"{section}: удалено {before - len(draft[section])}")
    wh = draft["what_happened"]
    for key in ("facts", "assumptions"):
        before = len(wh[key])
        wh[key] = [c for c in wh[key] if keep("what_happened", c)]
        if len(wh[key]) != before:
            done.append(f"what_happened.{key}: удалено {before - len(wh[key])}")
    bv = draft["bank_view"]
    before = len(bv["theses"])
    bv["theses"] = [c for c in bv["theses"] if c["origin"] == "bank" and all(s.startswith("bank:") for s in c["source_ids"])]
    if len(bv["theses"]) != before:
        done.append(f"bank_view: удалено {before - len(bv['theses'])}")
    bv["available"] = bool(bv["theses"])
    return done
