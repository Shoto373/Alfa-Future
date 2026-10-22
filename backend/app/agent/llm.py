"""Клиент LLM: OpenAI-совместимый /chat/completions с allowlist моделей.

Ключ подключается через LLM_BASE_URL + LLM_API_KEY. Без ключа клиент
недоступен, и агент работает в режиме правил. Разрешены только модели
из Приложения 3 кейса; учитывается дневной лимит токенов.
"""

import json
import logging
import re
import time
from datetime import date

import httpx

from app import config, database
from app.models import LLMUsage
from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger("app.agent.llm")

CONNECT_TIMEOUT = 10.0
BREAKER_SECONDS = 60.0  # после сбоя соединения LLM не вызывается, чтобы не ждать тайм-аут на каждом шаге

_down_until = 0.0


class LLMError(Exception):
    pass


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", name.lower())


def is_allowed(model: str) -> bool:
    n = _norm(model)
    return any(_norm(a) in n for a in config.ALLOWED_MODELS)


def available() -> bool:
    s = config.llm_settings()
    return bool(s["base_url"] and s["api_key"]) and time.monotonic() >= _down_until


def _post(payload: dict, s: dict) -> httpx.Response:
    """POST на основной адрес шлюза; при ошибке соединения — на запасной (LLM_FALLBACK_BASE_URL)."""
    global _down_until
    timeout = httpx.Timeout(s["timeout"], connect=CONNECT_TIMEOUT)
    headers = {"Authorization": f"Bearer {s['api_key']}"}
    bases = [b for b in (s["base_url"], s["fallback_base_url"]) if b]
    last: Exception | None = None
    for base in bases:
        try:
            return httpx.post(f"{base}/chat/completions", json=payload, timeout=timeout, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last = exc
            logger.warning("llm gateway unreachable base=%s", base)
    _down_until = time.monotonic() + BREAKER_SECONDS
    raise last or httpx.ConnectError("no LLM base url")


def usage() -> dict:
    with database.session() as db:
        row = db.get(LLMUsage, date.today())
        tokens, cost, calls, errors = (row.tokens, row.cost, row.calls, row.errors) if row else (0, 0, 0, 0)
    s = config.llm_settings()
    return {"date": date.today().isoformat(), "tokens": tokens, "cost": round(float(cost), 3), "calls": calls,
            "errors": errors, "limit": s["daily_token_limit"], "cost_limit": s["daily_cost_limit"]}


def _record(tokens: int, error: bool = False, cost: float = 0.0, call: bool = True) -> None:
    with database.session() as db:
        stmt = insert(LLMUsage).values(day=date.today(), tokens=max(0, tokens), cost=max(0, cost),
                                       calls=int(call), errors=int(error))
        db.execute(stmt.on_conflict_do_update(index_elements=[LLMUsage.day],
            set_={k: getattr(LLMUsage, k) + getattr(stmt.excluded, k) for k in ("tokens", "cost", "calls", "errors")}))


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError("Модель не вернула JSON")
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str, model_kind: str = "reasoning", max_tokens: int = 2000) -> tuple[dict, dict]:
    """Вызов модели с ответом в JSON. Возвращает (json, meta)."""
    s = config.llm_settings()
    if not available():
        raise LLMError("LLM не подключена")
    model = s["model_reasoning"] if model_kind == "reasoning" else s["model_fast"]
    if not is_allowed(model):
        raise LLMError(f"Модель {model} не входит в список разрешенных кейсом")
    u = usage()
    if u["tokens"] >= u["limit"] or u["cost"] >= u["cost_limit"]:
        raise LLMError("Исчерпан дневной лимит LLM")

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if model_kind == "reasoning" and s["reasoning_effort"]:
        payload["reasoning_effort"] = s["reasoning_effort"]
    started = time.perf_counter()
    recorded = False
    try:
        resp = _post(payload, s)
        for optional in ("response_format", "reasoning_effort"):
            if resp.status_code == 400 and optional in resp.text and optional in payload:
                payload.pop(optional)
                resp = _post(payload, s)
        resp.raise_for_status()
        body = resp.json()
        choice = body["choices"][0]
        content = choice["message"].get("content") or ""
        usage_info = body.get("usage") or {}
        tokens = int(usage_info.get("total_tokens") or (len(system) + len(user) + len(content)) // 3)
        _record(tokens, cost=float(usage_info.get("cost") or 0.0))
        recorded = True
        if not isinstance(content, str):
            raise LLMError("Модель вернула ответ неподдерживаемого формата")
        if choice.get("finish_reason") == "length":
            raise LLMError("Ответ модели обрезан по лимиту токенов")
        data = _extract_json(content)
    except LLMError:
        _record(0, error=True, call=not recorded)
        raise
    except (httpx.HTTPError, KeyError, ValueError, IndexError, TypeError, AttributeError) as exc:
        _record(0, error=True, call=not recorded)
        logger.warning("llm call failed model=%s error=%s", model, type(exc).__name__)
        raise LLMError(f"Ошибка вызова модели: {type(exc).__name__}") from exc
    return data, {"model": model, "tokens": tokens, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
