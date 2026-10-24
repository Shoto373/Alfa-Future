import asyncio
import contextlib
import logging

from fastapi import FastAPI

from app import database, demo_accounts, legacy_import, observability, warmup
from app.api.admin_config import router as admin_config_router
from app.api.admin_kb import router as admin_kb_router
from app.api.admin_labeling import router as admin_labeling_router
from app.api.prometheus import router as metrics_router
from app.api.router import router
from app.api.notifications import public as notifications_public
from app.api.notifications import router as notifications_router
from app.api.stream import router as stream_router
from app.api.setup import configure_api
from app.auth.router import router as auth_router
from app.schemas import API_VERSION

observability.configure_logging()
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
    version=API_VERSION,  # версия контракта; политика — docs/api-versioning.md
    lifespan=lifespan,
)

configure_api(app)
# Поток разбора — раньше основного роутера: иначе /insights/stream перехватил бы /insights/{insight_id}.
app.include_router(stream_router)
app.include_router(router)
app.include_router(auth_router)
app.include_router(admin_kb_router)
app.include_router(admin_config_router)
app.include_router(admin_labeling_router)
app.include_router(notifications_router)
app.include_router(notifications_public)
app.include_router(metrics_router)


@app.get("/healthz")
async def healthz():
    await asyncio.to_thread(database.health)
    return {"status": "ok", "service": "backend"}
