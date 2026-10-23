"""Конфигурация из переменных окружения (читается при каждом обращении — удобно для тестов)."""

import os
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str:
    if not os.environ.get("DATABASE_URL") and os.environ.get("PGHOST"):
        from sqlalchemy.engine import URL
        return URL.create("postgresql+psycopg", host=os.environ["PGHOST"], port=int(os.environ.get("PGPORT", "5432")),
                          database=os.environ.get("PGDATABASE", "alfa"), username=os.environ.get("PGUSER", "alfa"),
                          password=os.environ.get("PGPASSWORD", "")).render_as_string(hide_password=False)
    return _env("DATABASE_URL", "postgresql://alfa:alfa-local@127.0.0.1:5432/alfa")


def database_schema() -> str:
    return _env("DATABASE_SCHEMA", "public")

ALLOWED_MODELS = (
    "gemma-4-26b-a4b",
    "glm-5.3-flash",
    "qwen3.6-35b-a3b",
    "deepseek-v4.1-flash",
    "qwen3-vl-30b-a3b-instruct",
    "kimi-k2.6",
)

DEFAULT_RSS = [
    {"name": "Банк России", "url": "https://www.cbr.ru/rss/eventrss"},
    {"name": "Интерфакс", "url": "https://www.interfax.ru/rss.asp"},
    {"name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"},
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml"},
]


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def data_dir() -> Path:
    return Path(_env("DATA_DIR", str(REPO_ROOT / "data" / "synthetic")))


def fallback_data_dir() -> Path:
    return Path(_env("FALLBACK_DATA_DIR", str(REPO_ROOT / "data" / "synthetic")))


def runtime_dir() -> Path:
    path = Path(_env("RUNTIME_DIR", str(REPO_ROOT / "data" / "runtime")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_path() -> Path:
    return Path(_env("PROFILES_PATH", str(runtime_dir() / "companies.json")))


def analysis_timeout() -> float:
    return float(_env("ANALYSIS_TIMEOUT_SECONDS", "150"))


def frontend_origin() -> str:
    return _env("FRONTEND_ORIGIN", "http://localhost:3000")


def frontend_origins() -> list[str]:
    """Allow both loopback names on the configured port for local development."""
    origin = frontend_origin().rstrip("/")
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or parts.hostname not in ("localhost", "127.0.0.1"):
        return [origin]
    alias = "127.0.0.1" if parts.hostname == "localhost" else "localhost"
    netloc = f"{alias}:{parts.port}" if parts.port is not None else alias
    return [origin, parts._replace(netloc=netloc).geturl()]


def rss_sources() -> list[dict]:
    raw = os.environ.get("RSS_SOURCES")
    if raw is None:
        return DEFAULT_RSS
    out = []
    for part in raw.split(","):
        if "|" in part:
            name, url = part.split("|", 1)
            out.append({"name": name.strip(), "url": url.strip()})
    return out


def rss_max_items() -> int:
    return int(_env("RSS_MAX_ITEMS", "30"))


def rss_refresh_minutes() -> int:
    return int(_env("RSS_REFRESH_MINUTES", "0"))


def llm_settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "fallback_base_url": os.environ.get("LLM_FALLBACK_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        # Модель на каждую роль агента. Выбор по сравнению всех моделей кейса на одной реальной задаче:
        # DeepSeek пишет самые конкретные выводы (≈26 с, 0,3 ₽), GLM быстрая и точная для плана и проверки
        # (≈13 с, 0,1 ₽), Kimi-K2.6 тратит >7000 токенов на рассуждения и не укладывается во время ответа.
        # Критик — другая модель, чем автор разбора, чтобы проверка была независимой.
        "models": {
            "plan": _env("LLM_MODEL_PLAN", "z-ai/glm-5.3-flash"),
            "compose": _env("LLM_MODEL_COMPOSE", "deepseek/deepseek-v4.1-flash"),
            "review": _env("LLM_MODEL_REVIEW", "z-ai/glm-5.3-flash"),
            "qa": _env("LLM_MODEL_QA", "deepseek/deepseek-v4.1-flash"),
        },
        # GLM без ограничения тратит весь лимит на рассуждения; DeepSeek с ним, наоборот, рассуждает дольше.
        "reasoning_effort": os.environ.get("LLM_REASONING_EFFORT", "low"),
        "reasoning_effort_models": [m.strip() for m in _env("LLM_REASONING_EFFORT_MODELS", "glm").split(",") if m.strip()],
        "daily_token_limit": int(_env("LLM_DAILY_TOKEN_LIMIT", "400000")),
        "timeout": float(_env("LLM_TIMEOUT_SECONDS", "75")),
        # Провайдер кейса возвращает usage.cost в рублях; бюджет — 500 ₽/день на команду.
        "daily_cost_limit": float(_env("LLM_DAILY_COST_LIMIT", "450")),
    }


def bank_pdf_dir() -> Path | None:
    value = os.environ.get("BANK_PDF_DIR")
    return Path(value) if value and Path(value).is_dir() else None


def embeddings_settings() -> dict:
    """Локальная embedding-модель для смыслового сравнения (не генеративная LLM — разрешена кейсом)."""
    return {
        "enabled": _env("EMBEDDINGS_ENABLED", "1").lower() not in ("0", "false", "no", "off"),
        "model": _env("EMBEDDINGS_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
        "cache_dir": os.environ.get("EMBEDDINGS_CACHE_DIR") or None,
        "batch_size": int(_env("EMBEDDINGS_BATCH_SIZE", "32")),
        # Векторы хранятся в PostgreSQL (pgvector); 0 — только в памяти процесса.
        "persist": _env("EMBEDDINGS_PERSIST", "1").lower() not in ("0", "false", "no", "off"),
    }


def redis_url() -> str | None:
    """Общий кэш ленты и служебных значений; без адреса — кэш в памяти процесса."""
    return os.environ.get("REDIS_URL") or None


def feed_cache_seconds() -> int:
    return int(_env("FEED_CACHE_SECONDS", "300"))


def warm_feeds_on_start() -> bool:
    return _env("WARM_FEEDS_ON_START", "1").lower() not in ("0", "false", "no", "off")
