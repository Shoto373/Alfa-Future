"""RSS-ленты: загрузка с защитой от SSRF (news.parser) и полный текст статьи по ссылке."""

from dataclasses import dataclass

from app import config
from app.news import parser
from app.news.sources.base import Adapter, RawNews


@dataclass
class RssAdapter(Adapter):
    def _fetch(self) -> list[RawNews]:
        entries = parser.rss_entries(parser._get(self.url))[: config.rss_max_items()]
        return [RawNews(e["title"], e["text"], e["url"], e["published_at"]) for e in entries]

    def enrich(self, raw: RawNews) -> RawNews:
        # Полный текст — только где лицензия позволяет хранить его.
        if self.license != "full":
            return raw
        text = parser.full_text(raw.url, raw.text)
        return raw if text is raw.text else RawNews(raw.title, text, raw.url, raw.published_at, raw.external_id)
