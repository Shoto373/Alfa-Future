from fastapi import FastAPI

app = FastAPI(
    title="Alfa Pulse Monolith Backend",
    description="Python/FastAPI монолит для сервиса новостной аналитики Альфа.Пульс",
    version="0.1.0",
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "backend"}
