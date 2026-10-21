"""Сбор новостей: RSS-ленты и загрузка статьи по URL.

Безопасность: только http/https, запрет адресов внутренних сетей (SSRF),
ограничение размера ответа и тайм-аут. Текст из сети — недоверенные данные:
он только классифицируется и цитируется, но не исполняется как инструкция.
"""

import html
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from app import config
from app.news import store

MAX_BYTES = 2_000_000
TIMEOUT = 10.0
USER_AGENT = "AlfaPulseBot/1.0 (+hackathon prototype)"

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_DROP = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


class FetchError(Exception):
    pass


def clean_html(raw: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", raw or ""))).strip()


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Разрешены только адреса http и https")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise FetchError("Не удалось разрешить адрес") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise FetchError("Адреса внутренних сетей запрещены")
    return url


def _get(url: str, max_redirects: int = 3) -> str:
    # Редиректы проходим вручную: каждый адрес заново проверяется на SSRF.
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(max_redirects + 1):
            check_url(url)
            with client.stream("GET", url) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    url = str(httpx.URL(url).join(resp.headers["location"]))
                    continue
                if resp.status_code != 200:
                    raise FetchError(f"Источник ответил HTTP {resp.status_code}")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError("Ответ источника слишком большой")
                    chunks.append(chunk)
                return b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    raise FetchError("Слишком много перенаправлений")


def parse_rss(xml_text: str, source: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        fields = {child.tag.split("}")[-1]: child for child in node}
        title = clean_html(fields["title"].text if "title" in fields else "")
        # Element без дочерних узлов ложен в bool — поэтому явная проверка на None.
        body_node = next((fields[k] for k in ("full-text", "description", "summary", "content") if fields.get(k) is not None), None)
        text = clean_html(body_node.text if body_node is not None else "")
        link = fields.get("link")
        url = (link.text or link.get("href")) if link is not None else None
        published = None
        date_node = next((fields[k] for k in ("pubDate", "published", "updated") if fields.get(k) is not None), None)
        if date_node is not None and date_node.text:
            try:
                published = parsedate_to_datetime(date_node.text).isoformat()
            except (TypeError, ValueError):
                published = date_node.text.strip()
        if title and len(text) >= 40:
            items.append(store.make_item(title, text, source, url, published, "rss"))
    return items


def fetch_rss(source: dict) -> list[dict]:
    return parse_rss(_get(source["url"]), source["name"])


def fetch_article(url: str) -> dict:
    raw = _DROP.sub(" ", _get(url))
    title_match = _TITLE.search(raw)
    title = clean_html(title_match.group(1)) if title_match else url
    paragraphs = [clean_html(p) for p in _P.findall(raw)]
    text = " ".join(p for p in paragraphs if len(p) > 40)[:8000]
    if len(text) < 80:
        raise FetchError("Не удалось извлечь текст статьи")
    host = urlparse(url).hostname or "web"
    return store.make_item(title, text, host, url, None, "user")


def refresh() -> dict:
    """Опрашивает настроенные RSS-ленты. Ошибки источников не прерывают сбор."""
    report = {"added": 0, "duplicates": 0, "skipped": 0, "sources": []}
    for source in config.rss_sources():
        entry = {"name": source["name"], "url": source["url"], "fetched": 0, "error": None}
        try:
            items = fetch_rss(source)[: config.rss_max_items()]
            entry["fetched"] = len(items)
            for item in items:
                if not item["classification"]["topics"]:
                    report["skipped"] += 1  # не относится к бизнес-темам таксономии
                    continue
                _, created = store.add(item)
                report["added" if created else "duplicates"] += 1
        except (FetchError, httpx.HTTPError, ET.ParseError) as exc:
            entry["error"] = str(exc)[:200]
        report["sources"].append(entry)
    return report
