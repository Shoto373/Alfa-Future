import logging

from fastapi import FastAPI

from app.api.router import router
from app.api.setup import configure_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Alfa Pulse Monolith Backend",
    description="Python/FastAPI монолит для сервиса новостной аналитики Альфа.Пульс",
    version="0.1.0",
)

configure_api(app)
app.include_router(router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "backend"}
