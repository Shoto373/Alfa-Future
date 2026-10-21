from fastapi import FastAPI

app = FastAPI(title="Alfa Pulse Monolith", version="0.1.0")


@app.get("/")
def read_root():
    return {"message": "Hello World", "service": "Alfa Pulse Monolith"}


@app.get("/health")
@app.get("/healthz")
def health():
    return {"status": "ok", "service": "backend"}
