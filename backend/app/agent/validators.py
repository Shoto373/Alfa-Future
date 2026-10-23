"""Самопроверка черновика интерпретации.

Каждая проверка возвращает (passed, detail, fix): fix — какое действие
агент выполнит при провале (расширить поиск, убрать утверждение, дополнить
раздел правилами). Проверки детерминированы и работают в обоих режимах.
"""

import re

from app.news.store import similarity
from app.agent import evidence

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS = re.compile(r"(?<=\d)[  ](?=\d{3}(?!\d))")


# Метки периодов аналитики («7М26», «2П27», «3К26») — обозначения, а не числовые утверждения.
_PERIOD = re.compile(r"\b\d{1,2}[МПКMH]\d{2}\b")
_YEAR = re.compile(r"^(19|20)\d{2}$")


def _norm_numbers(text: str) -> set[str]:
    return {n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n
            for n in _NUM.findall(_THOUSANDS.sub("", text))}


def missing_numbers(text: str, cited: str, everything: str) -> set[str]:
    """Числа утверждения, которых нет в указанных источниках.

    Год (2027) и метку периода («2П27») достаточно найти в любом собранном источнике: это горизонт
    планирования, а не числовой факт. Проценты, суммы и ставки должны быть в источнике, на который сослались.
    """
    labels = set(_PERIOD.findall(text))
    missing = _norm_numbers(_PERIOD.sub(" ", text)) - _norm_numbers(cited)
    years = {n for n in missing if _YEAR.match(n)}
    known = _norm_numbers(everything)
    return (missing - years) | (years - known) | {m for m in labels if m not in everything}


def _claims(draft: dict) -> list[tuple[str, dict]]:
    out = [("what_happened", c) for c in draft["what_happened"]["facts"] + draft["what_happened"]["assumptions"]]
    for section in ("why_important", "risks", "opportunities", "actions"):
        out += [(section, c) for c in draft[section]]
    out += [("bank_view", c) for c in draft["bank_view"]["theses"]]
    return out


def claim_errors(section: str, c: dict, ctx: dict, source_ids: set[str]) -> set[str]:
    errors = set()
    ids = c.get("source_ids", [])
    texts = evidence.source_texts(ctx)
    if not ids or not set(ids) <= source_ids:
        errors.add("sources")
    if not set(c.get("features", [])) <= evidence.valid_features(ctx["company"]):
        errors.add("features")
    if c.get("origin") == "bank":
        if not ids or not all(s.startswith("bank:") for s in ids):
            errors.add("origin")
        elif evidence.normalized(c["text"]) not in {evidence.normalized(texts.get(s, "")) for s in ids}:
            errors.add("origin")
    if c.get("origin") == "fact":
        # Факт — дословно из новости, на которую ссылается: текущей или более ранней из истории сюжета.
        if not any(s.startswith("news:") and evidence.normalized(c["text"]) in evidence.normalized(texts.get(s, "")) for s in ids):
            errors.add("origin")
    if c.get("origin") == "client_data" and not any(s.startswith("client:") for s in ids):
        errors.add("origin")
    if missing_numbers(c["text"], " ".join(texts.get(s, "") for s in ids), " ".join(texts.values())):
        errors.add("numbers")
    if c.get("origin") in ("ai", "client_data") and evidence.contradictions(c["text"], ctx["company"]):
        errors.add("contradictions")
    if evidence.INSTRUCTION.search(c["text"]):
        errors.add("instruction")
    return errors


def check(draft: dict, ctx: dict, source_ids: set[str], grounding_text: str) -> list[dict]:
    results = []

    def add(name: str, passed: bool, detail: str, fix: str | None = None):
        results.append({"name": name, "passed": passed, "detail": detail, "fix": None if passed else fix})

    # 1. Полнота разделов.
    missing = [s for s in ("why_important", "actions") if not draft[s]]
    if not draft["what_happened"]["facts"]:
        missing.append("what_happened")
    if ctx.get("exposures") and not draft["risks"] and not draft["opportunities"]:
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
    add("bank_view_found", has_kb or bool(ctx.get("bank_search_complete")), "Найдены релевантные материалы банка" if has_kb else "Поиск выполнен; материалов банка по теме нет, это явно указано",
        "broaden_search")

    # 4. Цифры в выводах есть в источниках (минимизация фактологических ошибок).
    ungrounded = []
    source_texts = evidence.source_texts(ctx)
    everything = " ".join(source_texts.values())
    for section, c in _claims(draft):
        bad = missing_numbers(c["text"], " ".join(source_texts.get(s, "") for s in c["source_ids"]), everything)
        if bad:
            ungrounded.append((c["text"][:60], sorted(bad)))
    add("numbers_grounded", not ungrounded, "Все числа подтверждены источниками" if not ungrounded
        else f"Числа без подтверждения: {ungrounded[:3]}", "drop_ungrounded")

    # 5. Нет противоречий с данными клиента.
    contradictions = ["Утверждение о компании не подтверждено профилем" for _, c in _claims(draft)
                      if c["origin"] in ("client_data", "ai") and evidence.contradictions(c["text"], ctx["company"])]
    add("consistent_with_client", not contradictions, "Противоречий с данными клиента нет" if not contradictions
        else "; ".join(sorted(set(contradictions))), "drop_contradictions")

    # 6. Не пересказ: вывод опирается на признаки компании и несколько факторов.
    features = {f for _, c in _claims(draft) for f in c.get("features", [])}
    headline_copy = similarity(draft["headline"], ctx["news"]["title"] + " " + ctx["news"]["lead"]) > 0.5
    available = {e["feature"] for e in ctx.get("exposures", [])}
    personalized = not headline_copy and (len(features & available) >= min(2, len(available)) if available else
                                          "не найден" in " ".join(c["text"].lower() for c in draft["why_important"]))
    add("personalized", personalized,
        f"Использовано признаков компании: {len(features)}" if personalized
        else "Вывод слабо привязан к компании или повторяет новость", "fill_from_rules")
    invalid = [(section, claim_errors(section, c, ctx, source_ids)) for section, c in _claims(draft)]
    add("evidence_boundaries", not any(err for _, err in invalid),
        "Проверены типы источников, числа в указанных источниках и доступность признаков", "drop_invalid")
    headline_ok = not evidence.contradictions(draft["headline"], ctx["company"]) and \
        not (_norm_numbers(draft["headline"]) - _norm_numbers(" ".join(evidence.source_texts(ctx).values())))
    add("headline_grounded", headline_ok, "Проверены числа и противоречия в заголовке", "restore_headline")
    bank_texts = {evidence.normalized(t["text"]) for t in ctx["theses"]}
    summary = draft["bank_view"].get("summary")
    summary_ok = not summary or evidence.normalized(summary) in bank_texts
    add("bank_summary_grounded", summary_ok, "Резюме банка соответствует проверенному тезису", "restore_bank_summary")
    return results


def _repair(draft: dict, ctx: dict, source_ids: set[str]) -> list[str]:
    """Исправить, а не удалить, утверждения с поправимыми ошибками.

    1. Модель пометила свой пересказ тезиса банка как «Альфа-Банк» (или пересказ новости как «факт»).
       Позиция банка — только дословный тезис, поэтому такое утверждение становится «Выводом AI»
       со ссылкой на тот же тезис: граница сохраняется, содержание не теряется.
    2. Число есть в данных, но модель не сослалась на нужный источник — добавляем источник,
       где это число действительно встречается. Число, которого нет ни в одном источнике, по-прежнему удаляется.
    """
    texts = evidence.source_texts(ctx)
    relabeled = recited = 0
    claims = [(sec, c) for sec in ("why_important", "risks", "opportunities", "actions") for c in draft[sec]]
    claims += [("what_happened", c) for c in draft["what_happened"]["assumptions"]]
    for section, c in claims:
        errors = claim_errors(section, c, ctx, source_ids)
        # Только пересказ настоящего тезиса банка (или новости). «Позиция банка» со ссылкой на данные компании
        # — это подмена источника, такое утверждение удаляется, а не переклассифицируется.
        based_on = "bank:" if c["origin"] == "bank" else "news:"
        if "origin" in errors and c["origin"] in ("bank", "fact") and any(sid.startswith(based_on) for sid in c["source_ids"]):
            c["origin"] = "ai"
            c["text"] = re.sub(r"^(?:Альфа-)?Банк\s*:\s*", "", c["text"]).strip()
            c["text"] = c["text"][:1].upper() + c["text"][1:]
            relabeled += 1
            errors = claim_errors(section, c, ctx, source_ids)
        if "numbers" in errors and c["origin"] in ("ai", "client_data"):
            missing = _norm_numbers(c["text"]) - _norm_numbers(" ".join(texts.get(s, "") for s in c["source_ids"]))
            extra = [sid for sid, text in texts.items() if sid in source_ids and sid not in c["source_ids"]
                     and missing & _norm_numbers(text)]
            covered = set().union(*(_norm_numbers(texts[sid]) for sid in extra)) if extra else set()
            if extra and missing <= covered:
                c["source_ids"] = c["source_ids"] + extra[:3]
                recited += 1
    done = []
    if relabeled:
        done.append(f"переклассифицировано в «Вывод AI» (пересказ, а не дословный тезис): {relabeled}")
    if recited:
        done.append(f"добавлены источники, где встречаются числа: {recited}")
    return done


def apply_fix(draft: dict, results: list[dict], source_ids: set[str], grounding_text: str, ctx: dict | None = None) -> list[str]:
    """Чинит черновик по провалившимся проверкам. Возвращает список выполненных исправлений."""
    done = []
    fixes = {r["fix"] for r in results if not r["passed"]}
    grounded = _norm_numbers(grounding_text)
    if ctx is not None:
        done += _repair(draft, ctx, source_ids)

    def keep(section: str, c: dict) -> bool:
        if ctx is not None and claim_errors(section, c, ctx, source_ids):
            return False
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
    if ctx is not None:
        bv["theses"] = [c for c in bv["theses"] if not claim_errors("bank_view", c, ctx, source_ids)]
        bv["available"] = bool(bv["theses"])
        bv["summary"] = bv["theses"][0]["text"] if bv["theses"] else None
        if "restore_headline" in fixes:
            from app.agent import composer
            draft["headline"] = composer.compose(ctx)["headline"]
    return done
