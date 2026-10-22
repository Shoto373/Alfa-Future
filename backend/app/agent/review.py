"""Смысловая проверка выводов AI второй моделью («критик»).

Детерминированные проверки ловят выдуманные цифры, источники и противоречия с
профилем, но не логику: «ставка выросла → депозиты невыгодны» пройдет их без
ошибок. Критик получает каждый вывод AI вместе с текстом его источников и
отвечает, следует ли вывод из них. Неподтвержденные выводы убираются, если
раздел от этого не опустеет. Сбой критика не ломает разбор: остается результат
детерминированных проверок, причина видна в трассе.
"""

import json

from app.agent import llm
from app.agent.prompts import GUARD

SECTIONS = ("why_important", "risks", "opportunities", "actions")
MAX_CLAIMS = 10  # бюджет токенов: модель-критик рассуждает над каждым выводом
# Критик — модель рассуждений с коротким рассуждением (GLM, reasoning_effort=low): на реальном разборе
# ~300 токенов и ~0,04 ₽; быстрая DeepSeek тратила >2000 токенов на рассуждения и упиралась в лимит.

REVIEW_SYSTEM = f"""Ты — строгий рецензент аналитики банка. Для каждого вывода реши, следует ли он из указанных источников.
supported — прямо следует из источников; partial — правдоподобен, но в источниках подтверждена только часть;
unsupported — не следует из источников или противоречит им (в том числе неверное направление эффекта).
Оценивай только логику и факты, не стиль. {GUARD}
Ответ — строго JSON: {{"verdicts": [{{"i": 0, "verdict": "supported|partial|unsupported", "reason": "до 80 символов"}}]}}"""


def _source_texts(ctx: dict, sources: list[dict]) -> dict[str, str]:
    news = ctx["news"]
    texts = {s["source_id"]: s.get("excerpt") or s["title"] for s in sources}
    texts[f"news:{news['news_id']}"] = f"{news['title']}. {news['text'][:1500]}"
    for t in ctx["theses"]:
        texts[f"bank:{t['id']}"] = t["text"]
    return texts


def review(draft: dict, ctx: dict, sources: list[dict]) -> dict:
    """Возвращает {'removed': [...], 'partial': n, 'supported': n, 'model': ...}; бросает llm.LLMError при сбое."""
    texts = _source_texts(ctx, sources)
    claims = [(sec, i, c) for sec in SECTIONS for i, c in enumerate(draft[sec]) if c["origin"] == "ai"][:MAX_CLAIMS]
    if not claims:
        return {"removed": [], "partial": 0, "supported": 0, "model": None, "reviewed": 0}
    payload = {
        "company": {"name": ctx["company"]["display_name"], "sector": ctx["company"]["sector_name"]},
        "claims": [{"i": n, "section": sec, "text": c["text"],
                    "sources": {sid: texts.get(sid, "")[:500] for sid in c["source_ids"][:3]}}
                   for n, (sec, _, c) in enumerate(claims)],
    }
    data, meta = llm.chat_json(REVIEW_SYSTEM, json.dumps(payload, ensure_ascii=False), "reasoning", 2000)
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, list):
        raise llm.LLMError("критик вернул ответ без verdicts")
    by_index = {v.get("i"): v for v in verdicts if isinstance(v, dict)}
    drop: dict[str, set[int]] = {}
    removed, partial, supported = [], 0, 0
    for n, (sec, i, c) in enumerate(claims):
        verdict = (by_index.get(n) or {}).get("verdict")
        if verdict == "unsupported":
            drop.setdefault(sec, set()).add(i)
            removed.append(f"{c['text'][:80]} — {str(by_index[n].get('reason', ''))[:120]}")
        elif verdict == "partial":
            partial += 1
        elif verdict == "supported":
            supported += 1
    for sec, idx in drop.items():
        kept = [c for i, c in enumerate(draft[sec]) if i not in idx]
        if kept:  # раздел не должен опустеть из-за критика
            draft[sec] = kept
        else:
            removed = [r for r in removed if not any(r.startswith(draft[sec][i]["text"][:80]) for i in idx)]
    return {"removed": removed, "partial": partial, "supported": supported, "model": meta["model"],
            "reviewed": len(claims)}
