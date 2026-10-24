"""Агент подготовки персонализированного разбора: запуск, один разбор на всех ожидающих, учет бюджета.

Сам разбор — конвейер этапов из app/agent/stages.py: план → инструменты → черновик →
проверки и коррекция → итог (подробности — в описании stages).
"""

import asyncio

from app import llm_usage
from app.agent import stages

_inflight: dict[tuple, asyncio.Future] = {}


async def run_once(company: dict, role: str, news: dict, request_id: str, use_llm: bool | None = None,
                   on_built=None, charge_company: bool = True) -> tuple[dict, bool]:
    """Один и тот же разбор (компания, роль, новость, режим) не строится дважды одновременно.

    Второй запрос, пришедший, пока первый еще строится (два сотрудника открыли одну новость, конвейер
    и пользователь), ждет первый и получает его результат — модель вызывается и оплачивается один раз.
    Возвращает (разбор, leader): leader=False — результат чужого запроса, сохранять его повторно не нужно.
    on_built(insight) — проверка и сохранение первым запросом; ждущие получают разбор только после нее,
    поэтому сразу могут задать по нему вопрос. Действует внутри процесса; разборы разных воркеров разводит кэш.
    """
    loop = asyncio.get_running_loop()
    key = (company["company_id"], role, news["news_id"], use_llm is False)
    while (shared := _inflight.get(key)) is not None and shared.get_loop() is loop:
        try:
            return await asyncio.shield(shared), False
        except asyncio.CancelledError:
            if not shared.cancelled():
                raise  # отменили этот запрос, а не первый
            # Первый отменен (тайм-аут) — снова проверяем: ведущим станет один из ждущих, а не каждый.
    future = loop.create_future()
    future.add_done_callback(lambda f: f.cancelled() or f.exception())  # ошибку без ждущих не логировать
    _inflight[key] = future
    try:
        insight = await run(company, role, news, request_id, use_llm=use_llm, charge_company=charge_company)
        if on_built is not None:
            await on_built(insight)
        future.set_result(insight)
        return insight, True
    except asyncio.CancelledError:
        future.cancel()
        raise
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        if _inflight.get(key) is future:
            del _inflight[key]


async def run(company: dict, role: str, news: dict, request_id: str, use_llm: bool | None = None,
              charge_company: bool = True) -> dict:
    """use_llm=False — только правила (быстрый черновой разбор), None — LLM, если подключена.

    Вызовы модели учитываются в доле компании в общем дневном бюджете (llm_usage.for_company);
    charge_company=False — фоновый конвейер банка: у него своя доля, долю компании он не тратит."""
    with llm_usage.for_company(company["company_id"] if charge_company else None):
        return await _run(company, role, news, request_id, use_llm)


async def _run(company: dict, role: str, news: dict, request_id: str, use_llm: bool | None = None) -> dict:
    run = stages.start(company, role, news, request_id, use_llm)
    steps, planner = stages.plan(run)
    await stages.collect(run, steps, planner)
    await stages.draft(run)
    await stages.verify_and_fix(run)
    return stages.finalize(run)
