"""Качество классификации на эталоне tests/fixtures/golden_news.json.

    python -m app.eval_classify                # словари + смысл (если модель включена)
    python -m app.eval_classify --llm          # + модель-классификатор для неуверенных случаев

Итог на эталоне (36 новостей): словари — recall 0.92, шум 0; + смысл — business 1.0, recall 1.0, шум 0;
+ Gemma — шум 0.11 без прироста recall, поэтому по умолчанию модель-классификатор выключена (CLASSIFY_LLM).

Метрики:
- business_acc  деловая/не деловая определена верно;
- topic_recall  у деловой новости найдена хотя бы одна ожидаемая тема (главная задача — не потерять событие);
- topic_precision доля найденных тем, которые есть в разметке;
- noise_rate    доля не деловых новостей, получивших темы (попадут в ленту зря).
"""

import argparse
import json
from pathlib import Path

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "golden_news.json"


def evaluate(use_llm: bool = False) -> dict:
    from app.news import llm_classify
    from app.news.classifier import classify

    items = json.loads(GOLDEN.read_text(encoding="utf-8"))["items"]
    rows = []
    for it in items:
        cls = classify(it["title"], it["text"])
        if use_llm and cls.uncertain:
            hint = llm_classify.hint(it["title"], it["text"])
            if hint:
                cls = classify(it["title"], it["text"], hint)
        found = set(cls.topic_keys())
        rows.append({"title": it["title"], "expected": it["topics"], "found": sorted(found), "business": it["business"],
                     "paraphrase": it.get("paraphrase", False), "uncertain": cls.uncertain})
    biz = [r for r in rows if r["business"]]
    non = [r for r in rows if not r["business"]]
    found_total = sum(len(r["found"]) for r in biz)
    summary = {
        "n": len(rows),
        "business_acc": round(sum(bool(r["found"]) == r["business"] for r in rows) / len(rows), 3),
        "topic_recall": round(sum(bool(set(r["found"]) & set(r["expected"])) for r in biz) / len(biz), 3),
        "topic_precision": round(sum(len(set(r["found"]) & set(r["expected"])) for r in biz) / found_total, 3) if found_total else 0.0,
        "noise_rate": round(sum(bool(r["found"]) for r in non) / len(non), 3),
        "paraphrase_recall": round(sum(bool(set(r["found"]) & set(r["expected"])) for r in biz if r["paraphrase"])
                                   / max(1, sum(r["paraphrase"] for r in biz)), 3),
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    report = evaluate(ap.parse_args().llm)
    for r in report["rows"]:
        ok = bool(set(r["found"]) & set(r["expected"])) if r["business"] else not r["found"]
        print(("ok  " if ok else "MISS"), r["title"][:70], "->", r["found"], "| ожидалось", r["expected"])
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
