import asyncio
import contextlib
import logging

from fastapi import FastAPI

from app import config
from app.api.router import router
from app.api.setup import configure_api
from app.companies import profiles
from app.news import parser, store

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
    try:
        await asyncio.to_thread(profiles.meta)  # прогрев: построить профили, если кэша нет
    except profiles.ProfilesError:
        logger.exception("company profiles unavailable at startup")
    await asyncio.to_thread(store.all_items)
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


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "backend"}
