"""Калибровка весов ранжирования по разметке (SPR3-06): попарная логистическая регрессия на numpy,
регуляризация к ручным весам, кросс-валидация по компаниям.

    cd backend && python scripts/fit_ranking.py --labels tests/golden/ranking --cv companies [--write]

Новые веса записываются в app/ranking_weights.json только с --write и только если nDCG@10 на отложенных
компаниях вырос. Затем обязательно: python -m pytest tests/test_relevance_regressions.py — регрессии зеленые.
"""

import argparse
import json
from datetime import date

from _labels import read_labels

from app import ranking, ranking_eval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", default="tests/golden/ranking", help="файл или каталог разметки")
    parser.add_argument("--cv", choices=["companies"], default="companies", help="разбиение кросс-валидации")
    parser.add_argument("--l2", type=float, default=1.0, help="сила притяжения к ручным весам")
    parser.add_argument("--write", action="store_true", help="записать веса, если они лучше на отложенных компаниях")
    args = parser.parse_args()
    current = ranking.weights()
    data = ranking_eval.rows(read_labels(args.labels))
    result = ranking_eval.cross_validate(data, current["weights"], args.l2)
    print(f"Пар {len(data)}, компаний {len(result['folds'])}")
    for f in result["folds"]:
        print(f"  {f['company_id']}: ручные {f['manual']}, подобранные {f['fitted']}")
    print(f"nDCG@10 на отложенных компаниях: ручные {result['manual_ndcg']}, подобранные {result['fitted_ndcg']}")
    print("Веса:", json.dumps(result["weights"], ensure_ascii=False))
    better = result["fitted_ndcg"] is not None and result["manual_ndcg"] is not None \
        and result["fitted_ndcg"] > result["manual_ndcg"]
    if not args.write:
        return 0
    if not better:
        print("Веса не записаны: на отложенных компаниях они не лучше текущих")
        return 1
    data_out = {k: current[k] for k in ("note", "scale", "half_life_days")}
    data_out = {"version": f"{date.today():%Y-%m}-fit-{len(data)}", **data_out, "weights": result["weights"],
                "fit": {"labels": args.labels, "pairs": len(data), "cv": args.cv, "l2": args.l2,
                        "manual_ndcg": result["manual_ndcg"], "fitted_ndcg": result["fitted_ndcg"]}}
    ranking.WEIGHTS_FILE.write_text(json.dumps(data_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Записано: {ranking.WEIGHTS_FILE}. Проверьте регрессии: python -m pytest tests/test_relevance_regressions.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
