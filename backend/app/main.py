import asyncio
import contextlib
import logging

from fastapi import FastAPI

from app import config, database, warmup
from app.api.router import router
from app.api.setup import configure_api
from app.auth.router import router as auth_router
from app.news import parser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")


async def _rss_loop(minutes: int) -> None:
    while True:
        try:
            report = await asyncio.to_thread(parser.refresh)
            logger.info("rss refresh added=%s duplicates=%s", report["added"], report["duplicates"])
        except Exception:  # сбой источника не должен останавливать сервис
            logger.exception("rss refresh failed")
        await asyncio.sleep(minutes * 60)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(database.migrate)
    # Прогрев: профили, модель, векторы, база знаний, новости и ленты — до приема запросов.
    app.state.warmup = await asyncio.to_thread(warmup.run)
    task = None
    if config.rss_refresh_minutes() > 0:
        task = asyncio.create_task(_rss_loop(config.rss_refresh_minutes()))
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Альфа.Пульс API",
    description="Новостная аналитика для руководителей крупного бизнеса: профили компаний, персональная лента, "
                "агентная интерпретация событий с позицией Альфа-Банка и трассировкой.",
    version="1.0.0",
    lifespan=lifespan,
)

configure_api(app)
app.include_router(router)
app.include_router(auth_router)


@app.get("/healthz")
async def healthz():
    await asyncio.to_thread(database.health)
    return {"status": "ok", "service": "backend"}
