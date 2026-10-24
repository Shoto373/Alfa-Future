import asyncio
import contextlib
import logging

from fastapi import FastAPI

from app import database, demo_accounts, legacy_import, warmup
from app.api.router import router
from app.api.setup import configure_api
from app.auth.router import router as auth_router
from app.schemas import SCHEMA_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(database.migrate)
    # Учетные записи из прежнего JSON-хранилища (RUNTIME_DIR) — в PostgreSQL, один раз; файлы остаются.
    imported = await asyncio.to_thread(legacy_import.import_auth_once)
    if imported and any(imported.values()):
        logger.info("auth imported from runtime JSON: %s", imported)
    # Прогрев: профили, модель, векторы, база знаний и новости — до приема запросов. Фоновые задачи
    # (сбор новостей, предрасчет, переклассификация) API не запускает — это отдельный воркер (app/worker).
    app.state.warmup = await asyncio.to_thread(warmup.run, "api")
    try:  # локальная проверка: готовые учетные записи (DEMO_ACCOUNTS=1 только в compose.yaml)
        demo = await asyncio.to_thread(demo_accounts.ensure)
        if demo and demo["created"]:
            logger.info("demo accounts created: %s", demo)
    except Exception:  # без демо-записей сервис работает: регистрация открыта
        logger.exception("demo accounts failed")
    yield


app = FastAPI(
    title="Альфа.Пульс API",
    description="Новостная аналитика для руководителей крупного бизнеса: профили компаний, персональная лента, "
                "агентная интерпретация событий с позицией Альфа-Банка и трассировкой.",
    version=SCHEMA_VERSION,  # версия контракта; политика — docs/api-versioning.md
    lifespan=lifespan,
)

configure_api(app)
app.include_router(router)
app.include_router(auth_router)


@app.get("/healthz")
async def healthz():
    await asyncio.to_thread(database.health)
    return {"status": "ok", "service": "backend"}
