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
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from app import config
from app.news import semantic, store

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


def rss_entries(xml_text: str) -> list[dict]:
    """Сырые записи ленты (без классификации): title, text, url, published_at."""
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
            items.append({"title": title, "text": text, "url": url, "published_at": published})
    return items


def parse_rss(xml_text: str, source: str) -> list[dict]:
    return [store.make_item(e["title"], e["text"], source, e["url"], e["published_at"], "rss")
            for e in rss_entries(xml_text)]


def fetch_rss(source: dict) -> list[dict]:
    return parse_rss(_get(source["url"]), source["name"])


_ARTICLE = re.compile(r"<article[^>]*>(.*?)</article>", re.IGNORECASE | re.DOTALL)
# Служебные абзацы сайтов: подписки, cookies, «читайте также», копирайт.
_BOILERPLATE = re.compile(r"подпис(ывайтесь|ка)|cookie|читайте также|telegram-канал|все права защищены|©|"
                          r"нашли ошибку|реклама|присоединяйтесь", re.IGNORECASE)
FULL_TEXT_LIMIT = 8000
LEAD_OVERLAP = 0.5  # доля слов анонса, которые должны найтись в тексте статьи


def article_text(raw_html: str) -> str:
    """Основной текст статьи: абзацы из <article> (или всей страницы) без служебных блоков."""
    raw = _DROP.sub(" ", raw_html)

    def paragraphs(body: str) -> str:
        found = [clean_html(p) for p in _P.findall(body)]
        return " ".join(p for p in found if len(p) > 40 and not _BOILERPLATE.search(p))

    # Сначала — внутри <article>; если там нет абзацев (разметка сайта другая) — по всей странице.
    text = paragraphs(max(_ARTICLE.findall(raw), key=len, default="")) or paragraphs(raw)
    return text[:FULL_TEXT_LIMIT]


def full_text(url: str | None, rss_text: str) -> str:
    """Полный текст по ссылке из RSS; если не удалось или он не богаче анонса — анонс из ленты."""
    if not url or not config.rss_full_text():
        return rss_text
    try:
        text = article_text(_get(url))
    except (FetchError, httpx.HTTPError, ValueError):
        return rss_text
    # Текст статьи должен быть заметно длиннее анонса и содержать большую часть его слов:
    # иначе это служебная часть страницы (подвал, меню), а не сама статья.
    if len(text) < max(300, int(len(rss_text) * 1.3)):
        return rss_text
    lead = {w for w in store.tokenize(rss_text) if len(w) > 3}
    found = {w for w in store.tokenize(text) if len(w) > 3}
    return text if not lead or len(lead & found) / len(lead) >= LEAD_OVERLAP else rss_text


def fetch_article(url: str) -> dict:
    raw = _DROP.sub(" ", _get(url))
    title_match = _TITLE.search(raw)
    title = clean_html(title_match.group(1)) if title_match else url
    paragraphs = [clean_html(p) for p in _P.findall(raw)]
    text = " ".join(p for p in paragraphs if len(p) > 40)[:8000]
    if len(text) < 80:
        raise FetchError("Не удалось извлечь текст статьи")
    host = urlparse(url).hostname or "web"
    return store.make_item(title, text, host, url, None, "user", llm=True)


def refresh() -> dict:
    """Опрашивает настроенные RSS-ленты. Ошибки источников не прерывают сбор."""
    report = {"added": 0, "duplicates": 0, "skipped": 0, "full_text": 0, "sources": []}
    for source in config.rss_sources():
        entry = {"name": source["name"], "url": source["url"], "fetched": 0, "error": None}
        try:
            entries = rss_entries(_get(source["url"]))[: config.rss_max_items()]
            entry["fetched"] = len(entries)
            # Уже сохраненные новости не классифицируются заново (это самая дорогая часть опроса),
            # а векторы новых считаются одной пачкой.
            fresh = [e for e in entries if not store.known(e["title"], e["text"])]
            report["duplicates"] += len(entries) - len(fresh)
            # Полный текст статьи (параллельно): больше фактов, чисел и участников, чем в анонсе ленты.
            with ThreadPoolExecutor(max_workers=6) as pool:
                texts = list(pool.map(lambda e: full_text(e["url"], e["text"]), fresh))
            for e, text in zip(fresh, texts):
                report["full_text"] += text is not e["text"]
                e["text"] = text
            semantic.prime([store.clean(e["title"], e["text"]) for e in fresh])
            for e in fresh:
                item = store.make_item(e["title"], e["text"], source["name"], e["url"], e["published_at"], "rss", llm=True)
                if not item["classification"]["topics"]:
                    report["skipped"] += 1  # не относится к бизнес-темам таксономии
                    continue
                _, created = store.add(item)
                report["added" if created else "duplicates"] += 1
        except (FetchError, httpx.HTTPError, ET.ParseError) as exc:
            entry["error"] = str(exc)[:200]
        report["sources"].append(entry)
    return report
