"""Ручные материалы редакции: JSON-файл со списком {title, text, url?, published_at?}."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.news.sources.base import Adapter, RawNews


@dataclass
class ManualAdapter(Adapter):
    def _fetch(self) -> list[RawNews]:
        items = json.loads(Path(self.url).read_text(encoding="utf-8"))
        return [RawNews(i["title"], i["text"], i.get("url"), i.get("published_at"), i.get("id"))
                for i in items if i.get("title") and len(i.get("text", "")) >= 40]
