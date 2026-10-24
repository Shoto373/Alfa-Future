"""Оценка и калибровка ранжирования (SPR3-06): метрики, веса из файла, подбор весов, экран разметки."""

import json
from pathlib import Path

import numpy as np
import pytest

from app import ranking, ranking_eval
from tests.conftest import register

LABELS = Path(__file__).parent / "golden" / "ranking" / "labels-draft.jsonl"


def _labels() -> list[dict]:
    return [json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_metrics():
    assert ranking_eval.ndcg([3, 2, 0]) == pytest.approx(1.0)
    assert ranking_eval.ndcg([0, 2, 3]) == pytest.approx(0.6064, abs=1e-4)
    assert ranking_eval.precision([3, 0, 2, 1], k=4) == 0.5
    assert ranking_eval.irrelevant_top3([0, 3, 0, 3]) == pytest.approx(2 / 3)
    assert ranking_eval.kappa([(3, 3), (0, 0), (2, 2), (1, 1)]) == pytest.approx(1.0)
    assert ranking_eval.kappa([(3, 0), (0, 3), (3, 0), (0, 3)]) < 0


def test_weights_from_file_and_cache_signature(tmp_path, monkeypatch):
    manual = ranking.weights()
    assert manual["version"] and set(ranking.FEATURES) <= set(manual["weights"])
    other = tmp_path / "w.json"
    other.write_text(json.dumps({**{k: manual[k] for k in ("version", "scale", "half_life_days")},
                                 "weights": {**manual["weights"], "exposure": 2.0}}), encoding="utf-8")
    monkeypatch.setenv("RANKING_WEIGHTS_FILE", str(other))
    assert ranking.weights()["signature"] != manual["signature"], "другие веса — другой ключ кэша ленты"
    other.write_text(json.dumps({"version": "x", "scale": 2.5, "half_life_days": 45, "weights": {"exposure": 1}}),
                     encoding="utf-8")
    with pytest.raises(ValueError):
        ranking.weights()


def test_eval_on_draft_labels(client):
    data = ranking_eval.rows(_labels())
    assert len(data) == 210, "все пары черновой разметки — на новостях демо-ленты"
    report = ranking_eval.evaluate(data, ranking.weights()["weights"])
    assert report["summary"]["queries"] == 15 and len(report["by_sector"]) == 5 and len(report["by_role"]) == 3
    assert 0 <= report["summary"]["ndcg@10"] <= 1


def test_fit_recovers_better_order_on_synthetic_data():
    rng = np.random.default_rng(7)
    data = []
    true = np.array([0.2, 3.0] + [1.0] * (len(ranking.FEATURES) - 2))  # разметчики ценят упоминание отрасли сильнее
    for q in range(8):
        for i in range(12):
            x = rng.random(len(ranking.FEATURES))
            data.append({"news_id": f"n{i}", "company_id": f"c{q}", "role": "cfo", "x": x,
                         "grade": int(min(3, (x @ true) // 2))})
    prior = {k: 1.0 for k in ranking.FEATURES}
    result = ranking_eval.cross_validate(data, prior, l2=0.1)
    assert result["fitted_ndcg"] >= result["manual_ndcg"]
    assert result["weights"]["sector_mention"] > result["weights"]["exposure"]
    assert all(v >= 0 for v in result["weights"].values()), "веса не отрицательны — причины остаются объяснимыми"


def test_labeling_screen_flow_and_kappa(client, new_client, monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "owner@example.com,second@example.com")
    assert new_client().get("/api/v1/admin/labeling/next").status_code == 401
    first = client.get("/api/v1/admin/labeling/next").json()
    pair = first["pair"]
    assert first["stats"]["planned"] == 210 and first["stats"]["overlap_planned"] == 42
    assert "score" not in json.dumps(pair) and pair["company"]["name"] and pair["news"]["title"]
    body = {k: pair[k] for k in ("news_id", "company_id", "role")} | {"grade": 3, "reason": "ставка — долг компании"}
    after = client.post("/api/v1/admin/labeling/labels", json=body).json()
    assert after["stats"]["labeled_pairs"] == 1
    assert (after["pair"]["news_id"], after["pair"]["company_id"]) != (pair["news_id"], pair["company_id"]), "дальше — следующая пара"

    second = new_client()
    register(second, "second@example.com")
    # Пары без оценок идут первыми; второе мнение по overlap-паре — когда новых не осталось. Проверяем напрямую.
    second.post("/api/v1/admin/labeling/labels", json={**body, "grade": 2})
    stats = client.get("/api/v1/admin/labeling/stats").json()
    # κ считается от двух пар с двумя мнениями; по одной паре согласованность не оценить.
    assert stats["overlap_done"] == 1 and stats["kappa"] is None and stats["annotators"] == {
        "owner@example.com": 1, "second@example.com": 1}
    exported = client.get("/api/v1/admin/labeling/export").json()["labels"]
    assert {x["grade"] for x in exported} == {2, 3}
