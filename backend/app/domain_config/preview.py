"""Предпросмотр версии конфигурации (SPR4-00): как изменится лента компании, без публикации.

Выполняется в воркере (задача domain_config_preview): кандидат временно применяется в процессе воркера,
новости переклассифицируются в памяти (без модели), лента считается до и после, затем действующая
конфигурация возвращается. Воркер выполняет задачи по одной, поэтому другие задачи кандидат не видят.
"""

import threading

from app import database
from app.domain_config import loader, runtime
from app.domain_config.validate import validate_texts

KEY = "domain_config_preview:"
TOP = 15
_lock = threading.Lock()


def _feed(items: list[dict], company_id: str, role: str, feed) -> list[dict]:
    return [{"news_id": r["news"]["news_id"], "title": r["news"]["title"], "score": r["relevance"]["score"],
             "topics": [t["topic"] for t in r["news"]["classification"]["topics"]]}
            for r in feed(items, company_id, role, None, TOP)]


def run(texts: dict[str, str], company_id: str, role: str, store, feed) -> dict:
    """store и feed передает вызывающий (слой services): доменная конфигурация не зависит от ленты."""
    docs, issues = validate_texts(texts)
    if any(i.level == "error" for i in issues):
        return {"status": "invalid", "issues": [i.as_dict() for i in issues]}
    current_texts, current_version = loader.current_texts()
    current_docs, _ = validate_texts(current_texts)
    items = store.all_items()
    before = _feed(items, company_id, role, feed)
    with _lock:
        try:
            runtime.apply(docs, current_version)
            reclassified = [{**n, **{k: v for k, v in store.make_item(n["title"], n["text"], n["source"], n.get("url"),
                                                                      n["published_at"], n["kind"], n["news_id"]).items()
                                     if k in ("classification", "lead")}} for n in items]
            after = _feed(reclassified, company_id, role, feed)
        finally:
            runtime.apply(current_docs, current_version)
    was = {r["news_id"]: i for i, r in enumerate(before)}
    for i, r in enumerate(after):
        r["rank_before"] = was.get(r["news_id"])
        r["rank"] = i
    gone = [r for r in before if r["news_id"] not in {a["news_id"] for a in after}]
    return {"status": "ready", "company_id": company_id, "role": role, "before": before, "after": after, "gone": gone,
            "issues": [i.as_dict() for i in issues]}


def save(preview_id: str, result: dict) -> None:
    with database.session() as db:
        database.set_state(KEY + preview_id, result, db)


def get(preview_id: str) -> dict | None:
    return database.state(KEY + preview_id)
