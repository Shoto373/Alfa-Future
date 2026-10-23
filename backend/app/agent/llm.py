"""Клиент LLM: OpenAI-совместимый /chat/completions с allowlist моделей.

Ключ подключается через LLM_BASE_URL + LLM_API_KEY. Без ключа клиент
недоступен, и агент работает в режиме правил. Разрешены только модели
из Приложения 3 кейса. Перед вызовом стоимость резервируется в дневном
бюджете (app/llm_usage.py): параллельные вызовы не превышают лимит вместе.
"""

import json
import logging
import re
import time

import httpx

from app import config, llm_usage

logger = logging.getLogger("app.agent.llm")

CONNECT_TIMEOUT = 10.0
BREAKER_SECONDS = 60.0  # после сбоя соединения LLM не вызывается, чтобы не ждать тайм-аут на каждом шаге

_down_until = 0.0
PRIMARY_RETRY_SECONDS = 300.0  # после сбоя основного шлюза запросы сразу идут на запасной
_primary_down_until = 0.0


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
    global _down_until, _primary_down_until
    timeout = httpx.Timeout(s["timeout"], connect=CONNECT_TIMEOUT)
    headers = {"Authorization": f"Bearer {s['api_key']}"}
    bases = [b for b in (s["base_url"], s["fallback_base_url"]) if b]
    # Основной шлюз недавно не ответил — не ждем тайм-аут соединения на каждом вызове.
    if len(bases) > 1 and time.monotonic() < _primary_down_until:
        bases = bases[1:] + bases[:1]
    last: Exception | None = None
    for base in bases:
        try:
            return httpx.post(f"{base}/chat/completions", json=payload, timeout=timeout, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last = exc
            if base == s["base_url"]:
                _primary_down_until = time.monotonic() + PRIMARY_RETRY_SECONDS
            logger.warning("llm gateway unreachable base=%s", base)
    _down_until = time.monotonic() + BREAKER_SECONDS
    raise last or httpx.ConnectError("no LLM base url")


usage = llm_usage.usage  # дневной учет: потрачено, зарезервировано, отказы по бюджету, лимиты


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError("Модель не вернула JSON")
    return json.loads(text[start:end + 1])


def _failed(reservation: llm_usage.Reservation, committed: bool) -> None:
    """Вызов не удался: до списания — снять резерв, после — только отметить ошибку."""
    if committed:
        llm_usage.record_error()
    else:
        llm_usage.release(reservation)


def chat_json(system: str, user: str, model_kind: str = "compose", max_tokens: int = 2000) -> tuple[dict, dict]:
    """Вызов модели роли model_kind (plan | compose | review | qa) с ответом в JSON. Возвращает (json, meta)."""
    s = config.llm_settings()
    if not available():
        raise LLMError("LLM не подключена")
    model = s["models"].get(model_kind)
    if not model:
        raise LLMError(f"Неизвестная роль модели: {model_kind}")
    if not is_allowed(model):
        raise LLMError(f"Модель {model} не входит в список разрешенных кейсом")
    try:
        reservation = llm_usage.reserve(model, len(system) + len(user), max_tokens)
    except llm_usage.BudgetExceeded as exc:  # агент откатится к правилам, причина — в трассе
        raise LLMError(str(exc)) from exc

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if s["reasoning_effort"] and any(m in model for m in s["reasoning_effort_models"]):
        payload["reasoning_effort"] = s["reasoning_effort"]
    started = time.perf_counter()
    committed = False
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
        llm_usage.commit(reservation, tokens, llm_usage.cost_of(model, tokens, usage_info.get("cost")))
        committed = True
        if not isinstance(content, str):
            raise LLMError("Модель вернула ответ неподдерживаемого формата")
        if choice.get("finish_reason") == "length":
            raise LLMError("Ответ модели обрезан по лимиту токенов")
        data = _extract_json(content)
    except LLMError:
        _failed(reservation, committed)
        raise
    except (httpx.HTTPError, KeyError, ValueError, IndexError, TypeError, AttributeError) as exc:
        _failed(reservation, committed)
        logger.warning("llm call failed model=%s error=%s", model, type(exc).__name__)
        raise LLMError(f"Ошибка вызова модели: {type(exc).__name__}") from exc
    return data, {"model": model, "tokens": tokens, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
