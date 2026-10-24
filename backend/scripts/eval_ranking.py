"""Качество ленты по экспертной разметке (SPR3-06): nDCG@10, precision@10, нерелевантные в топ-3.

    cd backend && python scripts/eval_ranking.py --labels tests/golden/ranking [--weights файл] [--json]

Нужна база с новостями из разметки (DATABASE_URL) и профили компаний (DATA_DIR / PROFILES_PATH).
"""

import argparse
import json

from _labels import read_labels

from app import ranking, ranking_eval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", required=True, help="файл или каталог разметки")
    parser.add_argument("--weights", help="другой файл весов (по умолчанию app/ranking_weights.json)")
    parser.add_argument("--json", action="store_true", help="отчет в JSON")
    args = parser.parse_args()
    weights = json.loads(open(args.weights, encoding="utf-8").read()) if args.weights else ranking.weights()
    data = ranking_eval.rows(read_labels(args.labels))
    report = ranking_eval.evaluate(data, weights["weights"])
    if args.json:
        print(json.dumps({**report, "weights_version": weights.get("version")}, ensure_ascii=False, indent=1))
        return 0
    s = report["summary"]
    print(f"Веса {weights.get('version')}: запросов {s.get('queries', 0)}, пар {s.get('pairs', 0)}")
    print(f"  nDCG@10 {s.get('ndcg@10')}  precision@10 {s.get('precision@10')}  нерелевантных в топ-3 {s.get('irrelevant_top3')}")
    for title, part in (("По отраслям", report["by_sector"]), ("По ролям", report["by_role"])):
        print(title)
        for name, m in part.items():
            print(f"  {name}: nDCG@10 {m['ndcg@10']}, precision@10 {m['precision@10']}, топ-3 нерелевантных {m['irrelevant_top3']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
