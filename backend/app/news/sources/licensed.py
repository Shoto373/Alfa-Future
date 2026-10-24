"""Лицензированные ленты (Интерфакс, ПРАЙМ) — заглушка до договора.

Формат записей повторяет поставку агентств: Интерфакс — XML (headline, lead, body), ПРАЙМ — JSON
(title, annotation, text). Читается файл из LICENSED_FEED_DIR; с договором меняется только транспорт
(HTTPS с ключом), разбор и дальнейший путь новости те же. Лицензия «заголовок + лид»: тело не хранится.
"""

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from app.news.parser import clean_html
from app.news.sources.base import Adapter, RawNews


def parse_interfax(xml_text: str) -> list[RawNews]:
    out = []
    for node in ET.fromstring(xml_text).iter():
        if node.tag.split("}")[-1] != "news":
            continue
        fields = {child.tag.split("}")[-1]: (child.text or "") for child in node}
        lead = clean_html(fields.get("lead") or fields.get("body", ""))
        body = clean_html(fields.get("body", ""))
        title = clean_html(fields.get("headline", ""))
        if title and lead:
            out.append(RawNews(title, f"{lead} {body}".strip(), fields.get("url") or None, node.get("date"), node.get("id"), lead))
    return out


def parse_prime(json_text: str) -> list[RawNews]:
    out = []
    for item in json.loads(json_text).get("items", []):
        title, lead = clean_html(item.get("title", "")), clean_html(item.get("annotation", ""))
        if title and lead:
            text = f"{lead} {clean_html(item.get('text', ''))}".strip()
            out.append(RawNews(title, text, item.get("link"), item.get("datetime"), str(item.get("id", "")) or None, lead))
    return out


PARSERS = {"interfax": parse_interfax, "prime": parse_prime}


@dataclass
class LicensedFeedAdapter(Adapter):
    incremental = True

    def _fetch(self) -> list[RawNews]:
        return PARSERS[self.extra["format"]](Path(self.url).read_text(encoding="utf-8"))
