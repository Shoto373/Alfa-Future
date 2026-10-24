"""Общее для scripts/eval_ranking.py и fit_ranking.py: путь к пакету app и чтение разметки."""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def read_labels(path: str) -> list[dict]:
    """Разметка из файла или каталога: JSONL (по паре в строке) или JSON {"labels": [...]} (выгрузка с экрана)."""
    root = Path(path)
    files = sorted(p for p in root.glob("*") if p.suffix in (".jsonl", ".json")) if root.is_dir() else [root]
    out: list[dict] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".jsonl":
            out += [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
            out += data["labels"] if isinstance(data, dict) else data
    return out
