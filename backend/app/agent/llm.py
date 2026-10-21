"""Клиент LLM: OpenAI-совместимый /chat/completions с allowlist моделей.

Ключ подключается через LLM_BASE_URL + LLM_API_KEY. Без ключа клиент
недоступен, и агент работает в режиме правил. Разрешены только модели
из Приложения 3 кейса; учитывается дневной лимит токенов.
"""

import json
import logging
import re
import threading
import time
from datetime import date

import httpx

from app import config

logger = logging.getLogger("app.agent.llm")

_usage_lock = threading.Lock()
_usage = {"date": date.today().isoformat(), "tokens": 0, "calls": 0, "errors": 0}


class LLMError(Exception):
    pass


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", name.lower())


def is_allowed(model: str) -> bool:
    n = _norm(model)
    return any(_norm(a) in n for a in config.ALLOWED_MODELS)


def available() -> bool:
    s = config.llm_settings()
    return bool(s["base_url"] and s["api_key"])


def usage() -> dict:
    with _usage_lock:
        if _usage["date"] != date.today().isoformat():
            _usage.update(date=date.today().isoformat(), tokens=0, calls=0, errors=0)
        return dict(_usage) | {"limit": config.llm_settings()["daily_token_limit"]}


def _record(tokens: int, error: bool = False) -> None:
    with _usage_lock:
        if _usage["date"] != date.today().isoformat():
            _usage.update(date=date.today().isoformat(), tokens=0, calls=0, errors=0)
        _usage["tokens"] += tokens
        _usage["calls"] += 1
        _usage["errors"] += int(error)


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
    if u["tokens"] >= u["limit"]:
        raise LLMError("Исчерпан дневной лимит токенов")

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    started = time.perf_counter()
    try:
        resp = httpx.post(f"{s['base_url']}/chat/completions", json=payload, timeout=s["timeout"],
                          headers={"Authorization": f"Bearer {s['api_key']}"})
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format")
            resp = httpx.post(f"{s['base_url']}/chat/completions", json=payload, timeout=s["timeout"],
                              headers={"Authorization": f"Bearer {s['api_key']}"})
        resp.raise_for_status()
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        tokens = int(body.get("usage", {}).get("total_tokens") or (len(system) + len(user) + len(content)) // 3)
        _record(tokens)
        data = _extract_json(content)
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        _record(0, error=True)
        logger.warning("llm call failed model=%s error=%s", model, type(exc).__name__)
        raise LLMError(f"Ошибка вызова модели: {type(exc).__name__}") from exc
    return data, {"model": model, "tokens": tokens, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
