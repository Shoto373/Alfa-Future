"""Организации в тексте новости (SPR3-02): словарь компаний из профилей, ИНН/ОГРН и правовые формы.

Найденная организация привязывается к company_id, если она есть в профилях; иначе остается
с company_id=None (для мониторинга контрагентов в спринте 4). Распознавание — без модели:
1) названия из профилей в кавычках, после правовой формы или как последовательность слов с заглавной;
2) ИНН и ОГРН с проверкой контрольных цифр;
3) прочие организации «правовая форма + название в кавычках».
Индекс хранится в таблице news_entities (воркер, sync); лента и карточка считают упоминания в памяти.
"""

import hashlib
import re
from functools import lru_cache

from sqlalchemy import delete

from app import database
from app.companies import profiles
from app.models import NewsEntity

VERSION = "entities-v1"
INDEX_KEY = "news_entities_index"
FORMS = {
    "ооо": "ООО", "ао": "АО", "пао": "ПАО", "зао": "ЗАО", "оао": "ОАО", "нко": "НКО", "гк": "ГК",
    "общество с ограниченной ответственностью": "ООО", "акционерное общество": "АО",
    "публичное акционерное общество": "ПАО", "закрытое акционерное общество": "ЗАО",
    "открытое акционерное общество": "ОАО",
}
_FORM = "|".join(sorted((re.escape(f) for f in FORMS), key=len, reverse=True))
_QUOTE_OPEN, _QUOTE_CLOSE = "«\"“„'", "»\"”“'"
_QUOTED = re.compile(rf"(?:\b({_FORM})\s+)?[{_QUOTE_OPEN}]([^{_QUOTE_CLOSE}\n]{{2,80}})[{_QUOTE_CLOSE}]", re.IGNORECASE)
# Название без кавычек: до четырех слов с заглавной буквы («Сытый Колос Групп подписала…»).
_CAPS = re.compile(r"(?<![\w-])([А-ЯЁA-Z][\w-]*(?:[ -][А-ЯЁA-Z][\w-]*){0,3})")
_FORM_BARE = re.compile(rf"\b({_FORM})\s+([А-ЯЁA-Z][\w-]*(?:[ -][А-ЯЁA-Z0-9][\w-]*){{0,3}})", re.IGNORECASE)
_INN = re.compile(r"\bИНН\s*:?\s*(\d{10}|\d{12})\b")
_OGRN = re.compile(r"\bОГРН(?:ИП)?\s*:?\s*(\d{13}|\d{15})\b")
# Однословные названия из профилей («Витрина», «Облачко») — обычные слова: без кавычек или формы не считаются.
MIN_BARE_WORDS = 2


def normalize(name: str) -> str:
    """Ядро названия: без правовой формы и кавычек, нижний регистр, ё → е, единые пробелы и дефисы."""
    s = name.lower().replace("ё", "е")
    s = re.sub(rf"^\s*(?:{_FORM})\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(rf"[{_QUOTE_OPEN}{_QUOTE_CLOSE}]", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def _inn_ok(inn: str) -> bool:
    d = [int(c) for c in inn]

    def check(weights: list[int], digit: int) -> bool:
        return sum(w * x for w, x in zip(weights, d)) % 11 % 10 == d[digit]

    if len(d) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8], 9)
    return check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8], 10) and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8], 11)


def _ogrn_ok(ogrn: str) -> bool:
    base, mod = (ogrn[:12], 11) if len(ogrn) == 13 else (ogrn[:14], 13)
    return int(base) % mod % 10 == int(ogrn[-1])


@lru_cache(maxsize=2)
def _dictionary(_signature: str | None) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(ядро названия → company_id, company_id → название, ИНН/ОГРН → company_id) из профилей."""
    by_core, names, codes = {}, {}, {}
    for c in profiles.list_companies(limit=10**6)[1]:
        by_core[normalize(c["display_name"])] = c["company_id"]
        names[c["company_id"]] = c["display_name"]
        full = profiles.get(c["company_id"]) or {}
        for key in ("inn", "ogrn"):
            if full.get(key):
                codes[str(full[key])] = c["company_id"]
    return by_core, names, codes


def signature() -> str:
    """Подпись словаря: при смене профилей или правил индекс news_entities пересчитывается."""
    return hashlib.sha256(f"{VERSION}|{profiles.signature()}".encode()).hexdigest()[:16]


def _add(found: dict, name: str, company_id: str | None, method: str) -> None:
    key = company_id or normalize(name)
    if key not in found:
        found[key] = {"name": name, "company_id": company_id, "method": method}


def _known_in(text: str, by_core: dict, names: dict, found: dict) -> None:
    for m in _QUOTED.finditer(text):
        core = normalize(m.group(2))
        if core in by_core:
            _add(found, names[by_core[core]], by_core[core], "dictionary")
        elif m.group(1):  # «правовая форма + кавычки», но не из профилей — сторонняя организация
            _add(found, f"{FORMS[m.group(1).lower()]} «{m.group(2).strip()}»", None, "legal_form")
    for m in _FORM_BARE.finditer(text):
        words = m.group(2).split(" ")
        for n in range(len(words), 0, -1):  # самое длинное совпадение: «Сытый Колос Групп», затем «Сытый Колос»
            core = normalize(" ".join(words[:n]))
            if core in by_core:
                _add(found, names[by_core[core]], by_core[core], "dictionary")
                break
    for m in _CAPS.finditer(text):
        _bare(m.group(1).split(" "), by_core, names, found)


def _bare(words: list[str], by_core: dict, names: dict, found: dict) -> None:
    """Слова с заглавной подряд: самое длинное название из словаря с любого места («Компания Сытый Колос»)."""
    start = 0
    while start < len(words):
        for end in range(len(words), start, -1):
            core = normalize(" ".join(words[start:end]))
            if core in by_core and len(core.replace("-", " ").split()) >= MIN_BARE_WORDS:
                _add(found, names[by_core[core]], by_core[core], "dictionary")
                start = end
                break
        else:
            start += 1


def sync(items: list[dict], revision: int) -> int:
    """Воркер: индекс news_entities по всем новостям, если изменились новости или словарь. Возвращает число строк."""
    marker = {"signature": signature(), "revision": revision}
    if database.state(INDEX_KEY) == marker:
        return 0
    rows = index(items)
    with database.session() as db:
        database.set_state(INDEX_KEY, marker, db)
    return rows


def extract(text: str) -> list[dict]:
    """Организации в тексте: [{name, company_id | None, method}] в порядке первого упоминания."""
    by_core, names, codes = _dictionary(profiles.signature())
    found: dict[str, dict] = {}
    _known_in(text, by_core, names, found)
    for pattern, method, valid in ((_INN, "inn", _inn_ok), (_OGRN, "ogrn", _ogrn_ok)):
        for m in pattern.finditer(text):
            if valid(m.group(1)):
                cid = codes.get(m.group(1))
                _add(found, names[cid] if cid else f"{method.upper()} {m.group(1)}", cid, method)
    return list(found.values())


@lru_cache(maxsize=20_000)
def _for_news(news_id: str, title: str, text: str, _signature: str) -> tuple[dict, ...]:
    return tuple(extract(f"{title}. {text}"))


def of_news(item: dict) -> list[dict]:
    """Организации новости (кэш по news_id и подписи словаря: текст записи не меняется)."""
    return list(_for_news(item["news_id"], item["title"], item["text"], signature()))


def relations(company_id: str) -> dict[str, str]:
    """Связанные компании: company_id → self | supplier | customer (по платежам из профиля)."""
    return _relations(company_id, profiles.signature())


@lru_cache(maxsize=1024)
def _relations(company_id: str, _signature: str | None) -> dict[str, str]:
    c = profiles.get(company_id) or {}
    out = {company_id: "self"}
    for side, relation in (("suppliers", "supplier"), ("customers", "customer")):
        for t in (c.get(side) or {}).get("top", []):
            if t.get("in_dataset") and t.get("company_id"):
                out.setdefault(t["company_id"], relation)
    return out


def mentions(item: dict, company_id: str) -> list[dict]:
    """Организации новости с отношением к компании: self, supplier, customer или other."""
    rel = relations(company_id)
    return [{**e, "relation": rel.get(e["company_id"], "other") if e["company_id"] else "other"} for e in of_news(item)]


def index(items: list[dict]) -> int:
    """Записать организации новостей в news_entities (замена прежних строк этих новостей)."""
    if not items:
        return 0
    rows = [NewsEntity(news_id=i["news_id"], name=e["name"], company_id=e["company_id"], method=e["method"])
            for i in items for e in of_news(i)]
    with database.session() as db:
        db.execute(delete(NewsEntity).where(NewsEntity.news_id.in_([i["news_id"] for i in items])))
        db.add_all(rows)
    return len(rows)
