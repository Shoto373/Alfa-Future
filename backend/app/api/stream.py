"""Потоковый разбор (SPR4-03): GET /api/v1/insights/stream — Server-Sent Events.

Порядок событий:
  section × N — разделы проверенного разбора на правилах (доли секунды): пользователь сразу видит содержание;
  insight     — тот же разбор целиком (валидный Insight) для интерфейса;
  sources     — источники разбора;
  stage       — ход работы агента с моделью (план, инструменты, черновик, проверки) — индикатор этапа;
  progress    — веха хода модели: {stage, index, total, state: start|done, label[, step: fix]} — индикатор прогресса;
  plan, review — план модели-исследователя и итог проверок;
  section_replaced — раздел версии модели, прошедший те же проверки, заменяет раздел правил;
  done        — итоговый разбор (валидный Insight); error — ошибка (разбор на правилах у пользователя остается).
Непроверенный текст в поток не попадает: разделы отдаются только из разборов, прошедших validators.
Без SSE (прокси, старый браузер) интерфейс использует прежний POST /insights.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app import config, llm, storage
from app.agent import orchestrator, stages
from app.api.router import ERRORS, _company, _news, limited
from app.auth.deps import member_of
from app.errors import ApiError
from app.schemas import Insight, Role

logger = logging.getLogger("app.api.stream")
router = APIRouter(prefix="/api/v1")

SECTIONS = ("headline", "effect", "what_happened", "why_important", "risks", "opportunities", "actions", "bank_view",
            "products", "questions")
HEARTBEAT_SECONDS = 15.0


def _event(name: str, data) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _valid(insight: dict) -> dict:
    """Итоговый разбор проходит схему контракта — как ответ POST /insights."""
    return Insight.model_validate(insight).model_dump(mode="json")


def _sections(insight: dict, event: str = "section", previous: dict | None = None) -> list[bytes]:
    return [_event(event, {"name": s, "value": insight.get(s), "mode": insight["mode"]}) for s in SECTIONS
            if previous is None or insight.get(s) != previous.get(s)]


async def _build(c: dict, role: str, n: dict, request_id: str, use_llm: bool | None) -> dict:
    async def save(insight: dict) -> None:
        await asyncio.to_thread(storage.save_insight, insight)
        # Этап «Оформляем карточку» заканчивается, когда карточка сохранена: сразу после этого приходит итог.
        stages.mark("finalize", "done")
    job = orchestrator.run_once(c, role, n, request_id, use_llm=use_llm, on_built=save)
    insight, _ = await asyncio.wait_for(job, timeout=config.analysis_timeout())
    return insight


async def _upgrade(c: dict, role: str, n: dict, request_id: str, queue: asyncio.Queue) -> dict:
    """Версия модели с ходом этапов в поток. Шаги трассы приходят из потоков инструментов — в очередь через loop."""
    loop = asyncio.get_running_loop()

    def listener(step: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("stage", {k: step[k] for k in ("stage", "name", "detail", "status")}))

    def on_milestone(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("progress", event))

    token, mtoken = stages.progress.set(listener), stages.milestone.set(on_milestone)
    try:
        return await _build(c, role, n, request_id, None)
    finally:
        stages.progress.reset(token)
        stages.milestone.reset(mtoken)


async def _events(c: dict, role: str, n: dict, request_id: str, request: Request) -> AsyncIterator[bytes]:
    cached = await asyncio.to_thread(storage.cached_insight, c["company_id"], role, n["news_id"])
    final = cached and not (cached["mode"] == "rules" and llm.available() and not storage.llm_attempted(cached))
    rules = cached or await _build(c, role, n, request_id, False)
    rules = _valid(rules)
    for chunk in _sections(rules):
        yield chunk
    yield _event("insight", rules)
    yield _event("sources", {"sources": rules["sources"]})
    if final or not llm.available():
        # Как POST /insights: разбор правил без модели объясняет, почему модели нет сейчас (плашка в карточке).
        if rules["mode"] == "rules" and not rules.get("fallback_reason") and not llm.available():
            rules = {**rules, "fallback_reason": llm.unavailable_reason()}
        yield _event("done", rules)
        return
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_upgrade(c, role, n, f"{request_id}-llm", queue))
    while not task.done():
        try:
            name, data = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            yield _event(name, data)
        except asyncio.TimeoutError:
            yield b": heartbeat\n\n"  # прокси не закрывает тихое соединение
        if await request.is_disconnected():
            task.cancel()  # пользователь ушел со страницы — разбор моделью не нужен
            return
    while not queue.empty():
        name, data = queue.get_nowait()
        yield _event(name, data)
    try:
        full = _valid(task.result())
    except Exception as exc:  # модель не ответила или тайм-аут: у пользователя остается проверенный разбор правил
        logger.warning("stream upgrade failed request_id=%s: %s", request_id, type(exc).__name__)
        yield _event("error", {"code": "ANALYSIS_UNAVAILABLE", "message": "AI-версия сейчас недоступна", "retryable": True})
        yield _event("done", rules)
        return
    yield _event("review", {"quality": full["quality"]})
    if full["mode"] == "llm":
        for chunk in _sections(full, "section_replaced", rules):
            yield chunk
    yield _event("done", full)


@router.get("/insights/stream", responses=ERRORS, response_class=StreamingResponse)
async def insight_stream(request: Request, company_id: str = Query(..., max_length=64), news_id: str = Query(..., max_length=64),
                         perspective: Role | None = Query(None), user: dict = Depends(limited("insights"))):
    """Разбор потоком событий: проверенный разбор правил сразу, версия модели — по мере готовности."""
    role = perspective or member_of(user, company_id)["role"]
    member_of(user, company_id)
    c, n = await asyncio.to_thread(lambda: (_company(company_id), _news(news_id)))
    request_id: str = request.state.request_id

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in _events(c, role, n, request_id, request):
                yield chunk
        except ApiError as exc:
            yield _event("error", {"code": exc.code, "message": exc.message or "Не удалось подготовить разбор", "retryable": False})
        except Exception:  # noqa: BLE001
            logger.exception("insight stream failed request_id=%s", request_id)
            yield _event("error", {"code": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервиса", "retryable": True})

    # X-Accel-Buffering: nginx отдает события сразу, без буферизации ответа.
    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
